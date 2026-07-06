from django.db import models
from business_apps.supplier.models import Supplier
from business_apps.inventory.models import Product, Warehouse
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant


class PurchaseOrder(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    STATUS_RECEIVED = "RECEIVED"
    STATUS_CLOSED = "CLOSED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "草稿"),
        (STATUS_PENDING_APPROVAL, "待审核"),
        (STATUS_APPROVED, "审核通过"),
        (STATUS_REJECTED, "已驳回"),
        (STATUS_PARTIALLY_RECEIVED, "部分到货"),
        (STATUS_RECEIVED, "全部到货"),
        (STATUS_CLOSED, "已关闭"),
        (STATUS_CANCELLED, "已取消"),
    )

    # 状态机：定义合法的状态跳转
    STATUS_TRANSITIONS = {
        STATUS_DRAFT: [STATUS_PENDING_APPROVAL, STATUS_APPROVED, STATUS_CANCELLED],
        STATUS_PENDING_APPROVAL: [STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED],
        STATUS_APPROVED: [STATUS_CANCELLED],
        STATUS_REJECTED: [STATUS_DRAFT, STATUS_CANCELLED],
        STATUS_PARTIALLY_RECEIVED: [],
        STATUS_RECEIVED: [STATUS_CLOSED],
        STATUS_CLOSED: [],
        STATUS_CANCELLED: [],
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_orders", null=True, blank=True)
    purchase_order_no = models.CharField(
        max_length=50, unique=True, verbose_name="采购单号"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_orders"
    )

    # 供应商快照
    supplier_name_snapshot = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="供应商名称快照"
    )
    supplier_code_snapshot = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="供应商编码快照"
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="DRAFT", verbose_name="状态"
    )
    order_date = models.DateField(auto_now_add=True, verbose_name="订单日期")
    expected_arrival_date = models.DateField(
        null=True, blank=True, verbose_name="预计到货日期"
    )

    total_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, default=0, verbose_name="总数量"
    )
    total_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="总金额"
    )

    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    created_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_purchase_orders",
        verbose_name="创建人",
    )
    submitted_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_purchase_orders",
        verbose_name="提交人",
    )
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="提交时间")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="关闭时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "采购订单"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["purchase_order_no"]),
            models.Index(fields=["supplier"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_by"]),
            models.Index(fields=["order_date"]),
            models.Index(fields=["dept"]),
        ]

    def __str__(self):
        return self.purchase_order_no

    def can_transition_to(self, target_status):
        return target_status in self.STATUS_TRANSITIONS.get(self.status, [])


class PurchaseOrderItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_order_items", null=True, blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="采购订单",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")

    # 商品快照
    product_name_snapshot = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="商品名称快照"
    )
    product_code_snapshot = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="商品编码快照"
    )
    unit_price_snapshot = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="商品成本价快照",
    )

    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, null=True, blank=True, verbose_name="仓库"
    )
    quantity = models.DecimalField(
        max_digits=15, decimal_places=3, verbose_name="采购数量"
    )
    unit_price = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="单价"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="金额")

    received_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, default=0, verbose_name="已收货数量"
    )
    returned_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, default=0, verbose_name="已退货数量"
    )
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "采购订单明细"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["purchase_order"]),
            models.Index(fields=["product"]),
        ]


class PurchaseReceipt(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "草稿"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_CANCELLED, "已取消"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_receipts", null=True, blank=True)
    receipt_no = models.CharField(max_length=50, unique=True, verbose_name="入库单号")
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="receipts",
        verbose_name="采购订单",
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, verbose_name="仓库"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name="状态"
    )
    received_at = models.DateTimeField(null=True, blank=True, verbose_name="入库时间")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="创建人",
    )
    executed_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="executed_purchase_receipts",
        verbose_name="执行人",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="取消时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "采购入库单"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["receipt_no"]),
            models.Index(fields=["purchase_order"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return self.receipt_no


class PurchaseReceiptItem(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_receipt_items", null=True, blank=True)
    receipt = models.ForeignKey(
        PurchaseReceipt,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="入库单",
    )
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem, on_delete=models.PROTECT, verbose_name="采购订单明细"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="商品")

    # 商品快照（入库时的商品信息）
    product_name_snapshot = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="商品名称快照"
    )
    product_code_snapshot = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="商品编码快照"
    )

    received_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, verbose_name="入库数量"
    )
    remark = models.TextField(null=True, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "采购入库明细"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["receipt"]),
        ]


class PurchaseApprovalLog(models.Model):
    ACTION_CHOICES = (
        ("AUTO_APPROVE", "自动审核通过"),
        ("APPROVE", "审核通过"),
        ("REJECT", "审核驳回"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_approval_logs", null=True, blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="approval_logs",
        verbose_name="采购订单",
    )
    action = models.CharField(
        max_length=50, choices=ACTION_CHOICES, verbose_name="审核动作"
    )
    comment = models.TextField(null=True, blank=True, verbose_name="审核意见")
    approved_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="审核人",
    )
    approved_at = models.DateTimeField(auto_now_add=True, verbose_name="审核时间")

    class Meta:
        verbose_name = "采购审批日志"
        verbose_name_plural = verbose_name
        ordering = ["-approved_at"]
        indexes = [
            models.Index(fields=["purchase_order"]),
        ]


class PurchaseChangeLog(models.Model):
    """采购变更日志：记录采购数量、价格、供应商等变更"""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_change_logs", null=True, blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="change_logs",
        verbose_name="采购订单",
    )
    field_name = models.CharField(max_length=100, verbose_name="变更字段")
    old_value = models.TextField(null=True, blank=True, verbose_name="变更前")
    new_value = models.TextField(null=True, blank=True, verbose_name="变更后")
    changed_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="变更人",
    )
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="变更时间")

    class Meta:
        verbose_name = "采购变更日志"
        verbose_name_plural = verbose_name
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["purchase_order"]),
        ]


class PurchaseAttachment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_attachments", null=True, blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="采购订单",
    )
    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_url = models.CharField(max_length=500, verbose_name="文件地址")
    uploaded_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="上传人",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        verbose_name = "采购附件"
        verbose_name_plural = verbose_name
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["purchase_order"]),
        ]
