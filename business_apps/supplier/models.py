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

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='suppliers', null=True, blank=True, verbose_name="租户")
    supplier_code = models.CharField(max_length=50, unique=True, verbose_name="供应商编码")
    supplier_name = models.CharField(max_length=255, verbose_name="供应商名称")
    short_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="简称")
    supplier_type = models.CharField(max_length=20, choices=SUPPLIER_TYPE, default='MANUFACTURER', verbose_name="供应商类型")
    supplier_level = models.CharField(max_length=10, choices=SUPPLIER_LEVEL, default='C', verbose_name="供应商等级")
    industry = models.CharField(max_length=100, null=True, blank=True, verbose_name="所属行业")
    tax_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="纳税人识别号")
    contact_phone = models.CharField(max_length=50, null=True, blank=True, verbose_name="联系电话")
    email = models.EmailField(null=True, blank=True, verbose_name="邮箱")
    website = models.URLField(null=True, blank=True, verbose_name="网址")
    country = models.CharField(max_length=100, default='China', verbose_name="国家")
    province = models.CharField(max_length=100, null=True, blank=True, verbose_name="省份")
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="城市")
    address = models.TextField(null=True, blank=True, verbose_name="地址")
    status = models.CharField(max_length=20, choices=STATUS, default='ACTIVE', verbose_name="状态")
    
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
    bank_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="开户银行")
    bank_account = models.CharField(max_length=100, null=True, blank=True, verbose_name="银行账号")
    account_holder = models.CharField(max_length=255, null=True, blank=True, verbose_name="账户名")

    # Ownership & Permissions
    owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='owned_suppliers', verbose_name="负责人")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    
    # Soft Delete
    is_deleted = models.BooleanField(default=False, verbose_name="是否删除")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    deleted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='deleted_suppliers', verbose_name="删除人")
    
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_suppliers', verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

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
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_contacts', null=True, blank=True, verbose_name="租户")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='contacts', verbose_name="供应商")
    name = models.CharField(max_length=100, verbose_name="联系人姓名")
    gender = models.CharField(max_length=10, choices=(('M', '男'), ('F', '女'), ('U', '未知')), default='U', verbose_name="性别")
    position = models.CharField(max_length=100, null=True, blank=True, verbose_name="职位")
    phone = models.CharField(max_length=50, null=True, blank=True, verbose_name="电话")
    mobile = models.CharField(max_length=50, null=True, blank=True, verbose_name="手机")
    email = models.EmailField(null=True, blank=True, verbose_name="邮箱")
    wechat = models.CharField(max_length=100, null=True, blank=True, verbose_name="微信")
    is_primary = models.BooleanField(default=False, verbose_name="是否主要联系人")
    sort = models.IntegerField(default=0, verbose_name="排序")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['sort', 'id']

class SupplierFollowRecord(models.Model):
    FOLLOW_TYPE = (
        ('PHONE', '电话'), ('VISIT', '拜访'), ('EMAIL', '邮件'), ('MEETING', '会议'), ('OTHER', '其他')
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_follow_records', null=True, blank=True, verbose_name="租户")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='follow_records', verbose_name="供应商")
    follow_type = models.CharField(max_length=20, choices=FOLLOW_TYPE, verbose_name="跟进方式")
    content = models.TextField(verbose_name="跟进内容")
    next_follow_time = models.DateTimeField(null=True, blank=True, verbose_name="下次跟进时间")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

class SupplierTag(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_tags', null=True, blank=True, verbose_name="租户")
    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    color = models.CharField(max_length=20, default='blue', verbose_name="标签颜色")
    sort = models.IntegerField(default=0, verbose_name="排序")
    suppliers = models.ManyToManyField(Supplier, related_name='tags', verbose_name="关联供应商")

class SupplierAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_attachments', null=True, blank=True, verbose_name="租户")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='attachments', verbose_name="供应商")
    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_url = models.CharField(max_length=500, verbose_name="文件地址")
    file_size = models.BigIntegerField(verbose_name="文件大小")
    expiry_date = models.DateField(null=True, blank=True, verbose_name="资质到期日")
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

class SupplierEvaluation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_evaluations', null=True, blank=True, verbose_name="租户")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='evaluations', verbose_name="供应商")
    quality_score = models.IntegerField(default=5, verbose_name="质量评分") # 1~5
    delivery_score = models.IntegerField(default=5, verbose_name="交付评分")
    service_score = models.IntegerField(default=5, verbose_name="服务评分")
    price_score = models.IntegerField(default=5, verbose_name="价格评分")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    evaluated_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="评分人")
    evaluated_at = models.DateTimeField(auto_now_add=True, verbose_name="评分时间")

    @property
    def average_score(self):
        return (self.quality_score + self.delivery_score + self.service_score + self.price_score) / 4.0

class SupplierTransferLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_transfer_logs', null=True, blank=True, verbose_name="租户")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='transfer_logs', verbose_name="供应商")
    old_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='sup_transferred_from', verbose_name="原负责人")
    new_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='sup_transferred_to', verbose_name="新负责人")
    transfer_time = models.DateTimeField(auto_now_add=True, verbose_name="转移时间")
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
