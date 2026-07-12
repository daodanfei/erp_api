from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant

class ProductCategory(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='product_categories', null=True, blank=True, verbose_name="租户")
    name = models.CharField(max_length=100, verbose_name="分类名称")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children', verbose_name="上级分类")
    sort = models.IntegerField(default=0, verbose_name="排序")
    status = models.BooleanField(default=True, verbose_name="状态")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    
    class Meta:
        verbose_name = "商品分类"
        verbose_name_plural = verbose_name
        ordering = ['sort', 'id']

    def __str__(self):
        return self.name

class Unit(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='units', null=True, blank=True, verbose_name="租户")
    name = models.CharField(max_length=50, verbose_name="单位名称")
    code = models.CharField(max_length=20, unique=True, verbose_name="单位编码")
    status = models.BooleanField(default=True, verbose_name="状态")

    class Meta:
        verbose_name = "计量单位"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name

class Product(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('ACTIVE', '启用'),
        ('DISABLED', '禁用'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='products', null=True, blank=True, verbose_name="租户")
    product_code = models.CharField(max_length=50, unique=True, verbose_name="商品编码")
    barcode = models.CharField(max_length=100, null=True, blank=True, verbose_name="条码")
    name = models.CharField(max_length=255, verbose_name="商品名称")
    short_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="简称")
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name='products', verbose_name="分类")
    brand = models.CharField(max_length=100, null=True, blank=True, verbose_name="品牌")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='products', verbose_name="单位")
    specification = models.CharField(max_length=255, null=True, blank=True, verbose_name="规格型号")
    
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="成本价")
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="销售价")
    
    min_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="最低库存")
    max_stock = models.DecimalField(max_digits=15, decimal_places=3, default=999999, verbose_name="最高库存")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="状态")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    
    # Cached total stock across warehouses. The inventory app is the source of truth.
    current_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="当前库存")
    
    # Ownership & Audit
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    is_deleted = models.BooleanField(default=False, verbose_name="是否删除")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    deleted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_products', verbose_name="删除人")
    
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_products', verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "商品"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['product_code']),
            models.Index(fields=['barcode']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"[{self.product_code}] {self.name}"

class ProductImage(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='product_images', null=True, blank=True, verbose_name="租户")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images', verbose_name="商品")
    file_url = models.CharField(max_length=500, verbose_name="文件路径")
    sort = models.IntegerField(default=0, verbose_name="排序")
    is_cover = models.BooleanField(default=False, verbose_name="是否封面")
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

class ProductAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='product_attachments', null=True, blank=True, verbose_name="租户")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='attachments', verbose_name="商品")
    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_url = models.CharField(max_length=500, verbose_name="文件路径")
    file_size = models.BigIntegerField(verbose_name="文件大小")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

class ProductTag(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='product_tags', null=True, blank=True, verbose_name="租户")
    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    color = models.CharField(max_length=20, default='blue', verbose_name="颜色")
    sort = models.IntegerField(default=0, verbose_name="排序")
    products = models.ManyToManyField(Product, related_name='tags', verbose_name="关联商品")

class Warehouse(models.Model):
    TYPE_CHOICES = (('MAIN', '主仓库'), ('BRANCH', '分仓'), ('TEMPORARY', '临时仓'))
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='warehouses', null=True, blank=True, verbose_name="租户")
    warehouse_code = models.CharField(max_length=50, unique=True, verbose_name="仓库编码")
    warehouse_name = models.CharField(max_length=100, verbose_name="仓库名称")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='MAIN', verbose_name="仓库类型")
    manager = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="负责人")
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name="联系电话")
    address = models.TextField(null=True, blank=True, verbose_name="地址")
    status = models.BooleanField(default=True, verbose_name="是否启用")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "仓库"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.warehouse_name

