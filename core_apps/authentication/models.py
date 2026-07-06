from django.db import models
from django.contrib.auth.models import AbstractUser
from core_apps.organization.models import Department

class Permission(models.Model):
    TYPE_CHOICES = (
        ('MENU', '菜单'),
        ('BUTTON', '按钮'),
    )
    name = models.CharField(max_length=50, verbose_name="名称")
    code = models.CharField(max_length=100, unique=True, verbose_name="权限标识")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='MENU')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    path = models.CharField(max_length=200, null=True, blank=True, verbose_name="路由路径")
    component = models.CharField(max_length=200, null=True, blank=True, verbose_name="组件路径")
    icon = models.CharField(max_length=50, null=True, blank=True, verbose_name="图标")
    hide_in_menu = models.BooleanField(default=False, verbose_name="在菜单中隐藏")
    order = models.IntegerField(default=0, verbose_name="排序")
    status = models.BooleanField(default=True, verbose_name="状态")

    class Meta:
        verbose_name = "权限"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name

class Role(models.Model):
    SCOPE_CHOICES = (
        ('ALL', '全部数据'),
        ('SELF', '仅本人数据'),
        ('DEPARTMENT', '本部门数据'),
    )
    name = models.CharField(max_length=50, verbose_name="角色名称")
    code = models.CharField(max_length=50, unique=True, verbose_name="角色标识")
    data_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='SELF', verbose_name="数据权限范围")
    permissions = models.ManyToManyField(Permission, blank=True, verbose_name="功能权限")
    status = models.BooleanField(default=True, verbose_name="状态")

    class Meta:
        verbose_name = "角色"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name

class User(AbstractUser):
    dept = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属部门")
    roles = models.ManyToManyField(Role, blank=True, verbose_name="拥有角色")
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name="手机号")
    status = models.BooleanField(default=True, verbose_name="用户状态")

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name
