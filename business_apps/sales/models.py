from django.db import models
from business_apps.crm.models import Customer
from business_apps.inventory.models import Product, Warehouse
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant

class SalesOrder(models.Model):
    STATUS_DRAFT = 'DRAFT'
    STATUS_PENDING_APPROVAL = 'PENDING_APPROVAL'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_ALLOCATED = 'ALLOCATED'
    STATUS_PARTIALLY_SHIPPED = 'PARTIALLY_SHIPPED'
    STATUS_SHIPPED = 'SHIPPED'
    STATUS_CLOSED = 'CLOSED'
    STATUS_CANCELLED = 'CANCELLED'

    # Standard fulfillment statuses:
    # APPROVED: order passed approval and is waiting for stock allocation.
    # ALLOCATED: stock has been reserved and the order can create outbound requests.
    # PARTIALLY_SHIPPED: some quantity has been shipped, but fulfillment is incomplete.
    # SHIPPED: all ordered quantity has been shipped.
    # CLOSED: fulfillment lifecycle is closed after shipment completion.
    # CANCELLED: remaining unfulfilled quantity has been cancelled.
    STATUS_CHOICES = (
        (STATUS_DRAFT, '草稿'),
        (STATUS_PENDING_APPROVAL, '待审核'),
        (STATUS_APPROVED, '审核通过'),
        (STATUS_REJECTED, '已驳回'),
        (STATUS_ALLOCATED, '库存已锁定'),
        (STATUS_PARTIALLY_SHIPPED, '部分发货'),
        (STATUS_SHIPPED, '全部发货'),
        (STATUS_CLOSED, '已关闭'),
        (STATUS_CANCELLED, '已取消'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_orders', null=True, blank=True, verbose_name="租户")
    order_no = models.CharField(max_length=50, unique=True, verbose_name="订单号")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders', verbose_name="客户")
    
    # Snapshots (Redundant data for audit integrity)
    customer_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="客户名称快照")
    customer_phone_snapshot = models.CharField(max_length=50, null=True, blank=True, verbose_name="客户电话快照")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name="状态")
    
    order_date = models.DateField(auto_now_add=True, verbose_name="订单日期")
    expected_delivery_date = models.DateField(null=True, blank=True, verbose_name="预计交付日期")
    
    total_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="总数量")
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="总金额")
    
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_orders', verbose_name="创建人")
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_sales_orders', verbose_name="提交人")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="提交时间")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="关闭时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "销售订单"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

class SalesOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_items', null=True, blank=True, verbose_name="租户")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='items', verbose_name="销售订单")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    
    # Snapshot: Product info at creation
    product_name_snapshot = models.CharField(max_length=255, null=True, blank=True, verbose_name="商品名称快照")
    
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name="仓库")
    
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="销售数量")
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="单价")
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="金额")
    
    allocated_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="已分配数量")
    shipped_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="已发货数量")
    invoiced_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name="已开票数量")
    
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

class Shipment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='shipments', null=True, blank=True, verbose_name="租户")
    shipment_no = models.CharField(max_length=50, unique=True, verbose_name="发货单号")
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name='shipments', verbose_name="销售订单")
    status = models.CharField(max_length=20, default='SHIPPED', verbose_name="状态")
    shipped_at = models.DateTimeField(auto_now_add=True, verbose_name="发货时间")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")

class ShipmentItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='shipment_items', null=True, blank=True, verbose_name="租户")
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='items', verbose_name="发货单")
    order_item = models.ForeignKey(SalesOrderItem, on_delete=models.PROTECT, verbose_name="销售订单明细")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name="发货数量")

class OrderApprovalLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_approval_logs', null=True, blank=True, verbose_name="租户")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='approval_logs', verbose_name="销售订单")
    action = models.CharField(max_length=50, verbose_name="审核动作") # APPROVE, REJECT
    comment = models.TextField(null=True, blank=True, verbose_name="审核意见")
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="审核人")
    approved_at = models.DateTimeField(auto_now_add=True, verbose_name="审核时间")

class OrderChangeLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_change_logs', null=True, blank=True, verbose_name="租户")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='change_logs', verbose_name="销售订单")
    field_name = models.CharField(max_length=50, verbose_name="变更字段")
    old_value = models.TextField(null=True, blank=True, verbose_name="变更前")
    new_value = models.TextField(null=True, blank=True, verbose_name="变更后")
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

class OrderAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_attachments', null=True, blank=True, verbose_name="租户")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='attachments', verbose_name="销售订单")
    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_url = models.CharField(max_length=500, verbose_name="文件地址")
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")


class SalesExecutionLog(models.Model):
    ACTION_SUBMIT = 'SUBMIT'
    ACTION_APPROVE = 'APPROVE'
    ACTION_REJECT = 'REJECT'
    ACTION_ALLOCATE = 'ALLOCATE'
    ACTION_CREATE_OUTBOUND = 'CREATE_OUTBOUND'
    ACTION_CLOSE = 'CLOSE'
    ACTION_CANCEL = 'CANCEL'

    ACTION_CHOICES = (
        (ACTION_SUBMIT, '提交'),
        (ACTION_APPROVE, '审核通过'),
        (ACTION_REJECT, '审核驳回'),
        (ACTION_ALLOCATE, '锁库'),
        (ACTION_CREATE_OUTBOUND, '生成出库申请'),
        (ACTION_CLOSE, '关闭'),
        (ACTION_CANCEL, '取消'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_execution_logs', null=True, blank=True, verbose_name="租户")
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='execution_logs', verbose_name="销售订单")
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, verbose_name="执行动作")
    from_status = models.CharField(max_length=20, null=True, blank=True, verbose_name="原状态")
    to_status = models.CharField(max_length=20, null=True, blank=True, verbose_name="新状态")
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "销售执行日志"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
