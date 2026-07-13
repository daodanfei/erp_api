from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import (
    OutboundOrder, OutboundOrderItem,
    TransferOrder, TransferOrderItem,
    SalesReturnOrder, SalesReturnOrderItem,
    PurchaseReturnOrder, PurchaseReturnOrderItem,
    InventoryAlert,
)
from business_apps.inventory.services import InventoryService
from business_apps.inventory.models import Inventory
from business_apps.platform.services import CodeRuleService
from core_apps.common.viewsets import apply_erp_tenant_scope
from core_apps.erp_auth.compat import (
    build_erp_user_and_dept_kwargs,
    get_erp_user_id,
)
from core_apps.policies.registry import get_policy


def _aggregate_requested_quantities(items_data):
    requested_quantities = {}
    for item in items_data:
        product = item["product"]
        quantity = Decimal(str(item["quantity"]))
        if quantity <= 0:
            raise ValueError(f"退货数量必须大于0：{product.name}")
        requested_quantities[product.id] = requested_quantities.get(product.id, Decimal("0")) + quantity
    return requested_quantities


def _allocate_quantity_to_source_lines(source_lines, quantity_field, requested_quantity):
    remaining = Decimal(str(requested_quantity))
    allocations = []

    for source_line in source_lines:
        if isinstance(source_line, dict):
            available_quantity = Decimal(str(source_line.get(quantity_field, 0)))
        else:
            available_quantity = Decimal(str(getattr(source_line, quantity_field, 0)))
        if available_quantity <= 0 or remaining <= 0:
            continue
        allocated_quantity = min(available_quantity, remaining)
        allocations.append((source_line, allocated_quantity))
        remaining -= allocated_quantity

    if remaining > 0:
        raise ValueError("退货数量超过来源单据可退数量")

    return allocations


