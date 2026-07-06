from django.db import models
from core_apps.erp_auth.models import ERPUser


class ReportExportTask(models.Model):
    """报表导出任务"""
    STATUS_CHOICES = (
        ('PENDING', '等待中'),
        ('PROCESSING', '处理中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
    )

    REPORT_TYPE_CHOICES = (
        ('DASHBOARD', '经营驾驶舱'),
        ('SALES_SUMMARY', '销售汇总'),
        ('SALES_TREND', '销售趋势'),
        ('SALES_PRODUCTS', '商品销售排行'),
        ('SALES_CUSTOMERS', '客户销售排行'),
        ('PURCHASE_SUMMARY', '采购汇总'),
        ('PURCHASE_TREND', '采购趋势'),
        ('PURCHASE_SUPPLIERS', '供应商采购排行'),
        ('INVENTORY_SUMMARY', '库存汇总'),
        ('INVENTORY_AGING', '库龄分析'),
        ('INVENTORY_ALERTS', '库存预警'),
        ('CUSTOMER_ANALYSIS', '客户分析'),
        ('SUPPLIER_ANALYSIS', '供应商分析'),
        ('PRODUCT_ANALYSIS', '商品分析'),
    )

    report_type = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES, verbose_name="报表类型")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="状态")
    file_url = models.CharField(max_length=500, null=True, blank=True, verbose_name="文件URL")
    file_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="文件名")
    params = models.JSONField(default=dict, blank=True, verbose_name="查询参数")
    error_message = models.TextField(null=True, blank=True, verbose_name="错误信息")
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")

    class Meta:
        verbose_name = "报表导出任务"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['report_type']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.status}"


class ReportSnapshot(models.Model):
    """报表快照：缓存统计结果，避免每次全表统计"""
    REPORT_TYPE_CHOICES = (
        ('DASHBOARD', '经营驾驶舱'),
        ('SALES_SUMMARY', '销售汇总'),
        ('PURCHASE_SUMMARY', '采购汇总'),
        ('INVENTORY_SUMMARY', '库存汇总'),
    )

    snapshot_date = models.DateField(verbose_name="快照日期")
    report_type = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES, verbose_name="报表类型")
    data_json = models.JSONField(verbose_name="快照数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "报表快照"
        verbose_name_plural = verbose_name
        ordering = ['-snapshot_date']
        unique_together = ('snapshot_date', 'report_type')
        indexes = [
            models.Index(fields=['snapshot_date']),
            models.Index(fields=['report_type']),
        ]

    def __str__(self):
        return f"{self.report_type} - {self.snapshot_date}"
