from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class ERPPermission(models.Model):
    TYPE_CHOICES = (
        ("MENU", "菜单"),
        ("BUTTON", "按钮"),
    )

    name = models.CharField(max_length=50, verbose_name="名称")
    code = models.CharField(max_length=100, unique=True, verbose_name="权限标识")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="MENU", verbose_name="权限类型")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    path = models.CharField(max_length=200, null=True, blank=True, verbose_name="路由路径")
    component = models.CharField(max_length=200, null=True, blank=True, verbose_name="组件路径")
    icon = models.CharField(max_length=50, null=True, blank=True, verbose_name="图标")
    hide_in_menu = models.BooleanField(default=False, verbose_name="在菜单中隐藏")
    order = models.IntegerField(default=0, verbose_name="排序")
    status = models.BooleanField(default=True, verbose_name="状态")

    class Meta:
        verbose_name = "ERP 权限"
        verbose_name_plural = verbose_name
        ordering = ["order", "id"]
        db_table = "erp_permissions"

    def __str__(self):
        return self.name


class ERPDepartment(models.Model):
    tenant = models.ForeignKey(
        "tenant.Tenant",
        on_delete=models.CASCADE,
        related_name="erp_departments",
        verbose_name="租户",
    )
    name = models.CharField(max_length=100, verbose_name="部门名称")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="上级部门",
    )
    order = models.IntegerField(default=0, verbose_name="排序")
    leader = models.CharField(max_length=50, blank=True, verbose_name="负责人")
    phone = models.CharField(max_length=20, blank=True, verbose_name="联系电话")
    email = models.EmailField(blank=True, verbose_name="邮箱")
    status = models.BooleanField(default=True, verbose_name="状态")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "ERP 部门"
        verbose_name_plural = verbose_name
        ordering = ["tenant_id", "order", "id"]
        db_table = "erp_departments"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_erp_department_name_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.name}"


class ERPRole(models.Model):
    SCOPE_CHOICES = (
        ("ALL", "全部数据"),
        ("SELF", "仅本人数据"),
        ("DEPARTMENT", "本部门数据"),
    )

    tenant = models.ForeignKey(
        "tenant.Tenant",
        on_delete=models.CASCADE,
        related_name="erp_roles",
        verbose_name="租户",
    )
    name = models.CharField(max_length=50, verbose_name="角色名称")
    code = models.CharField(max_length=50, verbose_name="角色标识")
    data_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="SELF", verbose_name="数据权限范围")
    permissions = models.ManyToManyField(ERPPermission, blank=True, verbose_name="功能权限")
    status = models.BooleanField(default=True, verbose_name="状态")
    is_system = models.BooleanField(default=False, verbose_name="是否系统角色")

    class Meta:
        verbose_name = "ERP 角色"
        verbose_name_plural = verbose_name
        ordering = ["tenant_id", "name", "id"]
        db_table = "erp_roles"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_erp_role_code_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.name}"


class ERPUserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, tenant, username: str, password: str | None = None, **extra_fields):
        if tenant is None:
            raise ValueError("ERP 用户必须归属租户")
        if not username:
            raise ValueError("ERP 用户必须提供用户名")
        user = self.model(tenant=tenant, username=username.strip(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, tenant, username: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("status", True)
        extra_fields.setdefault("is_super_admin", True)
        return self.create_user(tenant=tenant, username=username, password=password, **extra_fields)


class ERPUser(AbstractBaseUser):
    tenant = models.ForeignKey(
        "tenant.Tenant",
        on_delete=models.CASCADE,
        related_name="erp_users",
        verbose_name="租户",
    )
    dept = models.ForeignKey(
        ERPDepartment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="所属部门",
    )
    username = models.CharField(max_length=150, verbose_name="用户名")
    name = models.CharField(max_length=150, blank=True, verbose_name="姓名")
    phone = models.CharField(max_length=20, blank=True, verbose_name="手机号")
    email = models.EmailField(blank=True, verbose_name="邮箱")
    status = models.BooleanField(default=True, verbose_name="用户状态")
    is_super_admin = models.BooleanField(default=False, verbose_name="是否租户超级管理员")
    must_change_password = models.BooleanField(default=True, verbose_name="是否首次改密")
    last_login_at = models.DateTimeField(null=True, blank=True, verbose_name="最近登录时间")
    roles = models.ManyToManyField(ERPRole, blank=True, related_name="users", verbose_name="拥有角色")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    objects = ERPUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "ERP 用户"
        verbose_name_plural = verbose_name
        ordering = ["tenant_id", "username", "id"]
        db_table = "erp_users"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "username"], name="uniq_erp_username_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.username}"
