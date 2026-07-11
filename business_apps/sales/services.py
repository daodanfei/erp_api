from datetime import date, datetime
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField
from .models import (
    SalesOrder,
    SalesOrderItem,
    Shipment,
    ShipmentItem,
    OrderApprovalLog,
    OrderChangeLog,
    SalesExecutionLog,
)
from business_apps.inventory.models import Inventory
from business_apps.inventory.services import InventoryService
from business_apps.inventory.policies import InventoryPolicy
from business_apps.platform.services import CodeRuleService
from business_apps.sales.models import SalesOrder
from business_apps.sales.policies import SalesPolicy
from core_apps.erp_auth.compat import (
    build_erp_user_fk_kwargs,
    get_erp_user_id,
)
from core_apps.policies.registry import get_policy

class SalesOrderService:
    THREE_DECIMAL_PLACES = Decimal("0.000")
    OPEN_COMMITMENT_STATUSES = (
        SalesOrder.STATUS_DRAFT,
        SalesOrder.STATUS_PENDING_APPROVAL,
        SalesOrder.STATUS_APPROVED,
        SalesOrder.STATUS_ALLOCATED,
        SalesOrder.STATUS_PARTIALLY_SHIPPED,
    )

    STATE_MACHINE = {
        'submit': {'from': {SalesOrder.STATUS_DRAFT}, 'to': SalesOrder.STATUS_PENDING_APPROVAL},
        'approve': {'from': {SalesOrder.STATUS_PENDING_APPROVAL}, 'to': SalesOrder.STATUS_APPROVED},
        'reject': {'from': {SalesOrder.STATUS_PENDING_APPROVAL}, 'to': SalesOrder.STATUS_REJECTED},
        'allocate': {'from': {SalesOrder.STATUS_APPROVED}, 'to': SalesOrder.STATUS_ALLOCATED},
        'create_outbound': {'from': {SalesOrder.STATUS_ALLOCATED, SalesOrder.STATUS_PARTIALLY_SHIPPED}, 'to': None},
        'cancel': {
            'from': {
                SalesOrder.STATUS_DRAFT,
                SalesOrder.STATUS_PENDING_APPROVAL,
                SalesOrder.STATUS_APPROVED,
                SalesOrder.STATUS_ALLOCATED,
                SalesOrder.STATUS_PARTIALLY_SHIPPED,
                SalesOrder.STATUS_REJECTED,
            },
            'to': SalesOrder.STATUS_CANCELLED,
        },
        'close': {'from': {SalesOrder.STATUS_SHIPPED}, 'to': SalesOrder.STATUS_CLOSED},
    }

    @staticmethod
    def normalize_expected_delivery_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            parsed = parse_date(value[:10])
            if parsed:
                return parsed
        raise ValueError("预计交货日期格式错误，请使用 YYYY-MM-DD")

    @staticmethod
    def generate_order_no():
        return CodeRuleService.generate('SALES_ORDER')

    @staticmethod
    def _transition_error_message(action):
        messages = {
            'submit': "只有草稿订单可以提交审核",
            'approve': "只能审核待审核状态的订单",
            'reject': "只能审核待审核状态的订单",
            'allocate': "审核通过后才能锁定库存",
            'create_outbound': "库存锁定后才能生成销售出库申请",
            'cancel': "当前状态不允许取消销售订单",
            'close': "只有已完成全部发货的订单可以关闭",
        }
        return messages[action]

    @staticmethod
    def validate_customer(customer):
        if customer.status == 'BLACKLIST':
            raise ValueError("黑名单客户禁止创建订单")
        if customer.status != 'ACTIVE':
            raise ValueError("未激活客户禁止创建订单")

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
        SalesOrderService.validate_customer(order.customer)
        SalesOrderService.validate_products(
            [{'product': item.product} for item in order.items.select_related('product').all()]
        )

    @staticmethod
    def get_open_sales_commitment_quantity(*, warehouse, product, exclude_order_id=None):
        remaining_expr = ExpressionWrapper(
            F('quantity') - F('shipped_quantity'),
            output_field=DecimalField(max_digits=15, decimal_places=3),
        )
        queryset = SalesOrderItem.objects.filter(
            warehouse=warehouse,
            product=product,
            order__status__in=SalesOrderService.OPEN_COMMITMENT_STATUSES,
        )
        if exclude_order_id is not None:
            queryset = queryset.exclude(order_id=exclude_order_id)
        return queryset.aggregate(total=Sum(remaining_expr))['total'] or Decimal('0')

    @staticmethod
    def normalize_and_validate_sellable_items(*, items_data, user, exclude_order_id=None):
        inventory_policy = SalesOrderService.get_inventory_policy(user=user)
        SalesOrderService.validate_products(items_data)

        normalized_items = []
        requested_quantities: dict[tuple[int, int], Decimal] = {}
        warehouse_map = {}
        product_map = {}

        for item in items_data:
            product = item['product']
            warehouse = inventory_policy.resolve_warehouse(item.get('warehouse'))
            qty = Decimal(str(item['quantity']))
            price = Decimal(str(item['unit_price']))
            if qty <= 0:
                raise ValueError(f"销售数量必须大于0：{product.name}")
            normalized_items.append({
                **item,
                'warehouse': warehouse,
                'quantity': qty,
                'unit_price': price,
                'amount': qty * price,
            })
            key = (warehouse.id, product.id)
            requested_quantities[key] = requested_quantities.get(key, Decimal('0')) + qty
            warehouse_map[key] = warehouse
            product_map[key] = product

        for key, requested_qty in requested_quantities.items():
            warehouse = warehouse_map[key]
            product = product_map[key]
            inventory = Inventory.objects.filter(warehouse=warehouse, product=product).only('current_qty').first()
            current_qty = inventory.current_qty if inventory is not None else Decimal('0')
            committed_qty = SalesOrderService.get_open_sales_commitment_quantity(
                warehouse=warehouse,
                product=product,
                exclude_order_id=exclude_order_id,
            )
            sellable_qty = current_qty - committed_qty
            if requested_qty > sellable_qty:
                raise ValueError(
                    f"可销售数量不足：{product.name} 在 {warehouse.warehouse_name} 当前库存"
                    f"{current_qty.quantize(SalesOrderService.THREE_DECIMAL_PLACES)}，"
                    f"其他未完成销售单已占用"
                    f"{committed_qty.quantize(SalesOrderService.THREE_DECIMAL_PLACES)}，"
                    f"当前可销售{max(sellable_qty, Decimal('0')).quantize(SalesOrderService.THREE_DECIMAL_PLACES)}，"
                    f"本次申请{requested_qty.quantize(SalesOrderService.THREE_DECIMAL_PLACES)}"
                )

        return normalized_items

    @staticmethod
    def validate_sellable_quantities_for_order(order):
        items_data = [
            {
                'product': item.product,
                'warehouse': item.warehouse,
                'quantity': item.quantity,
                'unit_price': item.unit_price,
            }
            for item in order.items.select_related('product', 'warehouse').all()
        ]
        SalesOrderService.normalize_and_validate_sellable_items(
            items_data=items_data,
            user=order.created_by,
            exclude_order_id=order.id,
        )

    @staticmethod
    def validate_transition(order, action, next_status=None):
        allowed_from = SalesOrderService.STATE_MACHINE[action]['from']
        if order.status not in allowed_from:
            raise ValueError(SalesOrderService._transition_error_message(action))
        if action == 'submit' and next_status == SalesOrder.STATUS_APPROVED:
            return

    @staticmethod
    def log_execution(order, action, user, from_status=None, to_status=None, remark=None):
        SalesExecutionLog.objects.create(
            tenant=order.tenant,
            order=order,
            action=action,
            from_status=from_status,
            to_status=to_status,
            remark=remark,
            **build_erp_user_fk_kwargs(
                SalesExecutionLog,
                user=user,
                field_names=("operator",),
            ),
        )

    @staticmethod
    def check_credit_on_submit(order, allow_exception=False):
        from business_apps.crm.services import CustomerCreditService

        allowed, msg = CustomerCreditService.check_limit(
            order.customer,
            order.total_amount,
            allow_exception=allow_exception,
        )
        if not allowed:
            raise ValueError(msg)

    @staticmethod
    def get_open_outbound_quantity(order_item):
        return sum(
            (
                outbound_item.quantity
                for outbound_item in order_item.outbound_items
                .select_related('outbound_order')
                .exclude(outbound_order__status='CANCELLED')
                .exclude(outbound_order__status='COMPLETED')
            ),
            Decimal('0'),
        )

    @staticmethod
    def has_open_outbound_requests(order):
        return order.outbound_orders.exclude(status__in=['COMPLETED', 'CANCELLED']).exists()

    @staticmethod
    def release_allocated_stock(order):
        for item in order.items.all():
            if item.allocated_quantity > 0:
                InventoryService.release_stock(item.warehouse, item.product, item.allocated_quantity)
                item.allocated_quantity = Decimal('0')
                item.save(update_fields=['allocated_quantity'])

    @staticmethod
    @transaction.atomic
    def create_order(customer, items_data, user, remark=None, expected_delivery_date=None):
        SalesOrderService.validate_customer(customer)
        normalized_items = SalesOrderService.normalize_and_validate_sellable_items(
            items_data=items_data,
            user=user,
        )
        expected_delivery_date = SalesOrderService.normalize_expected_delivery_date(expected_delivery_date)
        order_no = SalesOrderService.generate_order_no()
        order = SalesOrder.objects.create(
            tenant=customer.tenant,
            order_no=order_no,
            customer=customer,
            customer_name_snapshot=customer.customer_name,
            customer_phone_snapshot=customer.phone,
            status='DRAFT',
            remark=remark,
            expected_delivery_date=expected_delivery_date,
            **build_erp_user_fk_kwargs(
                SalesOrder,
                user=user,
                field_names=("created_by",),
            ),
        )

        total_qty = 0
        total_amt = Decimal('0')
        for item in normalized_items:
            product = item['product']
            qty = item['quantity']
            price = item['unit_price']
            amt = item['amount']
            
            SalesOrderItem.objects.create(
                tenant=order.tenant,
                order=order,
                product=product,
                product_name_snapshot=product.name,
                warehouse=item['warehouse'],
                quantity=qty,
                unit_price=price,
                amount=amt
            )
            total_qty += qty
            total_amt += amt

        order.total_quantity = total_qty
        order.total_amount = total_amt
        order.save()
        return order

    @staticmethod
    @transaction.atomic
    def update_order(order, user, customer=None, items_data=None, remark=None, expected_delivery_date=None):
        if order.status not in ['DRAFT', 'REJECTED']:
            raise ValueError("只有草稿或已驳回状态的订单可以修改")

        expected_delivery_date = SalesOrderService.normalize_expected_delivery_date(expected_delivery_date)
        SalesOrderService.validate_customer(customer or order.customer)
        normalized_items = None
        if items_data is not None:
            normalized_items = SalesOrderService.normalize_and_validate_sellable_items(
                items_data=items_data,
                user=user,
                exclude_order_id=order.id,
            )
        else:
            SalesOrderService.validate_sellable_quantities_for_order(order)

        if customer and customer.id != order.customer_id:
            OrderChangeLog.objects.create(
                tenant=order.tenant,
                order=order,
                field_name='customer',
                old_value=order.customer_name_snapshot or order.customer.customer_name,
                new_value=customer.customer_name,
                **build_erp_user_fk_kwargs(
                    OrderChangeLog,
                    user=user,
                    field_names=("operator",),
                ),
            )
            order.customer = customer
            order.customer_name_snapshot = customer.customer_name
            order.customer_phone_snapshot = customer.phone

        if remark is not None and remark != (order.remark or ''):
            OrderChangeLog.objects.create(
                tenant=order.tenant,
                order=order,
                field_name='remark',
                old_value=order.remark or '',
                new_value=remark,
                **build_erp_user_fk_kwargs(
                    OrderChangeLog,
                    user=user,
                    field_names=("operator",),
                ),
            )
            order.remark = remark

        if expected_delivery_date is not None:
            old_date = str(order.expected_delivery_date or '')
            new_date = str(expected_delivery_date or '')
            if old_date != new_date:
                OrderChangeLog.objects.create(
                    tenant=order.tenant,
                    order=order,
                    field_name='expected_delivery_date',
                    old_value=old_date,
                    new_value=new_date,
                    **build_erp_user_fk_kwargs(
                        OrderChangeLog,
                        user=user,
                        field_names=("operator",),
                    ),
                )
            order.expected_delivery_date = expected_delivery_date

        order.save()

        if items_data is not None:
            if len(items_data) == 0:
                raise ValueError("订单明细不能为空")

            old_items = list(order.items.all().values_list('product_name_snapshot', 'quantity', 'unit_price', 'amount'))
            old_summary = '; '.join(
                f"{name}: qty={qty}, price={price}, amt={amt}"
                for name, qty, price, amt in old_items
            )

            order.items.all().delete()

            total_qty = Decimal('0')
            total_amt = Decimal('0')
            for item in normalized_items:
                product = item['product']
                qty = item['quantity']
                price = item['unit_price']
                amt = item['amount']

                SalesOrderItem.objects.create(
                    tenant=order.tenant,
                    order=order,
                    product=product,
                    product_name_snapshot=product.name,
                    warehouse=item['warehouse'],
                    quantity=qty,
                    unit_price=price,
                    amount=amt
                )
                total_qty += qty
                total_amt += amt

            order.total_quantity = total_qty
            order.total_amount = total_amt
            order.save()

            new_items = list(order.items.all().values_list('product_name_snapshot', 'quantity', 'unit_price', 'amount'))
            new_summary = '; '.join(
                f"{name}: qty={qty}, price={price}, amt={amt}"
                for name, qty, price, amt in new_items
            )

            OrderChangeLog.objects.create(
                tenant=order.tenant,
                order=order,
                field_name='items',
                old_value=old_summary or '(空)',
                new_value=new_summary or '(空)',
                **build_erp_user_fk_kwargs(
                    OrderChangeLog,
                    user=user,
                    field_names=("operator",),
                ),
            )

        if order.status == 'REJECTED':
            order.status = 'DRAFT'
            order.save()

        return order

    @staticmethod
    def submit_order(order, user):
        policy = SalesOrderService.get_policy(user=user)
        next_status = policy.next_submit_status()
        SalesOrderService.validate_transition(order, 'submit', next_status=next_status)
        SalesOrderService.validate_order_references(order)
        SalesOrderService.validate_sellable_quantities_for_order(order)
        if policy.credit_control_enabled():
            SalesOrderService.check_credit_on_submit(order)

        from_status = order.status
        order.status = next_status
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None:
            order.submitted_by_id = erp_user_id
        else:
            order.submitted_by = None
        order.submitted_at = timezone.now()
        order.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])
        if next_status == SalesOrder.STATUS_APPROVED:
            OrderApprovalLog.objects.create(
                tenant=order.tenant,
                order=order,
                action='AUTO_APPROVE',
                comment='Auto approved by sales policy',
                **build_erp_user_fk_kwargs(
                    OrderApprovalLog,
                    user=user,
                    field_names=("approved_by",),
                ),
            )
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_SUBMIT,
            user,
            from_status=from_status,
            to_status=order.status,
        )
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order, user, comment=None):
        policy = SalesOrderService.get_policy(user=user)
        if not policy.approval_enabled():
            raise ValueError("当前租户已关闭销售审批，无需手动审批")
        SalesOrderService.validate_transition(order, 'approve')
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and order.submitted_by_id == erp_user_id:
            raise ValueError("审核人不能是提交人")
        
        from_status = order.status
        order.status = SalesOrder.STATUS_APPROVED
        order.save(update_fields=['status', 'updated_at'])
        OrderApprovalLog.objects.create(
            tenant=order.tenant,
            order=order,
            action='APPROVE',
            comment=comment,
            **build_erp_user_fk_kwargs(
                OrderApprovalLog,
                user=user,
                field_names=("approved_by",),
            ),
        )
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_APPROVE,
            user,
            from_status=from_status,
            to_status=order.status,
            remark=comment,
        )
        return order

    @staticmethod
    @transaction.atomic
    def reject_order(order, user, comment=None):
        policy = SalesOrderService.get_policy(user=user)
        if not policy.approval_enabled():
            raise ValueError("当前租户已关闭销售审批，不能执行驳回")
        SalesOrderService.validate_transition(order, 'reject')
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and order.submitted_by_id == erp_user_id:
            raise ValueError("审核人不能是提交人")
        
        from_status = order.status
        order.status = SalesOrder.STATUS_REJECTED
        order.save(update_fields=['status', 'updated_at'])
        OrderApprovalLog.objects.create(
            tenant=order.tenant,
            order=order,
            action='REJECT',
            comment=comment,
            **build_erp_user_fk_kwargs(
                OrderApprovalLog,
                user=user,
                field_names=("approved_by",),
            ),
        )
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_REJECT,
            user,
            from_status=from_status,
            to_status=order.status,
            remark=comment,
        )
        return order

    @staticmethod
    @transaction.atomic
    def allocate_stock(order, user):
        """Locks inventory for all items in the order"""
        policy = SalesOrderService.get_policy(user=user)
        SalesOrderService.validate_transition(order, 'allocate')
        if policy.credit_control_enabled() and order.status != SalesOrder.STATUS_APPROVED:
            raise ValueError("当前状态不允许锁定库存")
        
        from_status = order.status
        inventory_policy = SalesOrderService.get_inventory_policy(user=user)
        for item in order.items.all():
            item.warehouse = inventory_policy.resolve_warehouse(item.warehouse)
            item.save(update_fields=['warehouse'])
            
            InventoryService.reserve_stock(item.warehouse, item.product, item.quantity, operator=user)
            item.allocated_quantity = item.quantity
            item.save(update_fields=['allocated_quantity'])
            
        order.status = SalesOrder.STATUS_ALLOCATED
        order.save(update_fields=['status', 'updated_at'])
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_ALLOCATE,
            user,
            from_status=from_status,
            to_status=order.status,
        )
        return order

    @staticmethod
    @transaction.atomic
    def create_outbound_request(order, shipment_items_data, user):
        """Standard ERP flow: create outbound requests instead of direct shipment."""
        from business_apps.supply_chain.services import OutboundService

        SalesOrderService.validate_transition(order, 'create_outbound')

        for item in shipment_items_data:
            order_item = item['order_item']
            requested_qty = Decimal(str(item['quantity']))
            open_outbound_qty = SalesOrderService.get_open_outbound_quantity(order_item)
            pending_qty = Decimal(str(order_item.quantity)) - Decimal(str(order_item.shipped_quantity)) - open_outbound_qty
            if requested_qty > pending_qty:
                raise ValueError(f"出库申请数量不能大于剩余可申请数量：{order_item.product.name}")

        outbound_orders = OutboundService.create_from_sales_order(order, shipment_items_data, user)
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_CREATE_OUTBOUND,
            user,
            from_status=order.status,
            to_status=order.status,
            remark=f"生成{len(outbound_orders)}张出库申请",
        )
        return outbound_orders

    @staticmethod
    def ship_order(order, shipment_items_data, user):
        return SalesOrderService.create_outbound_request(order, shipment_items_data, user)

    @staticmethod
    @transaction.atomic
    def cancel_order(order, user):
        """Cancels order and releases remaining locked stock when allowed."""
        SalesOrderService.validate_transition(order, 'cancel')
        if order.status == SalesOrder.STATUS_PARTIALLY_SHIPPED:
            if SalesOrderService.has_open_outbound_requests(order):
                raise ValueError("存在未完成的出库申请，不能取消部分已执行的销售订单")
            remaining_qty = sum(
                (Decimal(str(item.quantity)) - Decimal(str(item.shipped_quantity)) for item in order.items.all()),
                Decimal('0'),
            )
            if remaining_qty <= 0:
                raise ValueError("订单已全部发货，不能取消")

        if order.status == SalesOrder.STATUS_ALLOCATED:
            if SalesOrderService.has_open_outbound_requests(order):
                raise ValueError("存在未完成的出库申请，不能取消已锁库订单")

        from_status = order.status
        if order.status in [SalesOrder.STATUS_ALLOCATED, SalesOrder.STATUS_PARTIALLY_SHIPPED]:
            SalesOrderService.release_allocated_stock(order)

        order.status = SalesOrder.STATUS_CANCELLED
        order.closed_at = timezone.now()
        order.save(update_fields=['status', 'closed_at', 'updated_at'])
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_CANCEL,
            user,
            from_status=from_status,
            to_status=order.status,
        )
        return order

    @staticmethod
    @transaction.atomic
    def close_order(order, user):
        SalesOrderService.validate_transition(order, 'close')
        from_status = order.status
        order.status = SalesOrder.STATUS_CLOSED
        order.closed_at = timezone.now()
        order.save(update_fields=['status', 'closed_at', 'updated_at'])
        SalesOrderService.log_execution(
            order,
            SalesExecutionLog.ACTION_CLOSE,
            user,
            from_status=from_status,
            to_status=order.status,
        )
        return order

    @staticmethod
    def get_statistics():
        today = timezone.now().date()
        month_start = today.replace(day=1)
        
        stats = {
            'today': SalesOrder.objects.filter(order_date=today).aggregate(
                count=Count('id'), amount=Sum('total_amount')
            ),
            'month': SalesOrder.objects.filter(order_date__gte=month_start).aggregate(
                count=Count('id'), amount=Sum('total_amount')
            ),
            'by_customer': SalesOrder.objects.values('customer__customer_name').annotate(
                count=Count('id'), amount=Sum('total_amount')
            ).order_by('-amount')[:10]
        }
        return stats
    @staticmethod
    def get_policy(*, user=None, runtime_config=None):
        if runtime_config is not None:
            return SalesPolicy(runtime_config)
        return get_policy("sales", user=user)

    @staticmethod
    def get_inventory_policy(*, user=None, runtime_config=None):
        if runtime_config is not None:
            return InventoryPolicy(runtime_config)
        return get_policy("inventory", user=user)
