from django.db import models
from business_apps.inventory.models import Product, Warehouse
from business_apps.crm.models import Customer
from business_apps.supplier.models import Supplier
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant


# ==================== 销售出库 ====================

class OutboundOrder(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('PENDING', '待审核'),
        ('APPROVED', '已审核'),
        ('COMPLETED', '已完成'),
        ('CANCELLED', '已取消'),
    )

    STATUS_TRANSITIONS = {
        'DRAFT': ['PENDING', 'CANCELLED'],
        'PENDING': ['APPROVED', 'CANCELLED'],
        'APPROVED': ['COMPLETED', 'CANCELLED'],
        'COMPLETED': [],
        'CANCELLED': [],
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='outbound_orders', null=True, blank=True)
    outbound_no = models.CharField(max_length=50, unique=True, verbose_name="出库单号")
    sales_order = models.ForeignKey('sales.SalesOrder', on_delete=models.PROTECT, null=True, blank=True, related_name='outbound_orders', verbose_name="销售订单")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="出库仓库")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="状态")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_outbound_orders', verbose_name="提交人")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="提交时间")
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_outbound_orders', verbose_name="审核人")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "销售出库单"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['outbound_no']),
            models.Index(fields=['sales_order']),
            models.Index(fields=['warehouse']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
            models.Index(fields=['dept']),
        ]

    def __str__(self):
        return self.outbound_no

    def can_transition_to(self, target_status):
        return target_status in self.STATUS_TRANSITIONS.get(self.status, [])


class OutboundOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='outbound_order_items', null=True, blank=True)
    outbound_order = models.ForeignKey(OutboundOrder, on_delete=models.CASCADE, related_name='items', verbose_name="出库单")
    sales_order_item = models.ForeignKey(
        'sales.SalesOrderItem',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='outbound_items',
        verbose_name="销售订单明细",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    product_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="商品名称快照")
    product_code_snapshot = models.CharField(max_length=50, null=True, blank=True, verbose_name="商品编码快照")
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="出库数量")
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="出库单价")
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="出库金额")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "销售出库明细"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['outbound_order']),
        ]


# ==================== 仓库调拨 ====================

class TransferOrder(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('PENDING_APPROVAL', '待审核'),
        ('APPROVED', '已审核'),
        ('IN_TRANSIT', '调拨中'),
        ('COMPLETED', '已完成'),
        ('CANCELLED', '已取消'),
    )

    STATUS_TRANSITIONS = {
        'DRAFT': ['PENDING_APPROVAL', 'CANCELLED'],
        'PENDING_APPROVAL': ['APPROVED', 'CANCELLED'],
        'APPROVED': ['IN_TRANSIT', 'CANCELLED'],
        'IN_TRANSIT': ['COMPLETED', 'CANCELLED'],
        'COMPLETED': [],
        'CANCELLED': [],
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='transfer_orders', null=True, blank=True)
    transfer_no = models.CharField(max_length=50, unique=True, verbose_name="调拨单号")
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transfer_from_orders', verbose_name="调出仓库")
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transfer_to_orders', verbose_name="调入仓库")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="状态")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_transfer_orders', verbose_name="提交人")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="提交时间")
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transfer_orders', verbose_name="审核人")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")
    outbound_confirmed_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='outbound_confirmed_transfer_orders', verbose_name="调出确认人")
    outbound_confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="调出确认时间")
    inbound_confirmed_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='inbound_confirmed_transfer_orders', verbose_name="调入确认人")
    inbound_confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="调入确认时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="取消时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "仓库调拨单"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transfer_no']),
            models.Index(fields=['from_warehouse']),
            models.Index(fields=['to_warehouse']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return self.transfer_no

    def can_transition_to(self, target_status):
        return target_status in self.STATUS_TRANSITIONS.get(self.status, [])


class TransferOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='transfer_order_items', null=True, blank=True)
    transfer_order = models.ForeignKey(TransferOrder, on_delete=models.CASCADE, related_name='items', verbose_name="调拨单")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    product_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="商品名称快照")
    product_code_snapshot = models.CharField(max_length=50, null=True, blank=True, verbose_name="商品编码快照")
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="调拨数量")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "调拨明细"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['transfer_order']),
        ]


# ==================== 销售退货 ====================

