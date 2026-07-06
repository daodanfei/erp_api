from django.conf import settings
from django.db import models


class OperationLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="用户")
    path = models.CharField(max_length=200, verbose_name="请求路径")
    method = models.CharField(max_length=10, verbose_name="请求方法")
    params = models.TextField(null=True, blank=True, verbose_name="请求参数")
    response = models.TextField(null=True, blank=True, verbose_name="响应结果")
    status_code = models.IntegerField(verbose_name="状态码")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP地址")
    browser = models.CharField(max_length=200, null=True, blank=True, verbose_name="浏览器")
    execution_time = models.FloatField(verbose_name="执行时间(ms)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "操作日志"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