class OutboundService:
    @staticmethod
    def generate_no():
        return CodeRuleService.generate('OUTBOUND_ORDER')

    @staticmethod
    def validate_products(items_data):
        for item in items_data:
            product = item['product']
            if product.status == 'DRAFT':
                raise ValueError(f"商品为草稿状态，禁止参与业务：{product.name}")
            if product.status == 'DISABLED':
                raise ValueError(f"商品已停用：{product.name}")

    @staticmethod
    def validate_order_references(order):
        if order.sales_order_id and order.sales_order.customer.status == 'BLACKLIST':
            raise ValueError("黑名单客户禁止创建出库单")
        OutboundService.validate_products(
            [{'product': item.product} for item in order.items.select_related('product').all()]
        )

    @staticmethod
    @transaction.atomic
    def create_order(sales_order, warehouse, items_data, user, remark=None):
        if sales_order and sales_order.customer.status == 'BLACKLIST':
            raise ValueError("黑名单客户禁止创建出库单")
        OutboundService.validate_products(items_data)
        order = OutboundOrder.objects.create(
            tenant=sales_order.tenant if sales_order else warehouse.tenant,
            outbound_no=OutboundService.generate_no(),
            sales_order=sales_order,
            warehouse=warehouse,
            status='DRAFT',
            remark=remark,
            **build_erp_user_and_dept_kwargs(OutboundOrder, user=user),
        )
        for item in items_data:
            product = item['product']
            qty = Decimal(str(item['quantity']))
            price = Decimal(str(item.get('unit_price', product.cost_price or 0)))
            OutboundOrderItem.objects.create(
                tenant=order.tenant,
                outbound_order=order,
                sales_order_item=item.get('sales_order_item'),
                product=product,
                product_name_snapshot=product.name,
                product_code_snapshot=product.product_code,
                quantity=qty,
                unit_price=price,
                amount=qty * price,
                remark=item.get('remark', ''),
            )
        return order

    @staticmethod
    @transaction.atomic
    def create_from_sales_order(order, items_data, user, remark=None):
        policy = get_policy("supply_chain", user=user)
        allowed_statuses = ['ALLOCATED', 'PARTIALLY_SHIPPED']
        if not policy.outbound_requires_allocation():
            allowed_statuses = ['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED']
        if order.status not in allowed_statuses:
            raise ValueError("库存锁定后才能生成销售出库单")

        warehouse_groups = {}
        total_qty = Decimal('0')
        for item in items_data:
            order_item = item['order_item']
            qty = Decimal(str(item['quantity']))
            from business_apps.sales.services import SalesOrderService

            open_outbound_qty = SalesOrderService.get_open_outbound_quantity(order_item)
            pending_qty = (
                Decimal(str(order_item.quantity))
                - Decimal(str(order_item.shipped_quantity))
                - open_outbound_qty
            )

            if order_item.order_id != order.id:
                raise ValueError("出库明细与销售订单不匹配")
            if not order_item.warehouse_id:
                raise ValueError(f"请先为商品 {order_item.product.name} 选择发货仓库")
            if qty <= 0:
                continue
            if qty > pending_qty:
                raise ValueError(f"出库数量不能大于待出库数量：{order_item.product.name}")

            total_qty += qty
            warehouse_groups.setdefault(order_item.warehouse_id, {
                'warehouse': order_item.warehouse,
                'items': [],
            })['items'].append({
                'sales_order_item': order_item,
                'product': order_item.product,
                'quantity': qty,
                'unit_price': order_item.unit_price,
                'remark': item.get('remark', '') or order.remark or '',
            })

        if total_qty <= 0:
            raise ValueError("请输入出库数量")

        outbound_orders = []
        for group in warehouse_groups.values():
            outbound_order = OutboundService.create_order(
                sales_order=order,
                warehouse=group['warehouse'],
                items_data=group['items'],
                user=user,
                remark=remark or order.remark,
            )
            outbound_orders.append(outbound_order)

        return outbound_orders

    @staticmethod
    @transaction.atomic
    def submit_order(order, user):
        """提交审核：DRAFT -> PENDING"""
        if not order.can_transition_to('PENDING'):
            raise ValueError("当前状态不允许提交审核")
        if order.items.count() == 0:
            raise ValueError("出库明细不能为空")
        OutboundService.validate_order_references(order)
        order.status = 'PENDING'
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None:
            order.submitted_by_id = erp_user_id
        else:
            order.submitted_by = None
        order.submitted_at = timezone.now()
        order.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order, user):
        """审核：PENDING -> APPROVED"""
        if order.status != 'PENDING':
            raise ValueError("只有待审核状态的出库单可以审核")
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and (
            order.created_by_id == erp_user_id or order.submitted_by_id == erp_user_id
        ):
            raise ValueError("审核人不能是出库单创建人或提交人")
        order.status = 'APPROVED'
        if erp_user_id is not None:
            order.approved_by_id = erp_user_id
        else:
            order.approved_by = None
        order.approved_at = timezone.now()
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def complete_order(order, user):
        """执行出库：扣减库存，二次校验库存充足性"""
        order = OutboundOrder.objects.select_for_update().get(id=order.id)
        policy = get_policy("supply_chain", user=user)
        if order.status != 'APPROVED':
            raise ValueError("只有已审核状态的出库单可以执行")

        # 二次校验：逐项检查库存充足性
        for item in order.items.all():
            try:
                inv = Inventory.objects.get(warehouse=order.warehouse, product=item.product)
                if item.sales_order_item_id:
                    locked_for_order = Decimal(str(item.sales_order_item.allocated_quantity))
                    if policy.outbound_requires_allocation() and locked_for_order < item.quantity:
                        raise ValueError(
                            f"锁定库存不足：{item.product_name_snapshot}，"
                            f"已锁定{locked_for_order}，出库数量{item.quantity}"
                        )
                    if inv.current_qty < item.quantity:
                        raise ValueError(
                            f"库存不足：{item.product_name_snapshot}，"
                            f"当前库存{inv.current_qty}，出库数量{item.quantity}"
                        )
                else:
                    available = inv.current_qty - inv.locked_qty
                    if available < item.quantity:
                        raise ValueError(
                            f"库存不足：{item.product_name_snapshot}，"
                            f"可用库存{available}，出库数量{item.quantity}"
                        )
            except Inventory.DoesNotExist:
                raise ValueError(f"库存不足：{item.product_name_snapshot}，无库存记录")

        for item in order.items.all():
            InventoryService.ship_stock(
                warehouse=order.warehouse,
                product=item.product,
                quantity=item.quantity,
                operator=user,
                reference_type='OUTBOUND_ORDER',
                reference_id=order.id,
                remark=f"销售出库: {order.outbound_no}"
            )

            if item.sales_order_item_id:
                order_item = item.sales_order_item
                order_item.shipped_quantity += item.quantity
                order_item.allocated_quantity = max(
                    Decimal('0'),
                    Decimal(str(order_item.allocated_quantity)) - Decimal(str(item.quantity)),
                )
                order_item.save(update_fields=['shipped_quantity', 'allocated_quantity'])

        order.status = 'COMPLETED'
        order.completed_at = timezone.now()
        order.save()

        if order.sales_order_id:
            sales_order = order.sales_order
            sales_items = sales_order.items.all()
            shipped_all = all(item.shipped_quantity >= item.quantity for item in sales_items)
            shipped_any = any(item.shipped_quantity > 0 for item in sales_items)
            if shipped_all:
                sales_order.status = 'SHIPPED'
            elif shipped_any:
                sales_order.status = 'PARTIALLY_SHIPPED'
            else:
                sales_order.status = 'ALLOCATED'
            sales_order.save(update_fields=['status', 'updated_at'])

            from business_apps.ar_receivable.services import ARService
            sales_policy = get_policy("sales", user=user)
            ar_policy = get_policy("ar_receivable", user=user)
            if (
                sales_policy.outbound_auto_ar_enabled()
                and ar_policy.auto_create_receivable_enabled()
                and not order.receivables.filter(is_deleted=False).exists()
            ):
                ARService.generate_ar_from_outbound(order, user)
            from business_apps.accounting.services import PostingService
            PostingService.post_sales_outbound(order, user)
        return order

    @staticmethod
    @transaction.atomic
    def cancel_order(order, user):
        if not order.can_transition_to('CANCELLED'):
            raise ValueError("当前状态不允许取消")
        order.status = 'CANCELLED'
        order.save()
        return order


