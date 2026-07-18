from decimal import Decimal
from datetime import date, datetime
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Sum, Count, Q
from .models import (
    PurchaseOrder, PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem,
    PurchaseApprovalLog, PurchaseChangeLog, PurchaseAttachment
)
from business_apps.inventory.services import InventoryService
from business_apps.inventory.policies import InventoryPolicy
from business_apps.purchase.models import PurchaseOrder
from business_apps.purchase.policies import PurchasePolicy
from business_apps.platform.services import CodeRuleService
from core_apps.common.viewsets import apply_erp_tenant_scope
from core_apps.erp_auth.compat import (
    build_erp_user_and_dept_kwargs,
    build_erp_user_fk_kwargs,
    get_erp_user_id,
)
from core_apps.policies.registry import get_policy


class PurchaseOrderService:
    RECEIPT_EVENT_TYPE_EXECUTED = "PURCHASE_RECEIPT_EXECUTED"
    THREE_DECIMAL_PLACES = Decimal("0.000")

    @staticmethod
    def normalize_expected_arrival_date(value):
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
        raise ValueError("预计到货日期格式错误，请使用 YYYY-MM-DD")

    @staticmethod
    def generate_order_no():
        """生成采购单号：PO202606150001"""
        return CodeRuleService.generate('PURCHASE_ORDER')

    @staticmethod
    def generate_receipt_no():
        """生成入库单号：PR202606150001"""
        return CodeRuleService.generate('PURCHASE_RECEIPT')

    @staticmethod
    def validate_supplier(supplier):
        if supplier.status == 'BLACKLIST':
            raise ValueError("黑名单供应商禁止创建订单")
        if supplier.status != 'ACTIVE':
            raise ValueError("未激活供应商禁止创建订单")

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
        PurchaseOrderService.validate_supplier(order.supplier)
        PurchaseOrderService.validate_products(
            [{'product': item.product} for item in order.items.select_related('product').all()]
        )

    @staticmethod
    def get_open_receipt_quantity(order_item, *, exclude_receipt_id=None):
        queryset = PurchaseReceiptItem.objects.filter(
            purchase_order_item=order_item,
            receipt__status=PurchaseReceipt.STATUS_DRAFT,
        )
        if exclude_receipt_id is not None:
            queryset = queryset.exclude(receipt_id=exclude_receipt_id)
        return queryset.aggregate(total=Sum('received_quantity'))['total'] or Decimal('0')

    @staticmethod
    @transaction.atomic
    def create_order(supplier, items_data, user, remark=None, expected_arrival_date=None):
        PurchaseOrderService.validate_supplier(supplier)
        PurchaseOrderService.validate_products(items_data)

        inventory_policy = PurchaseOrderService.get_inventory_policy(user=user)
        expected_arrival_date = PurchaseOrderService.normalize_expected_arrival_date(expected_arrival_date)
        order_no = PurchaseOrderService.generate_order_no()
        order = PurchaseOrder.objects.create(
            tenant=supplier.tenant,
            purchase_order_no=order_no,
            supplier=supplier,
            supplier_name_snapshot=supplier.supplier_name,
            supplier_code_snapshot=supplier.supplier_code,
            status=PurchaseOrder.STATUS_DRAFT,
            remark=remark,
            expected_arrival_date=expected_arrival_date,
            **build_erp_user_and_dept_kwargs(PurchaseOrder, user=user),
        )

        total_qty = Decimal('0')
        total_amt = Decimal('0')
        for item in items_data:
            product = item['product']
            qty = Decimal(str(item['quantity']))
            price = Decimal(str(item['unit_price']))
            amt = qty * price

            PurchaseOrderItem.objects.create(
                tenant=order.tenant,
                purchase_order=order,
                product=product,
                product_name_snapshot=product.name,
                product_code_snapshot=product.product_code,
                unit_price_snapshot=product.cost_price,
                warehouse=inventory_policy.resolve_warehouse(item.get('warehouse')),
                quantity=qty,
                unit_price=price,
                amount=amt,
                remark=item.get('remark', '')
            )
            total_qty += qty
            total_amt += amt

        order.total_quantity = total_qty
        order.total_amount = total_amt
        order.save()
        return order

    @staticmethod
    @transaction.atomic
    def update_order(order, user, supplier=None, items_data=None, remark=None, expected_arrival_date=None):
        """仅允许修改草稿或已驳回状态的订单"""
        if order.status not in (PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_REJECTED):
            raise ValueError("只有草稿或已驳回状态的订单可以修改")
        if order.receipts.filter(status=PurchaseReceipt.STATUS_COMPLETED).exists():
            raise ValueError("已执行入库的采购订单不允许修改")

        inventory_policy = PurchaseOrderService.get_inventory_policy(user=user)
        expected_arrival_date = PurchaseOrderService.normalize_expected_arrival_date(expected_arrival_date)
        PurchaseOrderService.validate_supplier(supplier or order.supplier)
        PurchaseOrderService.validate_products(
            items_data if items_data is not None else [{'product': item.product} for item in order.items.select_related('product').all()]
        )

        # 记录变更日志
        if supplier and supplier.id != order.supplier_id:
            PurchaseChangeLog.objects.create(
                tenant=order.tenant,
                purchase_order=order,
                field_name='supplier',
                old_value=str(order.supplier_name_snapshot),
                new_value=str(supplier.supplier_name),
                **build_erp_user_fk_kwargs(PurchaseChangeLog, user=user, field_names=("changed_by",)),
            )
            order.supplier = supplier
            order.supplier_name_snapshot = supplier.supplier_name
            order.supplier_code_snapshot = supplier.supplier_code

        if remark is not None and remark != (order.remark or ''):
            PurchaseChangeLog.objects.create(
                tenant=order.tenant,
                purchase_order=order,
                field_name='remark',
                old_value=order.remark or '',
                new_value=remark,
                **build_erp_user_fk_kwargs(PurchaseChangeLog, user=user, field_names=("changed_by",)),
            )
            order.remark = remark

        if expected_arrival_date is not None:
            old_date = str(order.expected_arrival_date or '')
            new_date = str(expected_arrival_date or '')
            if old_date != new_date:
                PurchaseChangeLog.objects.create(
                    tenant=order.tenant,
                    purchase_order=order,
                    field_name='expected_arrival_date',
                    old_value=old_date,
                    new_value=new_date,
                    **build_erp_user_fk_kwargs(PurchaseChangeLog, user=user, field_names=("changed_by",)),
                )
            order.expected_arrival_date = expected_arrival_date

        order.save()

        # 更新明细 - 细化变更记录
        if items_data is not None:
            old_items = list(order.items.all().values_list(
                'product__name', 'quantity', 'unit_price', 'amount'
            ))
            old_summary = '; '.join(
                f"{name}: qty={qty}, price={price}, amt={amt}"
                for name, qty, price, amt in old_items
            )

            order.items.all().delete()

            total_qty = Decimal('0')
            total_amt = Decimal('0')
            for item in items_data:
                product = item['product']
                qty = Decimal(str(item['quantity']))
                price = Decimal(str(item['unit_price']))
                amt = qty * price

                PurchaseOrderItem.objects.create(
                    tenant=order.tenant,
                    purchase_order=order,
                    product=product,
                    product_name_snapshot=product.name,
                    product_code_snapshot=product.product_code,
                    unit_price_snapshot=product.cost_price,
                    warehouse=inventory_policy.resolve_warehouse(item.get('warehouse')),
                    quantity=qty,
                    unit_price=price,
                    amount=amt,
                    remark=item.get('remark', '')
                )
                total_qty += qty
                total_amt += amt

            order.total_quantity = total_qty
            order.total_amount = total_amt
            order.save()

            new_items = list(order.items.all().values_list(
                'product_name_snapshot', 'quantity', 'unit_price', 'amount'
            ))
            new_summary = '; '.join(
                f"{name}: qty={qty}, price={price}, amt={amt}"
                for name, qty, price, amt in new_items
            )

            PurchaseChangeLog.objects.create(
                tenant=order.tenant,
                purchase_order=order,
                field_name='items',
                old_value=old_summary or '(空)',
                new_value=new_summary or '(空)',
                **build_erp_user_fk_kwargs(PurchaseChangeLog, user=user, field_names=("changed_by",)),
            )

        # 修改后重置为草稿（如果之前是已驳回）
        if order.status == PurchaseOrder.STATUS_REJECTED:
            order.status = PurchaseOrder.STATUS_DRAFT
            order.save()

        return order

    @staticmethod
    @transaction.atomic
    def submit_order(order, user):
        policy = PurchaseOrderService.get_policy(user=user)
        next_status = policy.next_submit_status()
        if not order.can_transition_to(next_status):
            raise ValueError(f"当前状态 {order.get_status_display()} 不允许提交审核")
        if order.items.count() == 0:
            raise ValueError("订单明细不能为空")
        PurchaseOrderService.validate_order_references(order)
        order.status = next_status
        order.submitted_by = build_erp_user_fk_kwargs(PurchaseOrder, user=user, field_names=("submitted_by",)).get("submitted_by")
        order.submitted_at = timezone.now()
        order.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
        if next_status == PurchaseOrder.STATUS_APPROVED:
            PurchaseApprovalLog.objects.create(
                tenant=order.tenant,
                purchase_order=order,
                action='AUTO_APPROVE',
                comment='Auto approved by purchase policy',
                **build_erp_user_fk_kwargs(PurchaseApprovalLog, user=user, field_names=("approved_by",)),
            )
        return order

    @staticmethod
    @transaction.atomic
    def approve_order(order, user, comment=None):
        policy = PurchaseOrderService.get_policy(user=user)
        if not policy.approval_enabled():
            raise ValueError("当前租户已关闭采购审批，无需手动审批")
        if not order.can_transition_to(PurchaseOrder.STATUS_APPROVED):
            raise ValueError(f"当前状态 {order.get_status_display()} 不允许审批通过")

        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and order.submitted_by_id == erp_user_id:
            raise ValueError("审核人不能是提交人")

        order.status = PurchaseOrder.STATUS_APPROVED
        order.save()
        PurchaseApprovalLog.objects.create(
            tenant=order.tenant,
            purchase_order=order,
            action='APPROVE',
            comment=comment,
            **build_erp_user_fk_kwargs(PurchaseApprovalLog, user=user, field_names=("approved_by",)),
        )
        return order

    @staticmethod
    @transaction.atomic
    def reject_order(order, user, comment=None):
        policy = PurchaseOrderService.get_policy(user=user)
        if not policy.approval_enabled():
            raise ValueError("当前租户已关闭采购审批，不能执行驳回")
        if not order.can_transition_to(PurchaseOrder.STATUS_REJECTED):
            raise ValueError(f"当前状态 {order.get_status_display()} 不允许驳回")

        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and order.submitted_by_id == erp_user_id:
            raise ValueError("审核人不能是提交人")

        order.status = PurchaseOrder.STATUS_REJECTED
        order.save()
        PurchaseApprovalLog.objects.create(
            tenant=order.tenant,
            purchase_order=order,
            action='REJECT',
            comment=comment,
            **build_erp_user_fk_kwargs(PurchaseApprovalLog, user=user, field_names=("approved_by",)),
        )
        return order

    @staticmethod
    @transaction.atomic
    def create_receipt(order, warehouse, items_data, user, remark=None):
        policy = PurchaseOrderService.get_policy(user=user)
        inventory_policy = PurchaseOrderService.get_inventory_policy(user=user)
        if order.status not in [PurchaseOrder.STATUS_APPROVED, PurchaseOrder.STATUS_PARTIALLY_RECEIVED]:
            raise ValueError("订单未审核或已完成入库，无法创建入库单")

        # 检查订单是否已全部到货
        if order.status in [PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_CLOSED]:
            raise ValueError("订单已全部到货，无法创建入库单")

        locked_items = {
            item.id: item
            for item in order.items.select_for_update().all()
        }
        remaining_items = {}
        fully_reserved_by_drafts = False
        for item in locked_items.values():
            pending_receipt_qty = PurchaseOrderService.get_open_receipt_quantity(item)
            remaining_qty = item.quantity - item.received_quantity - pending_receipt_qty
            if remaining_qty > 0:
                remaining_items[item.id] = item
            elif item.received_quantity < item.quantity and pending_receipt_qty > 0:
                fully_reserved_by_drafts = True
        if not remaining_items:
            if fully_reserved_by_drafts:
                raise ValueError("采购订单待入库数量已被其他草稿入库单占用，请先完成或取消现有草稿入库单")
            raise ValueError("采购订单已无待入库明细")

        requested_quantities: dict[int, Decimal] = {}
        for item in items_data:
            po_item = locked_items.get(item['purchase_order_item'].id)
            if po_item is None:
                raise ValueError("入库明细必须来自当前采购订单")
            qty = Decimal(str(item['received_quantity']))
            if qty <= 0:
                raise ValueError("入库数量必须大于0")
            requested_quantities[po_item.id] = requested_quantities.get(po_item.id, Decimal('0')) + qty

        if not policy.partial_receipt_enabled():
            submitted_ids = set(requested_quantities.keys())
            remaining_ids = set(remaining_items.keys())
            if submitted_ids != remaining_ids:
                raise ValueError("当前配置不允许部分入库，必须一次性完成全部待入库明细")

        receipt_no = PurchaseOrderService.generate_receipt_no()
        receipt = PurchaseReceipt.objects.create(
            tenant=order.tenant,
            receipt_no=receipt_no,
            purchase_order=order,
            warehouse=inventory_policy.resolve_warehouse(warehouse),
            status=PurchaseReceipt.STATUS_DRAFT,
            remark=remark,
            **build_erp_user_fk_kwargs(PurchaseReceipt, user=user, field_names=("created_by",)),
        )

        for po_item_id, requested_qty in requested_quantities.items():
            po_item = locked_items[po_item_id]
            pending_receipt_qty = PurchaseOrderService.get_open_receipt_quantity(po_item)
            remaining = po_item.quantity - po_item.received_quantity - pending_receipt_qty
            if remaining < 0:
                raise ValueError(
                    f"草稿入库单占用数量异常：{po_item.product_name_snapshot} 已超出可入库数量，请先清理草稿入库单"
                )
            if requested_qty > remaining:
                raise ValueError(
                    f"入库数量超过剩余可入库数量：{po_item.product_name_snapshot}，"
                    f"采购{po_item.quantity.quantize(PurchaseOrderService.THREE_DECIMAL_PLACES)}，"
                    f"已完成入库{po_item.received_quantity.quantize(PurchaseOrderService.THREE_DECIMAL_PLACES)}，"
                    f"其他草稿入库单已占用{pending_receipt_qty.quantize(PurchaseOrderService.THREE_DECIMAL_PLACES)}，"
                    f"当前剩余可入库{remaining.quantize(PurchaseOrderService.THREE_DECIMAL_PLACES)}，"
                    f"本次申请{requested_qty.quantize(PurchaseOrderService.THREE_DECIMAL_PLACES)}"
                )
            if not policy.partial_receipt_enabled():
                if requested_qty != remaining:
                    raise ValueError(
                        f"当前配置不允许部分入库：{po_item.product_name_snapshot} 剩余待入库 {remaining}，"
                        f"本次必须全部入库"
                    )

        for item in items_data:
            po_item = locked_items[item['purchase_order_item'].id]
            qty = Decimal(str(item['received_quantity']))
            # 保存商品快照
            PurchaseReceiptItem.objects.create(
                tenant=receipt.tenant,
                receipt=receipt,
                purchase_order_item=po_item,
                product=po_item.product,
                product_name_snapshot=po_item.product_name_snapshot or po_item.product.name,
                product_code_snapshot=po_item.product_code_snapshot or po_item.product.product_code,
                received_quantity=qty,
                remark=item.get('remark', '')
            )

        return receipt

    @staticmethod
    def build_receipt_execution_event(receipt):
        total_amount = Decimal("0")
        lines = []
        for item in receipt.items.select_related("purchase_order_item", "product").all():
            unit_price = item.purchase_order_item.unit_price
            line_amount = item.received_quantity * unit_price
            total_amount += line_amount
            lines.append(
                {
                    "purchase_order_item_id": item.purchase_order_item_id,
                    "product_id": item.product_id,
                    "received_quantity": item.received_quantity,
                    "unit_price": unit_price,
                    "line_amount": line_amount,
                }
            )
        return {
            "event_type": PurchaseOrderService.RECEIPT_EVENT_TYPE_EXECUTED,
            "source_type": "PURCHASE_RECEIPT",
            "source_id": receipt.id,
            "receipt_no": receipt.receipt_no,
            "purchase_order_id": receipt.purchase_order_id,
            "purchase_order_no": receipt.purchase_order.purchase_order_no,
            "supplier_id": receipt.purchase_order.supplier_id,
            "warehouse_id": receipt.warehouse_id,
            "executed_at": receipt.received_at,
            "total_amount": total_amount,
            "lines": lines,
        }

    @staticmethod
    @transaction.atomic
    def execute_receipt(receipt, user):
        """执行入库：加锁执行，二次校验超量，并生成标准应付事件载荷。"""
        policy = PurchaseOrderService.get_policy(user=user)
        if receipt.status != PurchaseReceipt.STATUS_DRAFT:
            raise ValueError("只有草稿状态的入库单可以执行入库")

        # COMPLETED 后禁止修改，所以这里加锁
        receipt = PurchaseReceipt.objects.select_for_update().get(id=receipt.id)
        if receipt.status != PurchaseReceipt.STATUS_DRAFT:
            raise ValueError("入库单状态已变更，请刷新重试")

        order = PurchaseOrder.objects.select_for_update().get(id=receipt.purchase_order_id)

        for item in receipt.items.all():
            # 加锁读取采购订单明细，二次校验超量入库
            po_item = PurchaseOrderItem.objects.select_for_update().get(id=item.purchase_order_item_id)

            if (po_item.received_quantity + item.received_quantity) > po_item.quantity:
                raise ValueError(
                    f"入库数量超过采购数量：{po_item.product_name_snapshot}，"
                    f"采购{po_item.quantity}，已入库{po_item.received_quantity}，"
                    f"本次入库{item.received_quantity}"
                )

            # 1. 通过 InventoryService 增加库存（事务+行锁+流水）
            InventoryService.change_stock(
                warehouse=receipt.warehouse,
                product=item.product,
                quantity=item.received_quantity,
                transaction_type='PURCHASE_IN',
                operator=user,
                reference_type='PURCHASE_RECEIPT',
                reference_id=receipt.id,
                remark=f"采购入库: {receipt.receipt_no}"
            )

            # 2. 更新采购订单明细已收数量
            po_item.received_quantity += item.received_quantity
            po_item.save()

        receipt.status = PurchaseReceipt.STATUS_COMPLETED
        receipt.received_at = timezone.now()
        receipt.executed_by = build_erp_user_fk_kwargs(PurchaseReceipt, user=user, field_names=("executed_by",)).get("executed_by")
        receipt.save(update_fields=['status', 'received_at', 'executed_by'])

        receipt_event = PurchaseOrderService.build_receipt_execution_event(receipt)

        # Generate AP Account automatically
        from business_apps.ap_payable.services import APService
        ap_policy = get_policy("ap_payable", user=user)
        if policy.receipt_auto_ap_enabled() and ap_policy.auto_create_payable_enabled():
            APService.generate_ap_from_receipt(receipt, user, receipt_event=receipt_event)

        from business_apps.accounting.services import PostingService
        PostingService.post_purchase_receipt(receipt, user, receipt_event=receipt_event)

        # 3. 自动更新采购订单状态
        all_received = all(
            it.received_quantity >= it.quantity
            for it in order.items.all()
        )
        if all_received:
            order.status = PurchaseOrder.STATUS_RECEIVED
        else:
            order.status = PurchaseOrder.STATUS_PARTIALLY_RECEIVED
        order.save(update_fields=['status', 'updated_at'])

        return receipt

    @staticmethod
    @transaction.atomic
    def complete_receipt(receipt, user):
        return PurchaseOrderService.execute_receipt(receipt, user)

    @staticmethod
    @transaction.atomic
    def cancel_receipt(receipt, user):
        """取消入库单，仅允许取消未执行入库的草稿单据。"""
        PurchaseOrderService.get_policy(user=user)
        if receipt.status != PurchaseReceipt.STATUS_DRAFT:
            raise ValueError("仅允许取消未执行入库的草稿入库单")
        receipt.status = PurchaseReceipt.STATUS_CANCELLED
        receipt.cancelled_at = timezone.now()
        receipt.save(update_fields=['status', 'cancelled_at'])
        return receipt

    @staticmethod
    @transaction.atomic
    def cancel_order(order, user):
        if not order.can_transition_to(PurchaseOrder.STATUS_CANCELLED):
            raise ValueError(f"当前状态 {order.get_status_display()} 不允许取消")

        if order.receipts.filter(status=PurchaseReceipt.STATUS_COMPLETED).exists():
            raise ValueError("已有入库记录的订单禁止取消")

        # 同时取消所有草稿入库单
        order.receipts.filter(status=PurchaseReceipt.STATUS_DRAFT).update(
            status=PurchaseReceipt.STATUS_CANCELLED,
            cancelled_at=timezone.now(),
        )

        order.status = PurchaseOrder.STATUS_CANCELLED
        order.save(update_fields=['status', 'updated_at'])
        return order

    @staticmethod
    @transaction.atomic
    def close_order(order, user):
        if not order.can_transition_to(PurchaseOrder.STATUS_CLOSED):
            raise ValueError("只有全部收货的采购订单可以关闭")

        order.status = PurchaseOrder.STATUS_CLOSED
        order.closed_at = timezone.now()
        order.save(update_fields=['status', 'closed_at', 'updated_at'])
        return order

    @staticmethod
    def get_statistics(user=None, start_date=None, end_date=None):
        """采购统计，支持日期范围过滤"""
        order_date_q = Q()
        item_order_date_q = Q()
        if start_date:
            order_date_q &= Q(order_date__gte=start_date)
            item_order_date_q &= Q(purchase_order__order_date__gte=start_date)
        if end_date:
            order_date_q &= Q(order_date__lte=end_date)
            item_order_date_q &= Q(purchase_order__order_date__lte=end_date)

        orders = apply_erp_tenant_scope(PurchaseOrder.objects.all(), user=user).filter(order_date_q).exclude(status='CANCELLED')
        order_items = apply_erp_tenant_scope(PurchaseOrderItem.objects.all(), user=user).filter(
            item_order_date_q & ~Q(purchase_order__status='CANCELLED')
        )

        by_supplier = list(
            orders.values('supplier_name_snapshot').annotate(
                count=Count('id'),
                amount=Sum('total_amount')
            ).order_by('-amount')[:10]
        )

        by_product = list(
            order_items.values(
                'product_name_snapshot', 'product_code_snapshot'
            ).annotate(
                qty=Sum('quantity'),
                amount=Sum('amount')
            ).order_by('-amount')[:10]
        )

        # 汇总统计
        total_orders = orders.count()
        total_amount = orders.aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0')

        # 按状态统计
        by_status = dict(
            orders.values('status').annotate(
                count=Count('id')
            ).values_list('status', 'count')
        )

        # 按月统计
        from django.db.models.functions import TruncMonth
        by_month = list(
            orders
            .annotate(month=TruncMonth('order_date'))
            .values('month')
            .annotate(count=Count('id'), amount=Sum('total_amount'))
            .order_by('-month')[:12]
        )

        return {
            'by_supplier': by_supplier,
            'by_product': by_product,
            'total_orders': total_orders,
            'total_amount': total_amount,
            'by_status': by_status,
            'by_month': by_month,
        }

    @staticmethod
    @transaction.atomic
    def upload_attachment(order, file_name, file_url, user):
        return PurchaseAttachment.objects.create(
            tenant=order.tenant,
            purchase_order=order,
            file_name=file_name,
            file_url=file_url,
            **build_erp_user_fk_kwargs(PurchaseAttachment, user=user, field_names=("uploaded_by",)),
        )

    @staticmethod
    @transaction.atomic
    def delete_attachment(attachment_id, user):
        attachment = PurchaseAttachment.objects.get(id=attachment_id)
        attachment.delete()
        return True
    @staticmethod
    def get_policy(*, user=None, runtime_config=None):
        if runtime_config is not None:
            return PurchasePolicy(runtime_config)
        return get_policy("purchase", user=user)

    @staticmethod
    def get_inventory_policy(*, user=None, runtime_config=None):
        if runtime_config is not None:
            return InventoryPolicy(runtime_config)
        return get_policy("inventory", user=user)