class Inventory(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='inventories', null=True, blank=True, verbose_name="租户")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='inventories', verbose_name="仓库")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='inventories', verbose_name="商品")
    current_qty = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="当前库存")
    locked_qty = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="锁定库存")
    # available_qty is property: current_qty - locked_qty
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "库存主表"
        verbose_name_plural = verbose_name
        unique_together = ('warehouse', 'product')

    @property
    def available_qty(self):
        return self.current_qty - self.locked_qty

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.available_qty < 0:
            raise ValidationError("可用库存不能为负数")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class InventoryTransaction(models.Model):
    DIRECTION_IN = 'IN'
    DIRECTION_OUT = 'OUT'
    DIRECTION_CHOICES = (
        (DIRECTION_IN, '入'),
        (DIRECTION_OUT, '出'),
    )
    TYPE_CHOICES = (
        ('PURCHASE_IN', '采购入库'),
        ('SALE_OUT', '销售出库'),
        ('MANUAL_ADJUST', '手动调整'),
        ('STOCKTAKE_GAIN', '盘盈入库'),
        ('STOCKTAKE_LOSS', '盘亏出库'),
        ('TRANSFER_IN', '调拨入库'),
        ('TRANSFER_OUT', '调拨出库'),
        ('RETURN_IN', '退货入库'),
        ('RETURN_OUT', '退货出库'),
    )
    TYPE_DIRECTION_MAP = {
        'PURCHASE_IN': DIRECTION_IN,
        'SALE_OUT': DIRECTION_OUT,
        'STOCKTAKE_GAIN': DIRECTION_IN,
        'STOCKTAKE_LOSS': DIRECTION_OUT,
        'TRANSFER_IN': DIRECTION_IN,
        'TRANSFER_OUT': DIRECTION_OUT,
        'RETURN_IN': DIRECTION_IN,
        'RETURN_OUT': DIRECTION_OUT,
    }
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='inventory_transactions', null=True, blank=True, verbose_name="租户")
    transaction_no = models.CharField(max_length=50, unique=True, verbose_name="流水号")
    business_date = models.DateField(default=timezone.localdate, verbose_name="业务日期")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="仓库")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="业务类型")
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, verbose_name="方向")
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="变动数量") # Positive for IN, Negative for OUT
    before_qty = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="变动前库存")
    after_qty = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="变动后库存")
    unit_cost = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name="单位成本")
    total_cost = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name="成本金额")
    
    reference_type = models.CharField(max_length=50, null=True, blank=True, verbose_name="关联单据类型")
    reference_id = models.IntegerField(null=True, blank=True, verbose_name="关联单据ID")
    
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="操作人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "库存流水"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def clean(self):
        if self.quantity == 0:
            raise ValidationError("库存流水数量不能为0")

        if self.direction == self.DIRECTION_IN and self.quantity < 0:
            raise ValidationError("入库方向的库存流水数量必须大于0")

        if self.direction == self.DIRECTION_OUT and self.quantity > 0:
            raise ValidationError("出库方向的库存流水数量必须小于0")

        expected_direction = self.TYPE_DIRECTION_MAP.get(self.transaction_type)
        if expected_direction and self.direction != expected_direction:
            raise ValidationError("库存流水方向与交易类型不一致")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class Stocktake(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('IN_PROGRESS', '盘点中'),
        ('PENDING_APPROVAL', '待审核'),
        ('APPROVED', '已审核'),
        ('COMPLETED', '已完成'),
        ('CANCELLED', '已取消'),
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='stocktakes', null=True, blank=True, verbose_name="租户")
    stocktake_no = models.CharField(max_length=50, unique=True, verbose_name="盘点单号")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="仓库")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="状态")
    
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_stocktakes', verbose_name="创建人")
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_stocktakes', verbose_name="提交人")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="提交时间")
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_stocktakes', verbose_name="审核人")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    is_deleted = models.BooleanField(default=False, verbose_name="是否删除")

    class Meta:
        verbose_name = "库存盘点"
        verbose_name_plural = verbose_name

class StocktakeItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='stocktake_items', null=True, blank=True, verbose_name="租户")
    stocktake = models.ForeignKey(Stocktake, on_delete=models.CASCADE, related_name='items', verbose_name="盘点单")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    system_qty = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="系统数量")
    actual_qty = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="实盘数量")
    # difference_qty is actual - system
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    @property
    def difference_qty(self):
        return self.actual_qty - self.system_qty
