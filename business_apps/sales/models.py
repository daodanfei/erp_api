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

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_orders', null=True, blank=True)
    order_no = models.CharField(max_length=50, unique=True, verbose_name="订单号")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders')
    
    # Snapshots (Redundant data for audit integrity)
    customer_name_snapshot = models.CharField(max_length=255, null=True, blank=True)
    customer_phone_snapshot = models.CharField(max_length=50, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    
    order_date = models.DateField(auto_now_add=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    
    total_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    remark = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_orders')
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_sales_orders')
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "销售订单"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

class SalesOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_items', null=True, blank=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    
    # Snapshot: Product info at creation
    product_name_snapshot = models.CharField(max_length=255, null=True, blank=True)
    
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True)
    
    quantity = models.DecimalField(max_digits=15, decimal_places=3)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    allocated_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    shipped_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    invoiced_quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    
    remark = models.TextField(null=True, blank=True)

class Shipment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='shipments', null=True, blank=True)
    shipment_no = models.CharField(max_length=50, unique=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name='shipments')
    status = models.CharField(max_length=20, default='SHIPPED')
    shipped_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)

class ShipmentItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='shipment_items', null=True, blank=True)
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey(SalesOrderItem, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=3)

class OrderApprovalLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_approval_logs', null=True, blank=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='approval_logs')
    action = models.CharField(max_length=50) # APPROVE, REJECT
    comment = models.TextField(null=True, blank=True)
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    approved_at = models.DateTimeField(auto_now_add=True)

class OrderChangeLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_change_logs', null=True, blank=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='change_logs')
    field_name = models.CharField(max_length=50)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class OrderAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_order_attachments', null=True, blank=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='attachments')
    file_name = models.CharField(max_length=255)
    file_url = models.CharField(max_length=500)
    uploaded_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


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

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales_execution_logs', null=True, blank=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='execution_logs')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20, null=True, blank=True)
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    remark = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "销售执行日志"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
