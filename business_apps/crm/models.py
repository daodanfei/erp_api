from django.db import models
from django.utils import timezone
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant

class Customer(models.Model):
    CUSTOMER_TYPE = (('PERSONAL', '个人'), ('COMPANY', '公司'))
    CUSTOMER_LEVEL = (('A', 'A级'), ('B', 'B级'), ('C', 'C级'), ('D', 'D级'))
    STATUS = (('ACTIVE', '激活'), ('INACTIVE', '未激活'), ('BLACKLIST', '黑名单'))
    PAYMENT_TERMS = (
        ('PREPAID', '预付'),
        ('NET_30', '30天账期'),
        ('NET_60', '60天账期'),
        ('NET_90', '90天账期'),
    )
    PAYMENT_METHODS = (
        ('BANK_TRANSFER', '银行转账'),
        ('WECHAT', '微信支付'),
        ('ALIPAY', '支付宝'),
        ('CASH', '现金'),
        ('OTHER', '其他'),
    )
    CREDIT_CONTROL_MODES = (
        ('NONE', '不控制'),
        ('WARN', '超额预警'),
        ('BLOCK', '超额阻断'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customers', null=True, blank=True)
    customer_code = models.CharField(max_length=50, unique=True, verbose_name="客户编码")
    customer_name = models.CharField(max_length=255, verbose_name="客户名称")
    short_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="简称")
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE, default='COMPANY')
    customer_level = models.CharField(max_length=10, choices=CUSTOMER_LEVEL, default='C')
    industry = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    website = models.URLField(null=True, blank=True)
    country = models.CharField(max_length=100, default='China')
    province = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='ACTIVE')
    
    # Financial/Credit fields
    payment_term = models.CharField(max_length=20, choices=PAYMENT_TERMS, default='NET_30', verbose_name="默认账期")
    default_payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='BANK_TRANSFER', verbose_name="默认收款方式")
    credit_control_mode = models.CharField(max_length=20, choices=CREDIT_CONTROL_MODES, default='BLOCK', verbose_name="信用控制模式")
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="信用额度")
    current_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name="当前应收余额",
        help_text="缓存字段，由过账或往来子账回写",
    )
    
    # Ownership & Permissions
    owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='owned_customers')
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Soft Delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='deleted_customers')
    
    remark = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_customers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['customer_name']),
            models.Index(fields=['phone']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"{self.customer_code} - {self.customer_name}"

class Contact(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_contacts', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='contacts')
    name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=(('M', '男'), ('F', '女'), ('U', '未知')), default='U')
    position = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    mobile = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    wechat = models.CharField(max_length=100, null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    remark = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class FollowRecord(models.Model):
    FOLLOW_TYPE = (
        ('PHONE', '电话'), ('VISIT', '拜访'), ('WECHAT', '微信'),
        ('EMAIL', '邮件'), ('MEETING', '会议'), ('OTHER', '其他')
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_follow_records', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='follow_records')
    follow_type = models.CharField(max_length=20, choices=FOLLOW_TYPE)
    content = models.TextField()
    next_follow_time = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class CustomerTag(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_tags', null=True, blank=True)
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=20, default='blue')
    sort = models.IntegerField(default=0)
    customers = models.ManyToManyField(Customer, related_name='tags')

class CustomerAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_attachments', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='attachments')
    file_name = models.CharField(max_length=255)
    file_url = models.CharField(max_length=500) # Compatible with S3/MinIO
    file_size = models.BigIntegerField()
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

class TransferLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_transfer_logs', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='transfer_logs')
    old_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='transferred_from')
    new_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='transferred_to')
    transfer_time = models.DateTimeField(auto_now_add=True)
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    remark = models.TextField(null=True, blank=True)