class SalesReturnOrder(models.Model):
    FINANCE_STATUS_CHOICES = (
        ('PENDING', '待处理'),
        ('ADJUSTED', '已调整'),
        ('NOT_REQUIRED', '无需处理'),
    )

    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('APPROVED', '已审核'),
        ('COMPLETED', '已完成'),
        ('CANCELLED', '已取消'),
    )

    STATUS_TRANSITIONS = {
        'DRAFT': ['APPROVED', 'CANCELLED'],
        'APPROVED': ['COMPLETED', 'CANCELLED'],
        'COMPLETED': [],
        'CANCELLED': [],
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_return_orders', null=True, blank=True)
    return_no = models.CharField(max_length=50, unique=True, verbose_name="退货单号")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, verbose_name="客户")
    customer_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="客户名称快照")
    sales_order = models.ForeignKey('sales.SalesOrder', on_delete=models.PROTECT, null=True, blank=True, related_name='return_orders', verbose_name="销售订单")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="退货仓库")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="状态")
    reason = models.TextField(null=True, blank=True, verbose_name="退货原因")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    finance_status = models.CharField(max_length=20, choices=FINANCE_STATUS_CHOICES, default='PENDING', verbose_name="财务处理状态")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "销售退货单"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['return_no']),
            models.Index(fields=['customer']),
            models.Index(fields=['sales_order']),
            models.Index(fields=['warehouse']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return self.return_no

    def can_transition_to(self, target_status):
        return target_status in self.STATUS_TRANSITIONS.get(self.status, [])


class SalesReturnOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_return_order_items', null=True, blank=True)
    return_order = models.ForeignKey(SalesReturnOrder, on_delete=models.CASCADE, related_name='items', verbose_name="退货单")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    product_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="商品名称快照")
    product_code_snapshot = models.CharField(max_length=50, null=True, blank=True, verbose_name="商品编码快照")
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="退货数量")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "销售退货明细"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['return_order']),
        ]


# ==================== 采购退货 ====================

class PurchaseReturnOrder(models.Model):
    FINANCE_STATUS_CHOICES = (
        ('PENDING', '待处理'),
        ('ADJUSTED', '已调整'),
        ('NOT_REQUIRED', '无需处理'),
    )

    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('APPROVED', '已审核'),
        ('COMPLETED', '已完成'),
        ('CANCELLED', '已取消'),
    )

    STATUS_TRANSITIONS = {
        'DRAFT': ['APPROVED', 'CANCELLED'],
        'APPROVED': ['COMPLETED', 'CANCELLED'],
        'COMPLETED': [],
        'CANCELLED': [],
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='purchase_return_orders', null=True, blank=True)
    return_no = models.CharField(max_length=50, unique=True, verbose_name="退货单号")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, verbose_name="供应商")
    supplier_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="供应商名称快照")
    purchase_order = models.ForeignKey('purchase.PurchaseOrder', on_delete=models.PROTECT, null=True, blank=True, related_name='return_orders', verbose_name="采购订单")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, verbose_name="退货仓库")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', verbose_name="状态")
    reason = models.TextField(null=True, blank=True, verbose_name="退货原因")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    finance_status = models.CharField(max_length=20, choices=FINANCE_STATUS_CHOICES, default='PENDING', verbose_name="财务处理状态")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "采购退货单"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['return_no']),
            models.Index(fields=['supplier']),
            models.Index(fields=['purchase_order']),
            models.Index(fields=['warehouse']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return self.return_no

    def can_transition_to(self, target_status):
        return target_status in self.STATUS_TRANSITIONS.get(self.status, [])


class PurchaseReturnOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='purchase_return_order_items', null=True, blank=True)
    return_order = models.ForeignKey(PurchaseReturnOrder, on_delete=models.CASCADE, related_name='items', verbose_name="退货单")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    product_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="商品名称快照")
    product_code_snapshot = models.CharField(max_length=50, null=True, blank=True, verbose_name="商品编码快照")
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="退货数量")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "采购退货明细"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['return_order']),
        ]


# ==================== 库存预警 ====================

class InventoryAlert(models.Model):
    ALERT_TYPE_CHOICES = (
        ('LOW_STOCK', '低库存'),
        ('OUT_OF_STOCK', '缺货'),
        ('OVER_STOCK', '超库存'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='inventory_alerts', null=True, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, verbose_name="仓库")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="商品")
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPE_CHOICES, verbose_name="预警类型")
    current_qty = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="当前库存")
    threshold_value = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True, verbose_name="阈值")
    is_resolved = models.BooleanField(default=False, verbose_name="已处理")
    resolved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="处理人")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "库存预警"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['warehouse', 'product']),
            models.Index(fields=['alert_type']),
            models.Index(fields=['is_resolved']),
        ]
