import hashlib
import os
from django.db import models
from core_apps.erp_auth.models import ERPUser


# ==================== 文件中心 ====================

class File(models.Model):
    """统一文件管理"""
    STORAGE_TYPE_CHOICES = (
        ('LOCAL', '本地存储'),
        ('MINIO', 'MinIO'),
        ('S3', 'Amazon S3'),
    )
    MODULE_CHOICES = (
        ('customer', '客户'), ('supplier', '供应商'), ('product', '商品'),
        ('purchase', '采购'), ('sales', '销售'), ('inventory', '库存'),
        ('supply_chain', '供应链'), ('report', '报表'), ('system', '系统'),
    )
    ACCESS_LEVEL_CHOICES = (
        ('PUBLIC', '公开'),
        ('LOGIN', '登录可见'),
        ('BUSINESS', '业务权限继承'),
    )

    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_ext = models.CharField(max_length=20, blank=True, verbose_name="文件扩展名")
    mime_type = models.CharField(max_length=100, blank=True, verbose_name="MIME类型")
    file_size = models.BigIntegerField(default=0, verbose_name="文件大小(字节)")
    storage_type = models.CharField(max_length=10, choices=STORAGE_TYPE_CHOICES, default='LOCAL', verbose_name="存储类型")
    bucket = models.CharField(max_length=100, blank=True, verbose_name="存储桶")
    object_key = models.CharField(max_length=500, blank=True, verbose_name="对象键")
    file_url = models.CharField(max_length=500, verbose_name="文件访问URL")
    md5 = models.CharField(max_length=32, blank=True, verbose_name="MD5校验")
    module = models.CharField(max_length=20, choices=MODULE_CHOICES, verbose_name="所属模块")
    business_type = models.CharField(max_length=50, verbose_name="业务类型", help_text="如: purchase_order, sales_order, customer")
    business_id = models.IntegerField(verbose_name="业务ID")
    access_level = models.CharField(max_length=10, choices=ACCESS_LEVEL_CHOICES, default='BUSINESS', verbose_name="访问级别")
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")
    is_deleted = models.BooleanField(default=False, verbose_name="是否删除")

    class Meta:
        verbose_name = "文件"
        verbose_name_plural = verbose_name
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['module', 'business_type', 'business_id'], name='idx_file_business'),
            models.Index(fields=['md5'], name='idx_file_md5'),
            models.Index(fields=['uploaded_by'], name='idx_file_uploader'),
            models.Index(fields=['storage_type'], name='idx_file_storage'),
        ]

    def __str__(self):
        return self.file_name


# ==================== 字典中心 ====================

class DictType(models.Model):
    """字典分类"""
    dict_code = models.CharField(max_length=50, unique=True, verbose_name="字典编码")
    dict_name = models.CharField(max_length=100, verbose_name="字典名称")
    remark = models.CharField(max_length=500, blank=True, verbose_name="备注")
    status = models.CharField(max_length=10, choices=(('ACTIVE', '启用'), ('DISABLED', '禁用')), default='ACTIVE', verbose_name="状态")
    sort = models.IntegerField(default=0, verbose_name="排序")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "字典分类"
        verbose_name_plural = verbose_name
        ordering = ['sort', 'id']
        db_table = 'sys_dict_types'

    def __str__(self):
        return f"{self.dict_name}({self.dict_code})"


class DictItem(models.Model):
    """字典项"""
    dict_type = models.ForeignKey(DictType, on_delete=models.CASCADE, related_name='items', verbose_name="字典分类")
    item_code = models.CharField(max_length=50, verbose_name="字典项编码")
    item_name = models.CharField(max_length=100, verbose_name="字典项名称")
    item_value = models.CharField(max_length=200, blank=True, verbose_name="字典项值", help_text="可选，用于存储额外数据")
    color = models.CharField(max_length=20, blank=True, verbose_name="颜色标记")
    sort = models.IntegerField(default=0, verbose_name="排序")
    status = models.CharField(max_length=10, choices=(('ACTIVE', '启用'), ('DISABLED', '禁用')), default='ACTIVE', verbose_name="状态")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "字典项"
        verbose_name_plural = verbose_name
        ordering = ['sort', 'id']
        db_table = 'sys_dict_items'
        unique_together = ('dict_type', 'item_code')
        indexes = [
            models.Index(fields=['dict_type', 'status'], name='idx_dict_item_type_status'),
        ]

    def __str__(self):
        return f"{self.item_name}({self.item_code})"


# ==================== 编码规则中心 ====================

class CodeRule(models.Model):
    """编码规则"""
    RESET_TYPE_CHOICES = (
        ('NEVER', '永不重置'),
        ('YEAR', '按年重置'),
        ('MONTH', '按月重置'),
        ('DAY', '按日重置'),
    )

    rule_code = models.CharField(max_length=50, unique=True, verbose_name="规则编码", help_text="如: SALES_ORDER, PURCHASE_ORDER")
    rule_name = models.CharField(max_length=100, verbose_name="规则名称")
    prefix = models.CharField(max_length=10, verbose_name="前缀", help_text="如: SO, PO, CUS")
    date_format = models.CharField(max_length=20, default='%Y%m%d', verbose_name="日期格式", help_text="如: %Y%m%d, %Y%m, 留空则不含日期")
    sequence_length = models.IntegerField(default=4, verbose_name="流水号位数")
    current_sequence = models.IntegerField(default=0, verbose_name="当前序号")
    current_date_key = models.CharField(max_length=20, blank=True, default='', verbose_name="当前日期键", help_text="用于判断是否需要重置序号")
    reset_type = models.CharField(max_length=10, choices=RESET_TYPE_CHOICES, default='DAY', verbose_name="重置策略")
    status = models.CharField(max_length=10, choices=(('ACTIVE', '启用'), ('DISABLED', '禁用')), default='ACTIVE', verbose_name="状态")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "编码规则"
        verbose_name_plural = verbose_name
        ordering = ['rule_code']
        db_table = 'code_rules'
        indexes = [
            models.Index(fields=['rule_code'], name='idx_code_rule_code'),
        ]

    def __str__(self):
        return f"{self.rule_name}({self.rule_code})"
