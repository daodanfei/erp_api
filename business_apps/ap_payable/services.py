from decimal import Decimal
from django.db import transaction, models
from django.utils import timezone
from django.db.models import Sum, Count, F, Q
from .models import APAccount, APPayment, APAllocation, APOperationLog, SupplierCreditNote
from business_apps.platform.services import CodeRuleService
from business_apps.purchase.models import PurchaseReceipt
from business_apps.supplier.services import SupplierSettlementService
from core_apps.erp_auth.compat import (
    build_erp_user_and_dept_kwargs,
    build_erp_user_fk_kwargs,
    get_erp_user_id,
)
from core_apps.policies.registry import get_policy

class APService:
    @staticmethod
    def generate_ap_no():
        return CodeRuleService.generate('AP_ACCOUNT')

    @staticmethod
    def generate_payment_no():
        return CodeRuleService.generate('AP_PAYMENT')
        
    @staticmethod
    def generate_allocation_no():
        return CodeRuleService.generate('AP_ALLOCATION')

    @staticmethod
    def generate_credit_note_no():
        return CodeRuleService.generate('AP_ACCOUNT')

    @staticmethod
    def _update_ap_status(ap_account):
        if ap_account.paid_amount >= ap_account.total_amount:
            ap_account.status = 'PAID'
        elif ap_account.paid_amount > 0:
            ap_account.status = 'PARTIAL'
        else:
            ap_account.status = 'PENDING'

    @staticmethod
    @transaction.atomic
    def generate_ap_from_receipt(receipt, operator, receipt_event=None):
        """Auto generate AP from completed Purchase Receipt"""
        policy = get_policy("ap_payable", user=operator)
        if not policy.auto_create_payable_enabled():
            raise ValueError("当前配置未启用自动生成应付")
        if receipt.status != 'COMPLETED':
            raise ValueError("只有已完成的入库单才能生成应付账款")
            
        # Avoid duplicate AP for same receipt
        if APAccount.objects.filter(purchase_receipt=receipt, is_deleted=False).exists():
            raise ValueError(f"入库单 {receipt.receipt_no} 已生成过应付账款")

        # Total amount based on received quantities and PO snapshots
        if receipt_event:
            total_amt = Decimal(str(receipt_event['total_amount']))
        else:
            total_amt = Decimal('0')
            for item in receipt.items.all():
                total_amt += item.received_quantity * item.purchase_order_item.unit_price

        ap_no = APService.generate_ap_no()
        base_date = receipt.created_at.date() if receipt.created_at else timezone.now().date()
        due_date = SupplierSettlementService.calculate_due_date(receipt.purchase_order.supplier, base_date=base_date)
        
        ap = APAccount.objects.create(
            tenant=receipt.tenant or receipt.purchase_order.tenant,
            ap_no=ap_no,
            supplier=receipt.purchase_order.supplier,
            source_type='PURCHASE_RECEIPT',
            source_id=receipt.id,
            source_document_no_snapshot=receipt.receipt_no,
            purchase_receipt=receipt,
            total_amount=total_amt,
            paid_amount=0,
            due_date=due_date,
            status='PENDING',
            **build_erp_user_and_dept_kwargs(APAccount, user=operator),
        )
        
        APOperationLog.objects.create(
            tenant=ap.tenant,
            ap_account=ap,
            action="自动生成应付",
            after_value=f"金额: {total_amt}, 来源: {receipt.receipt_no}",
            **build_erp_user_fk_kwargs(APOperationLog, user=operator, field_names=("operator",)),
        )
        return ap

    @staticmethod
    @transaction.atomic
    def create_payment(supplier, amount, payment_date, payment_method, operator, cash_account=None, bank_account=None, remark=None):
        if amount <= 0:
            raise ValueError("付款金额必须大于0")
            
        payment_no = APService.generate_payment_no()
        payment = APPayment.objects.create(
            tenant=supplier.tenant,
            payment_no=payment_no,
            supplier=supplier,
            payment_amount=amount,
            allocated_amount=0,
            payment_date=payment_date,
            payment_method=payment_method,
            bank_account=bank_account,
            cash_account=cash_account,
            status='DRAFT',
            remark=remark,
            **build_erp_user_and_dept_kwargs(APPayment, user=operator),
        )
        
        # Update Cash Account balance (only when COMPLETED, but for now we follow simple flow)
        # In a real ERP, payment usually reduces cash when "Completed" or "Cleared"
        # For simplicity, we reduce when status is COMPLETED.
        # But create_payment initializes as DRAFT.
        
        APOperationLog.objects.create(
            tenant=payment.tenant,
            payment=payment,
            action="创建付款单",
            after_value=f"金额: {amount}",
            **build_erp_user_fk_kwargs(APOperationLog, user=operator, field_names=("operator",)),
        )
        return payment

    @staticmethod
    @transaction.atomic
    def submit_payment(payment, user):
        policy = get_policy("ap_payable", user=user)
        if payment.status != 'DRAFT':
            raise ValueError("只有草稿状态的付款单可以提交审核")
        payment.status = 'PENDING_APPROVAL' if policy.payment_approval_enabled() else 'APPROVED'
        payment.submitted_by = build_erp_user_fk_kwargs(
            APPayment,
            user=user,
            field_names=("submitted_by",),
        ).get("submitted_by")
        payment.submitted_at = timezone.now()
        if policy.payment_approval_enabled():
            payment.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])
        else:
            payment.approved_by = build_erp_user_fk_kwargs(
                APPayment,
                user=user,
                field_names=("approved_by",),
            ).get("approved_by")
            payment.approved_at = timezone.now()
            payment.save(update_fields=['status', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at', 'updated_at'])
        return payment

    @staticmethod
    @transaction.atomic
    def approve_payment(payment, user):
        """Approve payment only; execution is separated."""
        policy = get_policy("ap_payable", user=user)
        if not policy.payment_approval_enabled():
            raise ValueError("当前配置为免审批，付款单无需审核")
        payment = APPayment.objects.select_for_update().get(id=payment.id)
        if payment.status != 'PENDING_APPROVAL':
            raise ValueError("只有待审核状态的付款单可以审核支付")
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and (
            payment.created_by_id == erp_user_id or payment.submitted_by_id == erp_user_id
        ):
            raise ValueError("审核人不能是付款单创建人或提交人")

        payment.status = 'APPROVED'
        payment.approved_by = build_erp_user_fk_kwargs(
            APPayment,
            user=user,
            field_names=("approved_by",),
        ).get("approved_by")
        payment.approved_at = timezone.now()
        payment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        return payment

    @staticmethod
    @transaction.atomic
    def execute_payment(payment, user):
        payment = APPayment.objects.select_for_update().get(id=payment.id)
        if payment.status != 'APPROVED':
            raise ValueError("只有已审核状态的付款单可以执行")
        if payment.executed_at:
            raise ValueError("付款单已执行")

        if payment.cash_account:
            from business_apps.finance.models import CashAccount, CashAccountTransaction
            acc = CashAccount.objects.select_for_update().get(id=payment.cash_account_id)
            if acc.current_balance < payment.payment_amount:
                raise ValueError(f"账户余额不足！当前: {acc.current_balance}, 需要: {payment.payment_amount}")
            CashAccountTransaction.record_change(
                cash_account=acc,
                direction='OUTFLOW',
                amount=payment.payment_amount,
                source_type='AP_PAYMENT',
                source_id=payment.id,
                source_document_no_snapshot=payment.payment_no,
                transaction_date=payment.payment_date,
                operator=user,
                remark=payment.remark,
            )

        payment.executed_at = timezone.now()
        payment.save(update_fields=['executed_at', 'updated_at'])

        from business_apps.accounting.services import PostingService
        PostingService.post_payment_execution(payment, user)
        return payment

    @staticmethod
    @transaction.atomic
    def allocate_payment(payment, ap_accounts_data, operator):
        """
        Allocate a payment to multiple AP accounts.
        ap_accounts_data: list of {'ap_id': id, 'amount': amount}
        """
        # Lock records for concurrency safety
        payment = APPayment.objects.select_for_update().get(id=payment.id)
        policy = get_policy("ap_payable", user=operator)
        if not policy.allocation_enabled() or not policy.writeoff_enabled():
            raise ValueError("当前配置未启用应付核销")
        if not payment.executed_at:
            raise ValueError("只有已执行的付款单可以核销")

        total_to_allocate = sum(Decimal(str(item['amount'])) for item in ap_accounts_data)
        if total_to_allocate > payment.unallocated_amount:
            raise ValueError(f"核销总额 {total_to_allocate} 超过付款单未核销余额 {payment.unallocated_amount}")

        for item in ap_accounts_data:
            ap = APAccount.objects.select_for_update().get(id=item['ap_id'])
            alloc_amt = Decimal(str(item['amount']))
            
            if alloc_amt > ap.balance_amount:
                raise ValueError(f"核销金额 {alloc_amt} 超过应付单 {ap.ap_no} 剩余余额 {ap.balance_amount}")
            if not policy.allow_partial_payment() and alloc_amt != ap.balance_amount:
                raise ValueError(f"当前配置不允许部分付款，应付单 {ap.ap_no} 必须整笔付款")

            # Create allocation record
            APAllocation.objects.create(
                tenant=ap.tenant,
                allocation_no=APService.generate_allocation_no(),
                ap_account=ap,
                payment=payment,
                amount=alloc_amt,
                allocation_date=timezone.now().date(),
                **build_erp_user_fk_kwargs(APAllocation, user=operator, field_names=("created_by",)),
            )
            
            # Update AP Account
            old_ap_status = ap.status
            ap.paid_amount += alloc_amt
            APService._update_ap_status(ap)
            ap.save()
            
            APOperationLog.objects.create(
                tenant=ap.tenant,
                ap_account=ap,
                action="付款核销",
                before_value=f"已付: {ap.paid_amount - alloc_amt}, 状态: {old_ap_status}",
                after_value=f"本次核销: {alloc_amt}, 已付: {ap.paid_amount}, 状态: {ap.status}",
                **build_erp_user_fk_kwargs(APOperationLog, user=operator, field_names=("operator",)),
            )

            # Update Payment
            payment.allocated_amount += alloc_amt
            if payment.allocated_amount >= payment.payment_amount:
                payment.status = 'COMPLETED'
            payment.save(update_fields=['allocated_amount', 'status', 'updated_at'])

        return payment

    @staticmethod
    @transaction.atomic
    def reverse_ap_for_purchase_return(return_order, operator):
        if not return_order.purchase_order_id or not return_order.supplier_id:
            raise ValueError("采购退货单未关联采购订单或供应商，无法执行应付反向调整")

        amount = Decimal('0')
        purchase_items_by_product = {}
        for purchase_item in return_order.purchase_order.items.all():
            purchase_items_by_product.setdefault(purchase_item.product_id, purchase_item)
        for item in return_order.items.all():
            purchase_item = purchase_items_by_product.get(item.product_id)
            unit_price = purchase_item.unit_price if purchase_item else (item.product.cost_price or Decimal('0'))
            amount += Decimal(str(item.quantity)) * Decimal(str(unit_price))

        if amount <= 0:
            raise ValueError("采购退货单金额必须大于0")

        ap_queryset = APAccount.objects.select_for_update().filter(
            supplier=return_order.supplier,
            is_deleted=False,
        ).exclude(status='CANCELLED')
        if return_order.purchase_order_id:
            ap_queryset = ap_queryset.filter(
                Q(purchase_receipt__purchase_order=return_order.purchase_order) |
                Q(purchase_receipt__isnull=True)
            )
        ap_queryset = ap_queryset.order_by('created_at', 'id')

        remaining = amount
        for ap_account in ap_queryset:
            adjustable = ap_account.total_amount - ap_account.paid_amount
            if adjustable <= 0 or remaining <= 0:
                continue

            delta = min(adjustable, remaining)
            old_amount = ap_account.total_amount
            old_status = ap_account.status
            ap_account.total_amount -= delta
            APService._update_ap_status(ap_account)
            ap_account.remark = (ap_account.remark or '').strip()
            suffix = f"采购退货反向调整 {return_order.return_no}: -{delta}"
            ap_account.remark = f"{ap_account.remark}; {suffix}" if ap_account.remark else suffix
            ap_account.save(update_fields=['total_amount', 'status', 'remark', 'updated_at'])
            APOperationLog.objects.create(
                tenant=ap_account.tenant,
                ap_account=ap_account,
                action="采购退货反向调整",
                before_value=f"金额: {old_amount}, 状态: {old_status}",
                after_value=f"退货冲减: {delta}, 金额: {ap_account.total_amount}, 状态: {ap_account.status}",
                **build_erp_user_fk_kwargs(APOperationLog, user=operator, field_names=("operator",)),
            )
            remaining -= delta

        if remaining > 0:
            credit_note = SupplierCreditNote.objects.create(
                tenant=return_order.tenant,
                credit_note_no=APService.generate_credit_note_no(),
                supplier=return_order.supplier,
                source_document_no_snapshot=return_order.return_no,
                source_id=return_order.id,
                amount=remaining,
                used_amount=Decimal('0'),
                note_date=timezone.now().date(),
                status='OPEN',
                remark=f"采购退货生成供应商贷项: {return_order.return_no}",
                **build_erp_user_fk_kwargs(
                    SupplierCreditNote,
                    user=operator,
                    field_names=("created_by",),
                ),
            )
            APOperationLog.objects.create(
                tenant=return_order.tenant,
                action="采购退货生成供应商贷项",
                after_value=f"贷项单: {credit_note.credit_note_no}, 金额: {remaining}",
                **build_erp_user_fk_kwargs(APOperationLog, user=operator, field_names=("operator",)),
            )

        return amount

    @staticmethod
    def get_statistics(start_date=None, end_date=None):
        base_q = Q()
        if start_date:
            base_q &= Q(created_at__date__gte=start_date)
        if end_date:
            base_q &= Q(created_at__date__lte=end_date)

        accounts = APAccount.objects.filter(base_q, is_deleted=False).exclude(status='CANCELLED')
        by_supplier = list(
            accounts.values('supplier__supplier_name').annotate(
                count=Count('id'),
                amount=Sum('total_amount'),
                balance=Sum(F('total_amount') - F('paid_amount')),
            ).order_by('-amount')[:10]
        )
        by_status = dict(
            accounts.values('status').annotate(count=Count('id')).values_list('status', 'count')
        )
        total_accounts = accounts.count()
        total_amount = accounts.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        total_paid = accounts.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0')
        total_balance = accounts.aggregate(total=Sum(F('total_amount') - F('paid_amount')))['total'] or Decimal('0')
        executed_payments = APPayment.objects.filter(base_q, executed_at__isnull=False)
        total_executed_payments = executed_payments.aggregate(total=Sum('payment_amount'))['total'] or Decimal('0')

        return {
            'total_accounts': total_accounts,
            'total_amount': total_amount,
            'total_paid': total_paid,
            'total_balance': total_balance,
            'total_executed_payments': total_executed_payments,
            'by_status': by_status,
            'by_supplier': by_supplier,
        }

    @staticmethod
    def get_aging_analysis(supplier_id=None):
        today = timezone.now().date()
        qs = APAccount.objects.filter(is_deleted=False).exclude(status='PAID')
        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
            
        analysis = []
        suppliers = qs.values('supplier__supplier_name', 'supplier__id').distinct()
        for s in suppliers:
            s_qs = qs.filter(supplier_id=s['supplier__id'])
            
            # Buckets
            not_due = s_qs.filter(due_date__gte=today).aggregate(bal=Sum(F('total_amount') - F('paid_amount')))['bal'] or 0
            overdue_1_30 = s_qs.filter(due_date__lt=today, due_date__gte=today - timezone.timedelta(days=30)).aggregate(bal=Sum(F('total_amount') - F('paid_amount')))['bal'] or 0
            overdue_31_60 = s_qs.filter(due_date__lt=today - timezone.timedelta(days=30), due_date__gte=today - timezone.timedelta(days=60)).aggregate(bal=Sum(F('total_amount') - F('paid_amount')))['bal'] or 0
            overdue_61_90 = s_qs.filter(due_date__lt=today - timezone.timedelta(days=60), due_date__gte=today - timezone.timedelta(days=90)).aggregate(bal=Sum(F('total_amount') - F('paid_amount')))['bal'] or 0
            overdue_90_plus = s_qs.filter(due_date__lt=today - timezone.timedelta(days=90)).aggregate(bal=Sum(F('total_amount') - F('paid_amount')))['bal'] or 0
            
            total = not_due + overdue_1_30 + overdue_31_60 + overdue_61_90 + overdue_90_plus
            
            if total > 0:
                analysis.append({
                    'supplier_id': s['supplier__id'],
                    'supplier_name': s['supplier__supplier_name'],
                    'total_balance': total,
                    'not_due': not_due,
                    'overdue_1_30': overdue_1_30,
                    'overdue_31_60': overdue_31_60,
                    'overdue_61_90': overdue_61_90,
                    'overdue_90_plus': overdue_90_plus,
                })
        return analysis

    @staticmethod
    def get_supplier_summary():
        # Aggregated stats per supplier
        return APAccount.objects.filter(is_deleted=False).values('supplier__supplier_name').annotate(
            total_ap=Sum('total_amount'),
            total_paid=Sum('paid_amount'),
            balance=Sum(F('total_amount') - F('paid_amount')),
            overdue_count=Count('id', filter=Q(due_date__lt=timezone.now().date(), status__in=['PENDING', 'PARTIAL']))
        ).order_by('-balance')
