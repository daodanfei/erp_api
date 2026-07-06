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
from core_apps.erp_auth.compat import (
    build_erp_user_and_dept_kwargs,
    get_erp_user_id,
)
from core_apps.policies.registry import get_policy


class OutboundService:
    @staticmethod
    def generate_no():
        return CodeRuleService.generate('OUTBOUND_ORDER')

    @staticmethod
    @transaction.atomic
    def create_order(sales_order, warehouse, items_data, user, remark=None):
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
            pending_qty = Decimal(str(order_item.quantity)) - Decimal(str(order_item.shipped_quantity))

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
    @transaction.atomic
    def create_order(from_warehouse, to_warehouse, items_data, user, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.transfer_enabled():
            raise ValueError("当前配置未启用调拨")
        if from_warehouse.id == to_warehouse.id:
            raise ValueError("禁止同仓库调拨")

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

        # 校验调出仓库库存充足性
        for item in order.items.all():
            try:
                inv = Inventory.objects.get(warehouse=order.from_warehouse, product=item.product)
                if inv.current_qty < item.quantity:
                    raise ValueError(
                        f"调出仓库库存不足：{item.product_name_snapshot}，"
                        f"当前库存{inv.current_qty}，调拨数量{item.quantity}"
                    )
            except Inventory.DoesNotExist:
                raise ValueError(f"调出仓库无库存：{item.product_name_snapshot}")

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
    @transaction.atomic
    def create_order(customer, sales_order, warehouse, items_data, user, reason=None, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.sales_return_enabled():
            raise ValueError("当前配置未启用销售退货")
        order = SalesReturnOrder.objects.create(
            tenant=(
                customer.tenant if customer else (
                    sales_order.tenant if sales_order else warehouse.tenant
                )
            ),
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
    def approve_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if not order.can_transition_to('APPROVED'):
            raise ValueError("当前状态不允许审核")
        if policy.return_approval_enabled() and order.created_by and order.created_by_id == user.id:
            raise ValueError("审核人不能是单据创建人")
        order.status = 'APPROVED'
        order.save()
        return order

    @staticmethod
    @transaction.atomic
    def complete_order(order, user):
        """完成退货：库存增加"""
        order = SalesReturnOrder.objects.select_for_update().get(id=order.id)
        if not order.can_transition_to('COMPLETED'):
            raise ValueError("当前状态不允许完成退货")

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
        if order.sales_order_id and order.customer_id:
            from business_apps.ar_receivable.services import ARService
            ARService.reverse_ar_for_sales_return(order, user)
            from business_apps.accounting.services import PostingService
            PostingService.post_sales_return(order, user)
            order.finance_status = 'ADJUSTED'
        else:
            order.finance_status = 'NOT_REQUIRED'
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
    @transaction.atomic
    def create_order(supplier, purchase_order, warehouse, items_data, user, reason=None, remark=None):
        policy = get_policy("supply_chain", user=user)
        if not policy.purchase_return_enabled():
            raise ValueError("当前配置未启用采购退货")
        order = PurchaseReturnOrder.objects.create(
            tenant=(
                supplier.tenant if supplier else (
                    purchase_order.tenant if purchase_order else warehouse.tenant
                )
            ),
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
    def approve_order(order, user):
        policy = get_policy("supply_chain", user=user)
        if not order.can_transition_to('APPROVED'):
            raise ValueError("当前状态不允许审核")
        if policy.return_approval_enabled() and order.created_by and order.created_by_id == user.id:
            raise ValueError("审核人不能是单据创建人")
        order.status = 'APPROVED'
        order.save()
        return order

    @staticmethod
    @transaction.atomic
    def complete_order(order, user):
        """完成退货：库存减少，校验库存充足性"""
        order = PurchaseReturnOrder.objects.select_for_update().get(id=order.id)
        if not order.can_transition_to('COMPLETED'):
            raise ValueError("当前状态不允许完成退货")

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
        if order.purchase_order_id and order.supplier_id:
            from business_apps.ap_payable.services import APService
            APService.reverse_ap_for_purchase_return(order, user)
            from business_apps.accounting.services import PostingService
            PostingService.post_purchase_return(order, user)
            order.finance_status = 'ADJUSTED'
        else:
            order.finance_status = 'NOT_REQUIRED'
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

        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        return qs.order_by('-created_at')
