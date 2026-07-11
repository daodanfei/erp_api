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

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customers', null=True, blank=True, verbose_name="租户")
    customer_code = models.CharField(max_length=50, unique=True, verbose_name="客户编码")
    customer_name = models.CharField(max_length=255, verbose_name="客户名称")
    short_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="简称")
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE, default='COMPANY', verbose_name="客户类型")
    customer_level = models.CharField(max_length=10, choices=CUSTOMER_LEVEL, default='C', verbose_name="客户等级")
    industry = models.CharField(max_length=100, null=True, blank=True, verbose_name="所属行业")
    phone = models.CharField(max_length=50, null=True, blank=True, verbose_name="手机号")
    email = models.EmailField(null=True, blank=True, verbose_name="邮箱")
    website = models.URLField(null=True, blank=True, verbose_name="网址")
    country = models.CharField(max_length=100, default='China', verbose_name="国家")
    province = models.CharField(max_length=100, null=True, blank=True, verbose_name="省份")
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="城市")
    address = models.TextField(null=True, blank=True, verbose_name="地址")
    status = models.CharField(max_length=20, choices=STATUS, default='ACTIVE', verbose_name="状态")
    
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
    owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='owned_customers', verbose_name="负责人")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    
    # Soft Delete
    is_deleted = models.BooleanField(default=False, verbose_name="是否删除")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    deleted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='deleted_customers', verbose_name="删除人")
    
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_customers', verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        indexes = [
            models.Index(fields=['customer_name']),
            models.Index(fields=['phone']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"{self.customer_code} - {self.customer_name}"

class Contact(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_contacts', null=True, blank=True, verbose_name="租户")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='contacts', verbose_name="客户")
    name = models.CharField(max_length=100, verbose_name="联系人姓名")
    gender = models.CharField(max_length=10, choices=(('M', '男'), ('F', '女'), ('U', '未知')), default='U', verbose_name="性别")
    position = models.CharField(max_length=100, null=True, blank=True, verbose_name="职位")
    phone = models.CharField(max_length=50, null=True, blank=True, verbose_name="电话")
    mobile = models.CharField(max_length=50, null=True, blank=True, verbose_name="手机")
    email = models.EmailField(null=True, blank=True, verbose_name="邮箱")
    wechat = models.CharField(max_length=100, null=True, blank=True, verbose_name="微信")
    is_primary = models.BooleanField(default=False, verbose_name="是否主要联系人")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

class FollowRecord(models.Model):
    FOLLOW_TYPE = (
        ('PHONE', '电话'), ('VISIT', '拜访'), ('WECHAT', '微信'),
        ('EMAIL', '邮件'), ('MEETING', '会议'), ('OTHER', '其他')
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_follow_records', null=True, blank=True, verbose_name="租户")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='follow_records', verbose_name="客户")
    follow_type = models.CharField(max_length=20, choices=FOLLOW_TYPE, verbose_name="跟进方式")
    content = models.TextField(verbose_name="跟进内容")
    next_follow_time = models.DateTimeField(null=True, blank=True, verbose_name="下次跟进时间")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

class CustomerTag(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_tags', null=True, blank=True, verbose_name="租户")
    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    color = models.CharField(max_length=20, default='blue', verbose_name="标签颜色")
    sort = models.IntegerField(default=0, verbose_name="排序")
    customers = models.ManyToManyField(Customer, related_name='tags', verbose_name="关联客户")

class CustomerAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_attachments', null=True, blank=True, verbose_name="租户")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='attachments', verbose_name="客户")
    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_url = models.CharField(max_length=500, verbose_name="文件地址") # Compatible with S3/MinIO
    file_size = models.BigIntegerField(verbose_name="文件大小")
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

class TransferLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_transfer_logs', null=True, blank=True, verbose_name="租户")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='transfer_logs', verbose_name="客户")
    old_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='transferred_from', verbose_name="原负责人")
    new_owner = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='transferred_to', verbose_name="新负责人")
    transfer_time = models.DateTimeField(auto_now_add=True, verbose_name="转移时间")
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
