from django.db import models

class Department(models.Model):
    name = models.CharField(max_length=100, verbose_name="部门名称")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children', verbose_name="上级部门")
    order = models.IntegerField(default=0, verbose_name="排序")
    leader = models.CharField(max_length=50, null=True, blank=True, verbose_name="负责人")
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name="联系电话")
    email = models.EmailField(null=True, blank=True, verbose_name="邮箱")
    status = models.BooleanField(default=True, verbose_name="状态")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "部门"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name
