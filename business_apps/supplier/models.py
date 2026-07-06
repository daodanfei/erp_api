from django.db import models
from django.utils import timezone
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant

class Supplier(models.Model):
    SUPPLIER_TYPE = (
        ('MANUFACTURER', '制造商'),
        ('DISTRIBUTOR', '分销商'),
        ('SERVICE_PROVIDER', '服务商'),
        ('LOGISTICS', '物流商'),
        ('OTHER', '其他'),
    )
    SUPPLIER_LEVEL = (('A', 'A级'), ('B', 'B级'), ('C', 'C级'), ('D', 'D级'))
    STATUS = (('ACTIVE', '激活'), ('INACTIVE', '未激活'), ('BLACKLIST', '黑名单'))
    PAYMENT_TERMS = (
        ('PREPAID', '预付'),
        ('NET_30', '30天账期'),
        ('NET_60', '60天账期'),
        ('NET_90', '90天账期'),
    )
    PAYMENT_METHODS = (
        ('CASH', '现金'),
        ('BANK_TRANSFER', '银行转账'),
        ('CHECK', '支票'),
        ('WECHAT', '微信'),
        ('ALIPAY', '支付宝'),
        ('OTHER', '其他'),
    )
    SETTLEMENT_CYCLES = (
        ('PER_RECEIPT', '逐单结算'),
        ('WEEKLY', '周结'),
        ('BIWEEKLY', '半月结'),
        ('MONTHLY', '月结'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='suppliers', null=True, blank=True)
    supplier_code = models.CharField(max_length=50, unique=True, verbose_name="供应商编码")
    supplier_name = models.CharField(max_length=255, verbose_name="供应商名称")
    short_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="简称")
    supplier_type = models.CharField(max_length=20, choices=SUPPLIER_TYPE, default='MANUFACTURER')
    supplier_level = models.CharField(max_length=10, choices=SUPPLIER_LEVEL, default='C')
    industry = models.CharField(max_length=100, null=True, blank=True)
    tax_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="纳税人识别号")
    contact_phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    website = models.URLField(null=True, blank=True)
    country = models.CharField(max_length=100, default='China')
    province = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='ACTIVE')
    
    # Settlement Info
    currency = models.CharField(max_length=10, default='CNY', verbose_name="常用币种")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.13, verbose_name="默认税率")
    payment_term = models.CharField(max_length=20, choices=PAYMENT_TERMS, default='NET_30', verbose_name="默认账期")
    default_payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        default='BANK_TRANSFER',
        verbose_name="默认付款方式",
    )
    settlement_cycle = models.CharField(
        max_length=20,
        choices=SETTLEMENT_CYCLES,
        default='PER_RECEIPT',
        verbose_name="结算周期",
    )
    bank_name = models.CharField(max_length=255, null=True, blank=True)
    bank_account = models.CharField(max_length=100, null=True, blank=True)
    account_holder = models.CharField(max_length=255, null=True, blank=True)

    # Ownership & Permissions
    owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='owned_suppliers')
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Soft Delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='deleted_suppliers')
    
    remark = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_suppliers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "供应商"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['supplier_name']),
            models.Index(fields=['tax_number']),
            models.Index(fields=['contact_phone']),
        ]

    def __str__(self):
        return f"{self.supplier_code} - {self.supplier_name}"

class SupplierContact(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_contacts', null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='contacts')
    name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=(('M', '男'), ('F', '女'), ('U', '未知')), default='U')
    position = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    mobile = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    wechat = models.CharField(max_length=100, null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    sort = models.IntegerField(default=0)
    remark = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort', 'id']

class SupplierFollowRecord(models.Model):
    FOLLOW_TYPE = (
        ('PHONE', '电话'), ('VISIT', '拜访'), ('EMAIL', '邮件'), ('MEETING', '会议'), ('OTHER', '其他')
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_follow_records', null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='follow_records')
    follow_type = models.CharField(max_length=20, choices=FOLLOW_TYPE)
    content = models.TextField()
    next_follow_time = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SupplierTag(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_tags', null=True, blank=True)
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=20, default='blue')
    sort = models.IntegerField(default=0)
    suppliers = models.ManyToManyField(Supplier, related_name='tags')

class SupplierAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_attachments', null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='attachments')
    file_name = models.CharField(max_length=255)
    file_url = models.CharField(max_length=500)
    file_size = models.BigIntegerField()
    expiry_date = models.DateField(null=True, blank=True, verbose_name="资质到期日")
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

class SupplierEvaluation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_evaluations', null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='evaluations')
    quality_score = models.IntegerField(default=5) # 1~5
    delivery_score = models.IntegerField(default=5)
    service_score = models.IntegerField(default=5)
    price_score = models.IntegerField(default=5)
    remark = models.TextField(null=True, blank=True)
    evaluated_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    @property
    def average_score(self):
        return (self.quality_score + self.delivery_score + self.service_score + self.price_score) / 4.0

class SupplierTransferLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_transfer_logs', null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='transfer_logs')
    old_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='sup_transferred_from')
    new_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='sup_transferred_to')
    transfer_time = models.DateTimeField(auto_now_add=True)
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    remark = models.TextField(null=True, blank=True)
