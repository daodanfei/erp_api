from decimal import Decimal
from django.db.models import F, Sum
from .models import Customer, TransferLog
from django.utils import timezone
from django.db import transaction
from business_apps.platform.services import CodeRuleService
from core_apps.erp_auth.compat import build_erp_user_fk_kwargs

def generate_customer_code():
    """Generates a code in format CUS2026050001"""
    return CodeRuleService.generate('CUSTOMER_CODE')

def check_duplicate(name, phone=None, email=None, exclude_id=None, tenant=None):
    """Checks if a customer already exists with same name, phone or email"""
    q = Customer.objects.filter(is_deleted=False)
    if tenant:
        q = q.filter(tenant=tenant)
    if exclude_id:
        q = q.exclude(id=exclude_id)
        
    errors = []
    if q.filter(customer_name=name).exists():
        errors.append("客户名称已存在")
    if phone and q.filter(phone=phone).exists():
        errors.append("手机号已存在")
    if email and q.filter(email=email).exists():
        errors.append("邮箱已存在")
        
    return errors

@transaction.atomic
def transfer_customer(customer, new_owner, operator, remark=None):
    """Handles customer ownership transfer"""
    old_owner = customer.owner
    customer.owner = new_owner
    customer.dept = None
    customer.save()
    
    TransferLog.objects.create(
        tenant=customer.tenant,
        customer=customer,
        old_owner=old_owner,
        new_owner=new_owner,
        remark=remark,
        **build_erp_user_fk_kwargs(
            TransferLog,
            user=operator,
            field_names=("operator",),
        ),
    )
    return customer


class CustomerCreditService:
    PAYMENT_TERM_DAYS = {
        'PREPAID': 0,
        'NET_30': 30,
        'NET_60': 60,
        'NET_90': 90,
    }

    @classmethod
    def get_payment_term_days(cls, customer):
        return cls.PAYMENT_TERM_DAYS.get(customer.payment_term or 'NET_30', 30)

    @classmethod
    def calculate_due_date(cls, customer, base_date=None):
        base_date = base_date or timezone.now().date()
        return base_date + timezone.timedelta(days=cls.get_payment_term_days(customer))

    @classmethod
    def get_credit_overview(cls, customer):
        from business_apps.ar_receivable.models import Receivable

        today = timezone.now().date()
        open_receivables = Receivable.objects.filter(customer=customer, is_deleted=False).exclude(status__in=['PAID', 'CANCELLED'])
        overdue_amount = open_receivables.filter(due_date__lt=today).aggregate(
            total=Sum(F('amount') - F('written_off_amount'))
        )['total'] or Decimal('0')
        available_credit = None
        if customer.credit_limit > 0:
            available_credit = customer.credit_limit - customer.current_balance

        def decimal_text(value):
            if value is None:
                return None
            return f"{Decimal(value):.2f}"

        return {
            'credit_limit': decimal_text(customer.credit_limit),
            'current_balance': decimal_text(customer.current_balance),
            'available_credit': decimal_text(available_credit),
            'credit_control_mode': customer.credit_control_mode,
            'payment_term': customer.payment_term,
            'default_payment_method': customer.default_payment_method,
            'overdue_amount': decimal_text(overdue_amount),
            'is_over_limit': customer.credit_limit > 0 and customer.current_balance > customer.credit_limit,
        }

    @classmethod
    def check_limit(cls, customer, new_order_amount, allow_exception=False):
        if customer.credit_limit <= 0 or customer.credit_control_mode == 'NONE':
            return True, None

        current_exposure = customer.current_balance
        new_order_amount = Decimal(str(new_order_amount))
        total_exposure = current_exposure + new_order_amount
        if total_exposure <= customer.credit_limit:
            return True, None

        message = (
            f"超过信用额度！限额: {customer.credit_limit}, "
            f"当前应收: {current_exposure}, 本单: {new_order_amount}"
        )
        if customer.credit_control_mode == 'WARN':
            return True, message
        if allow_exception:
            return True, f"{message}，已按例外放行"
        return False, message