class TransferService:
    @staticmethod
    def generate_no():
        return CodeRuleService.generate('TRANSFER_ORDER')

    @staticmethod
    def validate_products(items_data):
        for item in items_data:
            product = item['product']
            if product.status == 'DRAFT':
                raise ValueError(f"商品为草稿状态，禁止参与业务：{product.name}")
            if product.status == 'DISABLED':
                raise ValueError(f"商品已停用：{product.name}")

    @staticmethod
    def validate_order_references(order):
        TransferService.validate_products(
            [{'product': item.product} for item in order.items.select_related('product').all()]
        )

    @staticmethod
    def format_quantity(value):
        return Decimal(str(value)).quantize(Decimal("0.001"))

    @staticmethod
    def validate_stock_availability(from_warehouse, items_data):
        product_totals = {}
        product_refs = {}

        for item in items_data:
            product = item['product']
            quantity = Decimal(str(item['quantity']))
            if quantity <= 0:
                raise ValueError(f"调拨数量必须大于0：{product.name}")
            product_totals[product.id] = product_totals.get(product.id, Decimal("0")) + quantity
            product_refs[product.id] = product

        if not product_totals:
            return

        inventory_map = {
            inventory.product_id: inventory
            for inventory in Inventory.objects.filter(
                warehouse=from_warehouse,
                product_id__in=product_totals.keys(),
            )
        }

        for product_id, total_quantity in product_totals.items():
            product = product_refs[product_id]
            inventory = inventory_map.get(product_id)
            if inventory is None:
                raise ValueError(f"调出仓库无库存：{product.name}")
            if inventory.available_qty < total_quantity:
                raise ValueError(
                    f"调出仓库可用库存不足：{product.name}，"
                    f"可用库存{TransferService.format_quantity(inventory.available_qty)}，"
                    f"调拨数量{TransferService.format_quantity(total_quantity)}"
                )

    @staticmethod
    @transaction.atomic
    def create_order(from_warehouse, to_warehouse, items_data, user, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.transfer_enabled():
            raise ValueError("当前配置未启用调拨")
        if from_warehouse.id == to_warehouse.id:
            raise ValueError("禁止同仓库调拨")
        TransferService.validate_products(items_data)
        TransferService.validate_stock_availability(from_warehouse, items_data)

        order = TransferOrder.objects.create(
            tenant=from_warehouse.tenant,
            transfer_no=TransferService.generate_no(),
            from_warehouse=from_warehouse,
            to_warehouse=to_warehouse,
            status='DRAFT',
            remark=remark,
            **build_erp_user_and_dept_kwargs(TransferOrder, user=user),
        )
        for item in items_data:
            product = item['product']
            TransferOrderItem.objects.create(
                tenant=order.tenant,
                transfer_order=order,
                product=product,
                product_name_snapshot=product.name,
                product_code_snapshot=product.product_code,
                quantity=item['quantity'],
                remark=item.get('remark', ''),
            )
        return order

    @staticmethod
    @transaction.atomic
    def update_order(order, from_warehouse, to_warehouse, items_data, user, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.transfer_enabled():
            raise ValueError("当前配置未启用调拨")
        if order.status != 'DRAFT':
            raise ValueError("只有草稿状态的调拨单可以编辑")
        if from_warehouse.id == to_warehouse.id:
            raise ValueError("禁止同仓库调拨")
        TransferService.validate_products(items_data)
        TransferService.validate_stock_availability(from_warehouse, items_data)

        order.from_warehouse = from_warehouse
        order.to_warehouse = to_warehouse
        if remark is not None:
            order.remark = remark
        order.save()

        if items_data is not None:
            if len(items_data) == 0:
                raise ValueError("调拨单明细不能为空")
            order.items.all().delete()
            for item in items_data:
                product = item['product']
                TransferOrderItem.objects.create(
                    tenant=order.tenant,
                    transfer_order=order,
                    product=product,
                    product_name_snapshot=product.name,
                    product_code_snapshot=product.product_code,
                    quantity=Decimal(str(item['quantity'])),
                    remark=item.get('remark', ''),
                )
        return order

    @staticmethod
    @transaction.atomic
    def submit_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if order.status != 'DRAFT':
            raise ValueError("只有草稿状态的调拨单可以提交审核")
        if order.items.count() == 0:
            raise ValueError("调拨单明细不能为空")
        TransferService.validate_order_references(order)
        TransferService.validate_stock_availability(
            order.from_warehouse,
            [{'product': item.product, 'quantity': item.quantity} for item in order.items.select_related('product').all()],
        )
        erp_user_id = get_erp_user_id(user)
        if policy.transfer_approval_enabled():
            order.status = 'PENDING_APPROVAL'
        else:
            order.status = 'APPROVED'
            if erp_user_id is not None:
                order.approved_by_id = erp_user_id
            else:
                order.approved_by = None
            order.approved_at = timezone.now()
        if erp_user_id is not None:
            order.submitted_by_id = erp_user_id
        else:
            order.submitted_by = None
        order.submitted_at = timezone.now()
        update_fields = ['status', 'submitted_by', 'submitted_at', 'updated_at']
        if not policy.transfer_approval_enabled():
            update_fields.extend(['approved_by', 'approved_at'])
        order.save(update_fields=update_fields)
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order, user):
        if order.status != 'PENDING_APPROVAL':
            raise ValueError("只有待审核状态的调拨单可以审核通过")
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and (
            order.submitted_by_id == erp_user_id or order.created_by_id == erp_user_id
        ):
            raise ValueError("审核人不能是提交人或创建人")
        order.status = 'APPROVED'
        if erp_user_id is not None:
            order.approved_by_id = erp_user_id
        else:
            order.approved_by = None
        order.approved_at = timezone.now()
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def start_transfer(order, user):
        """调出确认：APPROVED -> IN_TRANSIT，扣减调出仓库库存"""
        order = TransferOrder.objects.select_for_update().get(id=order.id)
        if order.status != 'APPROVED':
            raise ValueError("只有已审核状态的调拨单可以调出确认")
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and order.approved_by_id == erp_user_id:
            raise ValueError("调出确认人不能是审核人")

        TransferService.validate_stock_availability(
            order.from_warehouse,
            [{'product': item.product, 'quantity': item.quantity} for item in order.items.select_related('product').all()],
        )

        for item in order.items.all():
            InventoryService.change_stock(
                warehouse=order.from_warehouse,
                product=item.product,
                quantity=-item.quantity,
                transaction_type='TRANSFER_OUT',
                operator=user,
                reference_type='TRANSFER_ORDER',
                reference_id=order.id,
                remark=f"调拨出库: {order.transfer_no}"
            )

        if erp_user_id is not None:
            order.outbound_confirmed_by_id = erp_user_id
        else:
            order.outbound_confirmed_by = None
        order.outbound_confirmed_at = timezone.now()
        order.status = 'IN_TRANSIT'
        order.save(update_fields=['status', 'outbound_confirmed_by', 'outbound_confirmed_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def complete_transfer(order, user):
        """调入确认：IN_TRANSIT -> COMPLETED，增加调入仓库库存"""
        order = TransferOrder.objects.select_for_update().get(id=order.id)
        if order.status != 'IN_TRANSIT':
            raise ValueError("只有调拨中状态的调拨单可以调入确认")
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and order.outbound_confirmed_by_id == erp_user_id:
            raise ValueError("调入确认人不能是调出确认人")

        for item in order.items.all():
            InventoryService.change_stock(
                warehouse=order.to_warehouse,
                product=item.product,
                quantity=item.quantity,
                transaction_type='TRANSFER_IN',
                operator=user,
                reference_type='TRANSFER_ORDER',
                reference_id=order.id,
                remark=f"调拨入库: {order.transfer_no}"
            )

        if erp_user_id is not None:
            order.inbound_confirmed_by_id = erp_user_id
        else:
            order.inbound_confirmed_by = None
        order.inbound_confirmed_at = timezone.now()
        order.status = 'COMPLETED'
        order.completed_at = timezone.now()
        order.save(update_fields=['status', 'inbound_confirmed_by', 'inbound_confirmed_at', 'completed_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def cancel_transfer(order, user):
        """取消调拨：DRAFT直接取消；IN_TRANSIT需回滚调出仓库库存"""
        order = TransferOrder.objects.select_for_update().get(id=order.id)
        if not order.can_transition_to('CANCELLED'):
            raise ValueError("当前状态不允许取消")

        if order.status == 'IN_TRANSIT':
            # 回滚调出仓库库存
            for item in order.items.all():
                InventoryService.change_stock(
                    warehouse=order.from_warehouse,
                    product=item.product,
                    quantity=item.quantity,
                    transaction_type='TRANSFER_IN',
                    operator=user,
                    reference_type='TRANSFER_ORDER',
                    reference_id=order.id,
                    remark=f"调拨取消回滚: {order.transfer_no}"
                )

        order.status = 'CANCELLED'
        order.cancelled_at = timezone.now()
        order.save(update_fields=['status', 'cancelled_at', 'updated_at'])
        return order


class SalesReturnService:
    @staticmethod
    def generate_no():
        return CodeRuleService.generate('SALES_RETURN')

    @staticmethod
    def validate_customer(customer):
        if customer and customer.status == 'BLACKLIST':
            raise ValueError("黑名单客户禁止创建销售退货单")
        if customer and customer.status != 'ACTIVE':
            raise ValueError("未激活客户禁止创建销售退货单")

    @staticmethod
    def validate_products(items_data):
        for item in items_data:
            product = item['product']
            if product.status == 'DRAFT':
                raise ValueError(f"商品为草稿状态，禁止参与业务：{product.name}")
            if product.status == 'DISABLED':
                raise ValueError(f"商品已停用：{product.name}")

    @staticmethod
    def _resolve_customer(customer, sales_order):
        if sales_order and customer and sales_order.customer_id != customer.id:
            raise ValueError("销售退货单客户必须与销售订单一致")
        return customer or (sales_order.customer if sales_order else None)

    @staticmethod
    def _require_sales_order(sales_order):
        if sales_order is None:
            raise ValueError("销售退货单必须关联销售订单")

    @staticmethod
    def _validate_return_quantities(sales_order, items_data, exclude_return_order_id=None):
        SalesReturnService._require_sales_order(sales_order)

        requested_quantities = _aggregate_requested_quantities(items_data)
        shipped_quantities = {}
        for order_item in sales_order.items.all():
            shipped_quantity = Decimal(str(order_item.shipped_quantity))
            if shipped_quantity <= 0:
                continue
            shipped_quantities[order_item.product_id] = shipped_quantities.get(order_item.product_id, Decimal("0")) + shipped_quantity

        existing_returns = sales_order.return_orders.exclude(status="CANCELLED")
        if exclude_return_order_id is not None:
            existing_returns = existing_returns.exclude(id=exclude_return_order_id)

        occupied_quantities = {}
        for return_item in SalesReturnOrderItem.objects.filter(return_order__in=existing_returns):
            occupied_quantities[return_item.product_id] = occupied_quantities.get(return_item.product_id, Decimal("0")) + Decimal(str(return_item.quantity))

        for product_id, requested_quantity in requested_quantities.items():
            product = next(item["product"] for item in items_data if item["product"].id == product_id)
            available_quantity = shipped_quantities.get(product_id, Decimal("0")) - occupied_quantities.get(product_id, Decimal("0"))
            if requested_quantity > available_quantity:
                raise ValueError(
                    f"销售退货数量超出可退范围：{product.name}，"
                    f"已发货{shipped_quantities.get(product_id, Decimal('0')):.3f}，"
                    f"其他退货已占用{occupied_quantities.get(product_id, Decimal('0')):.3f}，"
                    f"本次申请{requested_quantity:.3f}"
                )

    @staticmethod
    def build_sales_order_item_allocations(return_order, exclude_return_order_id=None):
        sales_order = return_order.sales_order
        if sales_order is None:
            return {}

        source_lines_by_product = {}
        for source_line in sales_order.items.order_by("id"):
            source_lines_by_product.setdefault(source_line.product_id, []).append({
                "order_item": source_line,
                "remaining_quantity": Decimal(str(source_line.shipped_quantity)),
            })

        previous_returns = sales_order.return_orders.filter(status="COMPLETED")
        if exclude_return_order_id is not None:
            previous_returns = previous_returns.exclude(id=exclude_return_order_id)

        for previous_item in SalesReturnOrderItem.objects.filter(return_order__in=previous_returns).order_by("id"):
            source_lines = source_lines_by_product.get(previous_item.product_id, [])
            allocations = _allocate_quantity_to_source_lines(
                source_lines,
                "remaining_quantity",
                previous_item.quantity,
            )
            for source_line, allocated_quantity in allocations:
                source_line["remaining_quantity"] -= allocated_quantity

        allocations_by_product = {}
        for item in return_order.items.all().order_by("id"):
            source_lines = source_lines_by_product.get(item.product_id, [])
            allocations = _allocate_quantity_to_source_lines(
                source_lines,
                "remaining_quantity",
                item.quantity,
            )
            allocations_by_product[item.id] = [
                (allocation["order_item"], allocated_quantity)
                for allocation, allocated_quantity in allocations
            ]
            for allocation, allocated_quantity in allocations:
                allocation["remaining_quantity"] -= allocated_quantity

        return allocations_by_product

    @staticmethod
    @transaction.atomic
    def create_order(customer, sales_order, warehouse, items_data, user, reason=None, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.sales_return_enabled():
            raise ValueError("当前配置未启用销售退货")
        SalesReturnService._require_sales_order(sales_order)
        customer = SalesReturnService._resolve_customer(customer, sales_order)
        SalesReturnService.validate_customer(customer)
        SalesReturnService.validate_products(items_data)
        SalesReturnService._validate_return_quantities(sales_order, items_data)
        order = SalesReturnOrder.objects.create(
            tenant=sales_order.tenant,
            return_no=SalesReturnService.generate_no(),
            customer=customer,
            customer_name_snapshot=customer.customer_name if customer else None,
            sales_order=sales_order,
            warehouse=warehouse,
            status='DRAFT',
            reason=reason,
            remark=remark,
            **build_erp_user_and_dept_kwargs(SalesReturnOrder, user=user),
        )
        for item in items_data:
            product = item['product']
            SalesReturnOrderItem.objects.create(
                tenant=order.tenant,
                return_order=order,
                product=product,
                product_name_snapshot=product.name,
                product_code_snapshot=product.product_code,
                quantity=item['quantity'],
                remark=item.get('remark', ''),
            )
        return order

    @staticmethod
    @transaction.atomic
    def submit_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if order.status != 'DRAFT':
            raise ValueError("只有草稿状态的销售退货单可以提交审核")
        if order.items.count() == 0:
            raise ValueError("销售退货单明细不能为空")
        SalesReturnService._require_sales_order(order.sales_order)
        SalesReturnService.validate_customer(order.customer)
        SalesReturnService.validate_products(
            [{"product": item.product, "quantity": item.quantity} for item in order.items.select_related("product").all()]
        )
        SalesReturnService._validate_return_quantities(
            order.sales_order,
            [{"product": item.product, "quantity": item.quantity} for item in order.items.select_related("product").all()],
            exclude_return_order_id=order.id,
        )
        erp_user_id = get_erp_user_id(user)
        if policy.return_approval_enabled():
            order.status = 'PENDING_APPROVAL'
        else:
            order.status = 'APPROVED'
            if erp_user_id is not None:
                order.approved_by_id = erp_user_id
            else:
                order.approved_by = None
            order.approved_at = timezone.now()
        if erp_user_id is not None:
            order.submitted_by_id = erp_user_id
        else:
            order.submitted_by = None
        order.submitted_at = timezone.now()
        update_fields = ['status', 'submitted_by', 'submitted_at', 'updated_at']
        if not policy.return_approval_enabled():
            update_fields.extend(['approved_by', 'approved_at'])
        order.save(update_fields=update_fields)
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if policy.return_approval_enabled():
            if order.status != 'PENDING_APPROVAL':
                raise ValueError("只有待审核状态的销售退货单可以审核")
        elif not order.can_transition_to('APPROVED'):
            raise ValueError("当前状态不允许审核")
        erp_user_id = get_erp_user_id(user)
        if order.created_by and erp_user_id is not None and order.created_by_id == erp_user_id:
            raise ValueError("审核人不能是单据创建人")
        if order.submitted_by and erp_user_id is not None and order.submitted_by_id == erp_user_id:
            raise ValueError("审核人不能是单据提交人")
        order.status = 'APPROVED'
        if erp_user_id is not None:
            order.approved_by_id = erp_user_id
        else:
            order.approved_by = None
        order.approved_at = timezone.now()
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def complete_order(order, user):
        """完成退货：库存增加"""
        order = SalesReturnOrder.objects.select_for_update().get(id=order.id)
        if not order.can_transition_to('COMPLETED'):
            raise ValueError("当前状态不允许完成退货")
        SalesReturnService._require_sales_order(order.sales_order)
        SalesReturnService._validate_return_quantities(
            order.sales_order,
            [{"product": item.product, "quantity": item.quantity} for item in order.items.all()],
            exclude_return_order_id=order.id,
        )

        for item in order.items.all():
            InventoryService.change_stock(
                warehouse=order.warehouse,
                product=item.product,
                quantity=item.quantity,
                transaction_type='RETURN_IN',
                operator=user,
                reference_type='SALES_RETURN_ORDER',
                reference_id=order.id,
                remark=f"销售退货入库: {order.return_no}"
            )

        order.status = 'COMPLETED'
        order.completed_at = timezone.now()
        if order.customer_id:
            from business_apps.ar_receivable.services import ARService
            ARService.reverse_ar_for_sales_return(order, user)
            from business_apps.accounting.services import PostingService
            PostingService.post_sales_return(order, user)
            order.finance_status = 'ADJUSTED'
        order.save(update_fields=['status', 'completed_at', 'finance_status', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def cancel_order(order, user):
        if not order.can_transition_to('CANCELLED'):
            raise ValueError("当前状态不允许取消")
        order.status = 'CANCELLED'
        order.save()
        return order


class PurchaseReturnService:
    @staticmethod
    def generate_no():
        return CodeRuleService.generate('PURCHASE_RETURN')

    @staticmethod
    def validate_supplier(supplier):
        if supplier and supplier.status == 'BLACKLIST':
            raise ValueError("黑名单供应商禁止创建采购退货单")
        if supplier and supplier.status != 'ACTIVE':
            raise ValueError("未激活供应商禁止创建采购退货单")

    @staticmethod
    def validate_products(items_data):
        for item in items_data:
            product = item['product']
            if product.status == 'DRAFT':
                raise ValueError(f"商品为草稿状态，禁止参与业务：{product.name}")
            if product.status == 'DISABLED':
                raise ValueError(f"商品已停用：{product.name}")

    @staticmethod
    def _resolve_supplier(supplier, purchase_order):
        if purchase_order and supplier and purchase_order.supplier_id != supplier.id:
            raise ValueError("采购退货单供应商必须与采购订单一致")
        return supplier or (purchase_order.supplier if purchase_order else None)

    @staticmethod
    def _require_purchase_order(purchase_order):
        if purchase_order is None:
            raise ValueError("采购退货单必须关联采购订单")

    @staticmethod
    def _validate_return_quantities(purchase_order, items_data, exclude_return_order_id=None):
        PurchaseReturnService._require_purchase_order(purchase_order)

        requested_quantities = _aggregate_requested_quantities(items_data)
        received_quantities = {}
        for order_item in purchase_order.items.all():
            received_quantity = Decimal(str(order_item.received_quantity))
            if received_quantity <= 0:
                continue
            received_quantities[order_item.product_id] = received_quantities.get(order_item.product_id, Decimal("0")) + received_quantity

        existing_returns = purchase_order.return_orders.exclude(status="CANCELLED")
        if exclude_return_order_id is not None:
            existing_returns = existing_returns.exclude(id=exclude_return_order_id)

        occupied_quantities = {}
        for return_item in PurchaseReturnOrderItem.objects.filter(return_order__in=existing_returns):
            occupied_quantities[return_item.product_id] = occupied_quantities.get(return_item.product_id, Decimal("0")) + Decimal(str(return_item.quantity))

        for product_id, requested_quantity in requested_quantities.items():
            product = next(item["product"] for item in items_data if item["product"].id == product_id)
            available_quantity = received_quantities.get(product_id, Decimal("0")) - occupied_quantities.get(product_id, Decimal("0"))
            if requested_quantity > available_quantity:
                raise ValueError(
                    f"采购退货数量超出可退范围：{product.name}，"
                    f"已收货{received_quantities.get(product_id, Decimal('0')):.3f}，"
                    f"其他退货已占用{occupied_quantities.get(product_id, Decimal('0')):.3f}，"
                    f"本次申请{requested_quantity:.3f}"
                )

    @staticmethod
    def build_purchase_order_item_allocations(return_order):
        purchase_order = return_order.purchase_order
        if purchase_order is None:
            return {}

        source_lines_by_product = {}
        for source_line in purchase_order.items.select_for_update().order_by("id"):
            remaining_quantity = Decimal(str(source_line.received_quantity)) - Decimal(str(source_line.returned_quantity))
            source_lines_by_product.setdefault(source_line.product_id, []).append({
                "order_item": source_line,
                "remaining_quantity": remaining_quantity,
            })

        allocations_by_item = {}
        for item in return_order.items.all().order_by("id"):
            source_lines = source_lines_by_product.get(item.product_id, [])
            allocations = _allocate_quantity_to_source_lines(
                source_lines,
                "remaining_quantity",
                item.quantity,
            )
            allocations_by_item[item.id] = [
                (allocation["order_item"], allocated_quantity)
                for allocation, allocated_quantity in allocations
            ]
            for allocation, allocated_quantity in allocations:
                allocation["remaining_quantity"] -= allocated_quantity

        return allocations_by_item

    @staticmethod
    @transaction.atomic
    def create_order(supplier, purchase_order, warehouse, items_data, user, reason=None, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.purchase_return_enabled():
            raise ValueError("当前配置未启用采购退货")
        PurchaseReturnService._require_purchase_order(purchase_order)
        supplier = PurchaseReturnService._resolve_supplier(supplier, purchase_order)
        PurchaseReturnService.validate_supplier(supplier)
        PurchaseReturnService.validate_products(items_data)
        PurchaseReturnService._validate_return_quantities(purchase_order, items_data)
        order = PurchaseReturnOrder.objects.create(
            tenant=purchase_order.tenant,
            return_no=PurchaseReturnService.generate_no(),
            supplier=supplier,
            supplier_name_snapshot=supplier.supplier_name if supplier else None,
            purchase_order=purchase_order,
            warehouse=warehouse,
            status='DRAFT',
            reason=reason,
            remark=remark,
            **build_erp_user_and_dept_kwargs(PurchaseReturnOrder, user=user),
        )
        for item in items_data:
            product = item['product']
            PurchaseReturnOrderItem.objects.create(
                tenant=order.tenant,
                return_order=order,
                product=product,
                product_name_snapshot=product.name,
                product_code_snapshot=product.product_code,
                quantity=item['quantity'],
                remark=item.get('remark', ''),
            )
        return order

    @staticmethod
    @transaction.atomic
    def submit_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if order.status != 'DRAFT':
            raise ValueError("只有草稿状态的采购退货单可以提交审核")
        if order.items.count() == 0:
            raise ValueError("采购退货单明细不能为空")
        PurchaseReturnService._require_purchase_order(order.purchase_order)
        PurchaseReturnService.validate_supplier(order.supplier)
        PurchaseReturnService.validate_products(
            [{"product": item.product, "quantity": item.quantity} for item in order.items.select_related("product").all()]
        )
        PurchaseReturnService._validate_return_quantities(
            order.purchase_order,
            [{"product": item.product, "quantity": item.quantity} for item in order.items.select_related("product").all()],
            exclude_return_order_id=order.id,
        )
        erp_user_id = get_erp_user_id(user)
        if policy.return_approval_enabled():
            order.status = 'PENDING_APPROVAL'
        else:
            order.status = 'APPROVED'
            if erp_user_id is not None:
                order.approved_by_id = erp_user_id
            else:
                order.approved_by = None
            order.approved_at = timezone.now()
        if erp_user_id is not None:
            order.submitted_by_id = erp_user_id
        else:
            order.submitted_by = None
        order.submitted_at = timezone.now()
        update_fields = ['status', 'submitted_by', 'submitted_at', 'updated_at']
        if not policy.return_approval_enabled():
            update_fields.extend(['approved_by', 'approved_at'])
        order.save(update_fields=update_fields)
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if policy.return_approval_enabled():
            if order.status != 'PENDING_APPROVAL':
                raise ValueError("只有待审核状态的采购退货单可以审核")
        elif not order.can_transition_to('APPROVED'):
            raise ValueError("当前状态不允许审核")
        erp_user_id = get_erp_user_id(user)
        if order.created_by and erp_user_id is not None and order.created_by_id == erp_user_id:
            raise ValueError("审核人不能是单据创建人")
        if order.submitted_by and erp_user_id is not None and order.submitted_by_id == erp_user_id:
            raise ValueError("审核人不能是单据提交人")
        order.status = 'APPROVED'
        if erp_user_id is not None:
            order.approved_by_id = erp_user_id
        else:
            order.approved_by = None
        order.approved_at = timezone.now()
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def complete_order(order, user):
        """完成退货：库存减少，校验库存充足性"""
        order = PurchaseReturnOrder.objects.select_for_update().get(id=order.id)
        if not order.can_transition_to('COMPLETED'):
            raise ValueError("当前状态不允许完成退货")
        PurchaseReturnService._require_purchase_order(order.purchase_order)
        PurchaseReturnService._validate_return_quantities(
            order.purchase_order,
            [{"product": item.product, "quantity": item.quantity} for item in order.items.all()],
            exclude_return_order_id=order.id,
        )
        source_allocations = PurchaseReturnService.build_purchase_order_item_allocations(order)

        # 校验库存充足性
        for item in order.items.all():
            try:
                inv = Inventory.objects.get(warehouse=order.warehouse, product=item.product)
                if inv.current_qty < item.quantity:
                    raise ValueError(
                        f"库存不足无法退货出库：{item.product_name_snapshot}，"
                        f"当前库存{inv.current_qty}，退货数量{item.quantity}"
                    )
            except Inventory.DoesNotExist:
                raise ValueError(f"无库存记录：{item.product_name_snapshot}")

        for item in order.items.all():
            InventoryService.change_stock(
                warehouse=order.warehouse,
                product=item.product,
                quantity=-item.quantity,
                transaction_type='RETURN_OUT',
                operator=user,
                reference_type='PURCHASE_RETURN_ORDER',
                reference_id=order.id,
                remark=f"采购退货出库: {order.return_no}"
            )

        order.status = 'COMPLETED'
        order.completed_at = timezone.now()
        if order.supplier_id:
            from business_apps.ap_payable.services import APService
            APService.reverse_ap_for_purchase_return(order, user)
            from business_apps.accounting.services import PostingService
            PostingService.post_purchase_return(order, user)
            order.finance_status = 'ADJUSTED'
        for allocations in source_allocations.values():
            for purchase_order_item, allocated_quantity in allocations:
                purchase_order_item.returned_quantity += allocated_quantity
                purchase_order_item.save(update_fields=["returned_quantity"])
        order.save(update_fields=['status', 'completed_at', 'finance_status', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def cancel_order(order, user):
        if not order.can_transition_to('CANCELLED'):
            raise ValueError("当前状态不允许取消")
        order.status = 'CANCELLED'
        order.save()
        return order


class InventoryAlertService:
    @staticmethod
    def check_and_create_alerts(user=None):
        """扫描所有库存，生成预警记录"""
        if user is not None and not get_policy("supply_chain", user=user).inventory_alert_enabled():
            return 0
        alerts_created = 0
        inventories = Inventory.objects.select_related('warehouse', 'product').all()

        for inv in inventories:
            product = inv.product
            current_qty = inv.current_qty

            alert_type = None
            threshold = None
            if current_qty == 0:
                alert_type = 'OUT_OF_STOCK'
                threshold = product.min_stock
            elif current_qty < product.min_stock:
                alert_type = 'LOW_STOCK'
                threshold = product.min_stock
            elif current_qty > product.max_stock:
                alert_type = 'OVER_STOCK'
                threshold = product.max_stock

            if alert_type:
                exists = InventoryAlert.objects.filter(
                    warehouse=inv.warehouse,
                    product=product,
                    alert_type=alert_type,
                    is_resolved=False,
                ).exists()
                if not exists:
                    InventoryAlert.objects.create(
                        tenant=inv.tenant or inv.warehouse.tenant or product.tenant,
                        warehouse=inv.warehouse,
                        product=product,
                        alert_type=alert_type,
                        current_qty=current_qty,
                        threshold_value=threshold,
                    )
                    alerts_created += 1

        return alerts_created

    @staticmethod
    @transaction.atomic
    def resolve_alert(alert_id, user):
        alert = InventoryAlert.objects.get(id=alert_id)
        alert.is_resolved = True
        alert.resolved_by = user
        alert.resolved_at = timezone.now()
        alert.save()
        return alert


class InventoryTraceService:
    """库存追溯服务：查询某商品最近N天的所有库存变化"""

    @staticmethod
    def get_product_trace(product_id, days=30, warehouse_id=None, user=None):
        if user is not None and not get_policy("supply_chain", user=user).trace_enabled():
            raise ValueError("当前配置未启用库存追溯")
        from business_apps.inventory.models import InventoryTransaction
        from datetime import timedelta

        start_date = timezone.now() - timedelta(days=days)
        qs = InventoryTransaction.objects.filter(
            product_id=product_id,
            created_at__gte=start_date,
        ).select_related('warehouse', 'product', 'operator')
        if user is not None:
            qs = apply_erp_tenant_scope(qs, user=user)

        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        return qs.order_by('-created_at')
