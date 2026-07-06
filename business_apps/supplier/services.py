from .models import Supplier, SupplierTransferLog
from django.utils import timezone
from django.db import transaction
from business_apps.platform.services import CodeRuleService
from core_apps.erp_auth.compat import build_erp_user_fk_kwargs

def generate_supplier_code():
    """Generates a code in format SUP2026050001"""
    return CodeRuleService.generate('SUPPLIER_CODE')

def check_duplicate_supplier(name, tax_number=None, phone=None, email=None, exclude_id=None):
    """Checks if a supplier already exists with same name, tax number, phone or email"""
    q = Supplier.objects.filter(is_deleted=False)
    if exclude_id:
        q = q.exclude(id=exclude_id)
        
    errors = []
    if q.filter(supplier_name=name).exists():
        errors.append("供应商名称已存在")
    if tax_number and q.filter(tax_number=tax_number).exists():
        errors.append("纳税人识别号已存在")
    if phone and q.filter(contact_phone=phone).exists():
        errors.append("联系电话已存在")
    if email and q.filter(email=email).exists():
        errors.append("邮箱已存在")
        
    return errors

def check_can_delete_supplier(supplier):
    """
    Checks if a supplier can be deleted based on business rules.
    Standard ERP rule: Cannot delete if active purchase orders exist.
    """
    reasons = []
    # This will be active when purchase module is implemented
    # if supplier.purchase_orders.filter(is_deleted=False).exists():
    #     reasons.append("存在关联采购记录")
    
    return reasons

@transaction.atomic
def transfer_supplier(supplier, new_owner, operator, remark=None):
    """Handles supplier ownership transfer"""
    old_owner = supplier.owner
    supplier.owner = new_owner
    supplier.dept = None
    supplier.save()
    
    SupplierTransferLog.objects.create(
        tenant=supplier.tenant,
        supplier=supplier,
        old_owner=old_owner,
        new_owner=new_owner,
        remark=remark,
        **build_erp_user_fk_kwargs(
            SupplierTransferLog,
            user=operator,
            field_names=("operator",),
        ),
    )
    return supplier


class SupplierSettlementService:
    PAYMENT_TERM_DAYS = {
        'PREPAID': 0,
        'NET_30': 30,
        'NET_60': 60,
        'NET_90': 90,
    }

    @classmethod
    def get_payment_term_days(cls, supplier):
        return cls.PAYMENT_TERM_DAYS.get(supplier.payment_term or 'NET_30', 30)

    @classmethod
    def calculate_due_date(cls, supplier, base_date=None):
        base_date = base_date or timezone.now().date()
        return base_date + timezone.timedelta(days=cls.get_payment_term_days(supplier))
