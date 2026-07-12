from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, F
from .models import CustomerRefund, Receivable, Receipt, WriteOff
from business_apps.sales.models import SalesOrder
from business_apps.crm.services import CustomerCreditService
from core_apps.erp_auth.compat import (
    build_erp_user_and_dept_kwargs,
    build_erp_user_fk_kwargs,
    get_erp_user_id,
)
from core_apps.common.viewsets import apply_erp_tenant_scope
from core_apps.policies.registry import get_policy

class ARService:
    @staticmethod
    def _normalize_amount(amount):
        return Decimal(str(amount))

    @staticmethod
    def _sync_customer_current_balance(customer, delta=None):
        customer = customer.__class__.objects.select_for_update().get(id=customer.id)
        if delta is None:
            balance = (
                Receivable.objects.filter(customer=customer, is_deleted=False)
                .exclude(status='CANCELLED')
                .aggregate(total=Sum(F('amount') - F('written_off_amount')))['total']
                or Decimal('0')
            )
            customer.current_balance = balance
        else:
            customer.current_balance += ARService._normalize_amount(delta)
        customer.save(update_fields=['current_balance'])
        return customer

    @staticmethod
    def _update_receivable_status(receivable):
        if receivable.amount >= 0:
            if receivable.written_off_amount >= receivable.amount:
                receivable.status = 'PAID'
            elif receivable.written_off_amount > 0:
                receivable.status = 'PARTIAL_PAID'
            else:
                receivable.status = 'UNPAID'
        else:
            refund_total = abs(receivable.amount)
            if receivable.written_off_amount >= refund_total:
                receivable.status = 'REFUNDED'
            elif receivable.written_off_amount > 0:
                receivable.status = 'PARTIAL_REFUNDED'
            else:
                receivable.status = 'REFUND_PENDING'

    @staticmethod
    def generate_no(prefix):
        now = timezone.now()
        date_str = now.strftime('%Y%m%d')
        full_prefix = f"{prefix}{date_str}"
        model_map = {
            'AR': (Receivable, 'receivable_no'),
            'RC': (Receipt, 'receipt_no'),
            'RF': (CustomerRefund, 'refund_no'),
            'WO': (WriteOff, 'write_off_no'),
        }
        model, field = model_map[prefix]
        
        last_record = model.objects.filter(**{f"{field}__startswith": full_prefix}).order_by(f"-{field}").first()
        if last_record:
            last_num = int(getattr(last_record, field)[-4:])
            new_num = str(last_num + 1).zfill(4)
        else:
            new_num = "0001"
        return f"{full_prefix}{new_num}"

    @staticmethod
    @transaction.atomic
    def generate_ar_from_order(order, operator):
        """Auto generate AR from shipped/closed SalesOrder"""
        policy = get_policy("ar_receivable", user=operator)
        if not policy.auto_create_receivable_enabled():
            raise ValueError("当前配置未启用自动生成应收")
        if order.status not in ['SHIPPED', 'CLOSED']:
            raise ValueError("只有已发货或已关闭的订单才能生成应收账款")
            
        if hasattr(order, 'receivables') and order.receivables.filter(is_deleted=False).exists():
            raise ValueError("该订单已生成过应收账款")

        ar_no = ARService.generate_no('AR')
        receivable = Receivable.objects.create(
            tenant=order.tenant,
            receivable_no=ar_no,
            customer=order.customer,
            sales_order=order,
            source_type='SALES_ORDER',
            amount=order.total_amount,
            written_off_amount=0,
            due_date=CustomerCreditService.calculate_due_date(order.customer, base_date=order.order_date),
            status='UNPAID',
            **build_erp_user_and_dept_kwargs(Receivable, user=operator),
        )
        
        ARService._sync_customer_current_balance(order.customer, delta=order.total_amount)
        
        return receivable

    @staticmethod
    @transaction.atomic
    def generate_ar_from_outbound(outbound_order, operator):
        """Auto generate AR from a completed outbound order."""
        policy = get_policy("ar_receivable", user=operator)
        if not policy.auto_create_receivable_enabled():
            raise ValueError("当前配置未启用自动生成应收")
        if outbound_order.status != 'COMPLETED':
            raise ValueError("只有已完成的销售出库单才能生成应收账款")
        if not outbound_order.sales_order_id:
            raise ValueError("销售出库单未关联销售订单，无法生成应收账款")

        if outbound_order.receivables.filter(is_deleted=False).exists():
            raise ValueError("该销售出库单已生成过应收账款")

        amount = sum((item.amount for item in outbound_order.items.all()), Decimal('0'))
        if amount <= 0:
            raise ValueError("销售出库单金额必须大于0")

        order = outbound_order.sales_order
        base_date = (
            outbound_order.completed_at.date()
            if outbound_order.completed_at else timezone.now().date()
        )
        due_date = CustomerCreditService.calculate_due_date(order.customer, base_date=base_date)

        receivable = Receivable.objects.create(
            tenant=order.tenant,
            receivable_no=ARService.generate_no('AR'),
            customer=order.customer,
            sales_order=order,
            outbound_order=outbound_order,
            source_type='OUTBOUND_ORDER',
            amount=amount,
            written_off_amount=0,
            due_date=due_date,
            status='UNPAID',
            remark=f"销售出库生成应收: {outbound_order.outbound_no}",
            **build_erp_user_and_dept_kwargs(Receivable, user=operator),
        )

        ARService._sync_customer_current_balance(order.customer, delta=amount)

        return receivable

    @staticmethod
    @transaction.atomic
    def reverse_ar_for_sales_return(return_order, operator):
        if not return_order.sales_order_id or not return_order.customer_id:
            raise ValueError("销售退货单未关联销售订单或客户，无法执行应收反向调整")

        from business_apps.supply_chain.services import SalesReturnService

        amount = Decimal('0')
        allocations_by_item = SalesReturnService.build_sales_order_item_allocations(
            return_order,
            exclude_return_order_id=return_order.id,
        )
        for item in return_order.items.all():
            allocations = allocations_by_item.get(item.id, [])
            if allocations:
                for sales_item, allocated_quantity in allocations:
                    amount += Decimal(str(allocated_quantity)) * Decimal(str(sales_item.unit_price))
            else:
                amount += Decimal(str(item.quantity)) * Decimal(str(item.product.sale_price or Decimal('0')))

        if amount <= 0:
            raise ValueError("销售退货单金额必须大于0")

        remaining = amount
        receivables = (
            Receivable.objects.select_for_update()
            .filter(sales_order=return_order.sales_order, customer=return_order.customer, is_deleted=False)
            .exclude(status='CANCELLED')
            .order_by('created_at', 'id')
        )
        for receivable in receivables:
            adjustable = receivable.amount - receivable.written_off_amount
            if adjustable <= 0 or remaining <= 0:
                continue

            delta = min(adjustable, remaining)
            receivable.amount -= delta
            ARService._update_receivable_status(receivable)
            receivable.remark = (receivable.remark or '').strip()
            suffix = f"销售退货反向调整 {return_order.return_no}: -{delta}"
            receivable.remark = f"{receivable.remark}; {suffix}" if receivable.remark else suffix
            receivable.save(update_fields=['amount', 'status', 'remark', 'updated_at'])
            WriteOff.objects.create(
                tenant=receivable.tenant,
                write_off_no=ARService.generate_no('WO'),
                receivable=receivable,
                receipt=None,
                amount=delta,
                write_off_type='RETURN_OFFSET',
                **build_erp_user_fk_kwargs(WriteOff, user=operator, field_names=("operator",)),
            )
            remaining -= delta

        if remaining > 0:
            refund_receivable = Receivable.objects.create(
                tenant=return_order.tenant,
                receivable_no=ARService.generate_no('AR'),
                customer=return_order.customer,
                sales_order=return_order.sales_order,
                source_type='SALES_RETURN',
                amount=-remaining,
                written_off_amount=Decimal('0'),
                due_date=timezone.now().date(),
                status='REFUND_PENDING',
                remark=f"销售退货红字应收: {return_order.return_no}",
                **build_erp_user_and_dept_kwargs(Receivable, user=operator),
            )
            ARService.create_customer_refund(
                customer=return_order.customer,
                receivable=refund_receivable,
                refund_date=timezone.now().date(),
                operator=operator,
                remark=f"销售退货自动生成退款单: {return_order.return_no}",
            )

        ARService._sync_customer_current_balance(return_order.customer, delta=-amount)
        return amount

    @staticmethod
    @transaction.atomic
    def create_customer_refund(customer, receivable, refund_date, operator, payment_method='BANK_TRANSFER', cash_account=None, reference_no=None, remark=None):
        if receivable.customer_id != customer.id:
            raise ValueError("退款单与红字应收客户不一致")
        if receivable.amount >= 0 or receivable.source_type != 'SALES_RETURN':
            raise ValueError("只能基于销售退货红字应收生成退款单")
        if receivable.balance <= 0:
            raise ValueError("该红字应收已无待退款金额")
        refund = CustomerRefund.objects.create(
            tenant=customer.tenant,
            refund_no=ARService.generate_no('RF'),
            customer=customer,
            receivable=receivable,
            refund_amount=receivable.balance,
            refund_date=refund_date,
            payment_method=payment_method,
            cash_account=cash_account,
            reference_no=reference_no,
            status='DRAFT',
            remark=remark,
            **build_erp_user_and_dept_kwargs(CustomerRefund, user=operator),
        )
        return refund

    @staticmethod
    @transaction.atomic
    def approve_customer_refund(refund, operator):
        refund = CustomerRefund.objects.select_for_update().get(id=refund.id)
        if refund.status != 'DRAFT':
            raise ValueError("只有草稿状态的退款单可以审核")
        refund.status = 'APPROVED'
        refund.approved_by = build_erp_user_fk_kwargs(
            CustomerRefund,
            user=operator,
            field_names=("approved_by",),
        ).get("approved_by")
        refund.approved_at = timezone.now()
        refund.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        return refund

    @staticmethod
    @transaction.atomic
    def execute_customer_refund(refund, operator):
        refund = CustomerRefund.objects.select_for_update().get(id=refund.id)
        if refund.status != 'APPROVED':
            raise ValueError("只有已审核状态的退款单可以执行")
        if refund.executed_at:
            raise ValueError("退款单已执行")

        receivable = Receivable.objects.select_for_update().get(id=refund.receivable_id)
        if receivable.balance < refund.refund_amount:
            raise ValueError("退款金额超过红字应收待退款余额")

        if refund.cash_account:
            from business_apps.finance.models import CashAccount, CashAccountTransaction
            acc = CashAccount.objects.select_for_update().get(id=refund.cash_account_id)
            if acc.current_balance < refund.refund_amount:
                raise ValueError(f"账户余额不足！当前: {acc.current_balance}, 需要: {refund.refund_amount}")
            CashAccountTransaction.record_change(
                cash_account=acc,
                direction='OUTFLOW',
                amount=refund.refund_amount,
                source_type='AR_REFUND',
                source_id=refund.id,
                source_document_no_snapshot=refund.refund_no,
                transaction_date=refund.refund_date,
                operator=operator,
                remark=refund.remark,
            )

        receivable.written_off_amount += refund.refund_amount
        ARService._update_receivable_status(receivable)
        receivable.save(update_fields=['written_off_amount', 'status', 'updated_at'])
        ARService._sync_customer_current_balance(refund.customer, delta=refund.refund_amount)

        refund.status = 'COMPLETED'
        refund.executed_at = timezone.now()
        refund.save(update_fields=['status', 'executed_at', 'updated_at'])

        from business_apps.accounting.services import PostingService
        PostingService.post_customer_refund_execution(refund, operator)
        return refund

    @staticmethod
    @transaction.atomic
    def create_receipt(customer, amount, receipt_date, payment_method, operator, cash_account=None, reference_no=None, remark=None):
        """Create a draft receipt. Cash is posted only after approval."""
        if amount <= 0:
            raise ValueError("收款金额必须大于0")
        if customer.status == 'BLACKLIST':
            raise ValueError("黑名单客户禁止创建收款单")
        if customer.status != 'ACTIVE':
            raise ValueError("未激活客户禁止创建收款单")
        policy = get_policy("ar_receivable", user=operator)
        receipt_no = ARService.generate_no('RC')
        receipt = Receipt.objects.create(
            tenant=customer.tenant,
            receipt_no=receipt_no,
            customer=customer,
            amount=amount,
            unwritten_amount=amount,
            receipt_date=receipt_date,
            payment_method=payment_method,
            cash_account=cash_account,
            reference_no=reference_no,
            status='DRAFT' if policy.receipt_approval_enabled() else 'UNWRITTEN',
            remark=remark,
            approved_by=(
                None if policy.receipt_approval_enabled()
                else build_erp_user_fk_kwargs(Receipt, user=operator, field_names=("approved_by",)).get("approved_by")
            ),
            approved_at=None if policy.receipt_approval_enabled() else timezone.now(),
            **build_erp_user_and_dept_kwargs(Receipt, user=operator),
        )
        return receipt

    @staticmethod
    @transaction.atomic
    def approve_receipt(receipt, operator):
        """Approve receipt only; cash posting is separated into execute."""
        policy = get_policy("ar_receivable", user=operator)
        if not policy.receipt_approval_enabled():
            raise ValueError("当前配置为免审批，收款单无需审核")
        receipt = Receipt.objects.select_for_update().get(id=receipt.id)
        if receipt.status != 'DRAFT':
            raise ValueError("只有草稿状态的收款单可以审核")
        erp_user_id = get_erp_user_id(operator)
        if erp_user_id is not None and receipt.created_by_id == erp_user_id:
            raise ValueError("审核人不能是收款单创建人")

        receipt.status = 'UNWRITTEN'
        receipt.approved_by = build_erp_user_fk_kwargs(
            Receipt,
            user=operator,
            field_names=("approved_by",),
        ).get("approved_by")
        receipt.approved_at = timezone.now()
        receipt.save(update_fields=['status', 'approved_by', 'approved_at'])
        return receipt

    @staticmethod
    @transaction.atomic
    def execute_receipt(receipt, operator):
        receipt = Receipt.objects.select_for_update().get(id=receipt.id)
        if receipt.status not in ['UNWRITTEN', 'PARTIAL_WRITTEN', 'WRITTEN']:
            raise ValueError("只有已审核的收款单可以执行")
        if receipt.executed_at:
            raise ValueError("收款单已执行")

        if receipt.cash_account:
            from business_apps.finance.models import CashAccount, CashAccountTransaction
            acc = CashAccount.objects.select_for_update().get(id=receipt.cash_account_id)
            CashAccountTransaction.record_change(
                cash_account=acc,
                direction='INFLOW',
                amount=receipt.amount,
                source_type='AR_RECEIPT',
                source_id=receipt.id,
                source_document_no_snapshot=receipt.receipt_no,
                transaction_date=receipt.receipt_date,
                operator=operator,
                remark=receipt.remark,
            )

        receipt.executed_at = timezone.now()
        receipt.save(update_fields=['executed_at'])

        from business_apps.accounting.services import PostingService
        PostingService.post_receipt_execution(receipt, operator)
        return receipt

    @staticmethod
    @transaction.atomic
    def write_off(receivable_id, receipt_id, amount, operator):
        """Perform write-off between a receivable and a receipt"""
        if amount <= 0:
            raise ValueError("核销金额必须大于0")
        policy = get_policy("ar_receivable", user=operator)
        if not policy.writeoff_enabled():
            raise ValueError("当前配置未启用应收核销")
        receivable = Receivable.objects.select_for_update().get(id=receivable_id)
        receipt = Receipt.objects.select_for_update().get(id=receipt_id)

        if receipt.status not in ['UNWRITTEN', 'PARTIAL_WRITTEN']:
            raise ValueError("只有已审核且未完全核销的收款单可以核销")
        
        if receivable.customer != receipt.customer:
            raise ValueError("收款单与应收单必须属于同一客户")
            
        if receivable.balance < Decimal(str(amount)):
            raise ValueError(f"核销金额不能大于应收单余额: {receivable.balance}")
            
        if receipt.unwritten_amount < Decimal(str(amount)):
            raise ValueError(f"核销金额不能大于收款单未核销金额: {receipt.unwritten_amount}")
        if not policy.allow_partial_receipt() and Decimal(str(amount)) != receivable.balance:
            raise ValueError("当前配置不允许部分收款，必须整笔核销应收")
            
        # Create write-off record
        write_off_no = ARService.generate_no('WO')
        WriteOff.objects.create(
            tenant=receivable.tenant,
            write_off_no=write_off_no,
            receivable=receivable,
            receipt=receipt,
            amount=amount,
            write_off_type='RECEIPT',
            **build_erp_user_fk_kwargs(WriteOff, user=operator, field_names=("operator",)),
        )
        
        # Update receivable
        receivable.written_off_amount += Decimal(str(amount))
        ARService._update_receivable_status(receivable)
        receivable.save()
        
        ARService._sync_customer_current_balance(receivable.customer, delta=-Decimal(str(amount)))
        
        # Update receipt
        receipt.unwritten_amount -= Decimal(str(amount))
        if receipt.unwritten_amount <= 0:
            receipt.status = 'WRITTEN'
        else:
            receipt.status = 'PARTIAL_WRITTEN'
        receipt.save()
        
        return receivable, receipt

    @staticmethod
    def get_aging_analysis(user=None, customer_id=None):
        """Generate aging analysis for receivables"""
        from django.utils import timezone
        today = timezone.now().date()
        
        qs = apply_erp_tenant_scope(Receivable.objects.all(), user=user).filter(is_deleted=False).exclude(status='PAID')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
            
        # Group by customer and calculate aging buckets
        # This is simplified. In real DB, we'd use conditional aggregation.
        analysis = []
        customers = qs.values('customer__customer_name', 'customer__id').distinct()
        for c in customers:
            c_qs = qs.filter(customer_id=c['customer__id'])
            
            not_due = c_qs.filter(due_date__gte=today).aggregate(Sum('amount'), Sum('written_off_amount'))
            not_due_bal = (not_due['amount__sum'] or 0) - (not_due['written_off_amount__sum'] or 0)
            
            overdue_1_30 = c_qs.filter(due_date__lt=today, due_date__gte=today - timezone.timedelta(days=30)).aggregate(Sum('amount'), Sum('written_off_amount'))
            o_1_30_bal = (overdue_1_30['amount__sum'] or 0) - (overdue_1_30['written_off_amount__sum'] or 0)
            
            overdue_31_60 = c_qs.filter(due_date__lt=today - timezone.timedelta(days=30), due_date__gte=today - timezone.timedelta(days=60)).aggregate(Sum('amount'), Sum('written_off_amount'))
            o_31_60_bal = (overdue_31_60['amount__sum'] or 0) - (overdue_31_60['written_off_amount__sum'] or 0)
            
            overdue_60_plus = c_qs.filter(due_date__lt=today - timezone.timedelta(days=60)).aggregate(Sum('amount'), Sum('written_off_amount'))
            o_60_plus_bal = (overdue_60_plus['amount__sum'] or 0) - (overdue_60_plus['written_off_amount__sum'] or 0)
            
            total = not_due_bal + o_1_30_bal + o_31_60_bal + o_60_plus_bal
            
            if total > 0:
                analysis.append({
                    'customer_id': c['customer__id'],
                    'customer_name': c['customer__customer_name'],
                    'total_balance': total,
                    'not_due': not_due_bal,
                    'overdue_1_30': o_1_30_bal,
                    'overdue_31_60': o_31_60_bal,
                    'overdue_60_plus': o_60_plus_bal,
                })
        return analysis
