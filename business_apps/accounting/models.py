from decimal import Decimal

from django.db import models
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant


class AccountSubject(models.Model):
    CATEGORY_ASSET = "ASSET"
    CATEGORY_LIABILITY = "LIABILITY"
    CATEGORY_EQUITY = "EQUITY"
    CATEGORY_COST = "COST"
    CATEGORY_PNL = "PNL"

    CATEGORY_CHOICES = (
        (CATEGORY_ASSET, "资产"),
        (CATEGORY_LIABILITY, "负债"),
        (CATEGORY_EQUITY, "权益"),
        (CATEGORY_COST, "成本"),
        (CATEGORY_PNL, "损益"),
    )

    BALANCE_DEBIT = "DEBIT"
    BALANCE_CREDIT = "CREDIT"
    BALANCE_DIRECTION_CHOICES = (
        (BALANCE_DEBIT, "借"),
        (BALANCE_CREDIT, "贷"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="account_subjects", null=True, blank=True)
    code = models.CharField(max_length=20, verbose_name="科目编码")
    name = models.CharField(max_length=100, verbose_name="科目名称")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, verbose_name="科目类别")
    balance_direction = models.CharField(
        max_length=10,
        choices=BALANCE_DIRECTION_CHOICES,
        verbose_name="余额方向",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="上级科目",
    )
    level = models.PositiveIntegerField(default=1, verbose_name="级次")
    is_leaf = models.BooleanField(default=True, verbose_name="末级科目")
    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    created_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_account_subjects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "会计科目"
        verbose_name_plural = verbose_name
        ordering = ["code"]
        unique_together = ("tenant", "code")
        indexes = [
            models.Index(fields=["tenant", "code"]),
            models.Index(fields=["category"]),
            models.Index(fields=["enabled"]),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class AccountingPeriod(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_CLOSED = "CLOSED"
    STATUS_CHOICES = (
        (STATUS_OPEN, "打开"),
        (STATUS_CLOSED, "关闭"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="accounting_periods", null=True, blank=True)
    year = models.PositiveIntegerField(verbose_name="年度")
    month = models.PositiveIntegerField(verbose_name="期间")
    start_date = models.DateField(verbose_name="开始日期")
    end_date = models.DateField(verbose_name="结束日期")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="关闭时间")
    closed_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_accounting_periods",
        verbose_name="关闭人",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "会计期间"
        verbose_name_plural = verbose_name
        ordering = ["-year", "-month"]
        unique_together = ("tenant", "year", "month")
        indexes = [
            models.Index(fields=["tenant", "year", "month"]),
            models.Index(fields=["start_date", "end_date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.year}-{self.month:02d}"


class Voucher(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_POSTED = "POSTED"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "草稿"),
        (STATUS_POSTED, "已过账"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="vouchers", null=True, blank=True)
    voucher_no = models.CharField(max_length=50, unique=True, verbose_name="凭证号")
    voucher_date = models.DateField(verbose_name="凭证日期")
    period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="vouchers",
        verbose_name="会计期间",
    )
    voucher_type = models.CharField(max_length=30, verbose_name="凭证类型")
    abstract = models.CharField(max_length=255, verbose_name="摘要")
    source_type = models.CharField(max_length=50, verbose_name="来源单据类型")
    source_id = models.IntegerField(verbose_name="来源单据ID")
    source_document_no = models.CharField(max_length=100, verbose_name="来源单号")
    total_debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_POSTED)
    posted_at = models.DateTimeField(null=True, blank=True, verbose_name="过账时间")
    posted_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_vouchers",
        verbose_name="过账人",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "会计凭证"
        verbose_name_plural = verbose_name
        ordering = ["-voucher_date", "-id"]
        indexes = [
            models.Index(fields=["voucher_no"]),
            models.Index(fields=["voucher_date"]),
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["voucher_type"]),
        ]

    def __str__(self):
        return self.voucher_no


class VoucherLine(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="voucher_lines", null=True, blank=True)
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="凭证",
    )
    line_no = models.PositiveIntegerField(verbose_name="行号")
    subject = models.ForeignKey(
        AccountSubject,
        on_delete=models.PROTECT,
        related_name="voucher_lines",
        verbose_name="会计科目",
    )
    summary = models.CharField(max_length=255, verbose_name="行摘要")
    debit_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    business_type = models.CharField(max_length=50, null=True, blank=True, verbose_name="业务类型")
    business_id = models.IntegerField(null=True, blank=True, verbose_name="业务ID")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "凭证明细"
        verbose_name_plural = verbose_name
        ordering = ["voucher_id", "line_no"]
        unique_together = ("voucher", "line_no")
        indexes = [
            models.Index(fields=["subject"]),
            models.Index(fields=["business_type", "business_id"]),
        ]


class BusinessPostingLog(models.Model):
    STATUS_SUCCESS = "SUCCESS"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = (
        (STATUS_SUCCESS, "成功"),
        (STATUS_FAILED, "失败"),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="business_posting_logs", null=True, blank=True)
    event_type = models.CharField(max_length=50, verbose_name="过账事件")
    business_type = models.CharField(max_length=50, verbose_name="业务类型")
    business_id = models.IntegerField(verbose_name="业务ID")
    business_document_no = models.CharField(max_length=100, verbose_name="业务单号")
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="posting_logs",
        verbose_name="凭证",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    error_message = models.TextField(null=True, blank=True, verbose_name="错误信息")
    payload = models.JSONField(default=dict, blank=True, verbose_name="过账载荷")
    created_by = models.ForeignKey(
        ERPUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_posting_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "业务过账日志"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        unique_together = ("tenant", "event_type", "business_type", "business_id")
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["business_type", "business_id"]),
            models.Index(fields=["business_document_no"]),
        ]
