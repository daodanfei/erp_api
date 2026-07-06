from django.conf import settings
from django.db import models
import uuid


class SystemBlueprint(models.Model):
    STATUS_CHOICES = (
        ("DRAFT", "草稿"),
        ("ACTIVE", "启用"),
        ("ARCHIVED", "归档"),
    )

    key = models.CharField(max_length=100, unique=True, verbose_name="蓝图标识")
    name = models.CharField(max_length=100, verbose_name="蓝图名称")
    description = models.TextField(blank=True, verbose_name="描述")
    industry = models.CharField(max_length=100, blank=True, verbose_name="行业")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT", verbose_name="状态")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_blueprints",
        verbose_name="创建人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "系统蓝图"
        verbose_name_plural = verbose_name
        ordering = ["name", "id"]
        db_table = "sys_blueprints"

    def __str__(self):
        return f"{self.name}({self.key})"


class SystemBlueprintVersion(models.Model):
    blueprint = models.ForeignKey(
        SystemBlueprint,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="蓝图",
    )
    version = models.CharField(max_length=50, verbose_name="版本号")
    config_json = models.JSONField(default=dict, blank=True, verbose_name="配置快照")
    change_note = models.CharField(max_length=500, blank=True, verbose_name="变更说明")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_blueprint_versions",
        verbose_name="创建人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    is_published = models.BooleanField(default=False, verbose_name="是否发布")

    class Meta:
        verbose_name = "蓝图版本"
        verbose_name_plural = verbose_name
        ordering = ["-created_at", "-id"]
        db_table = "sys_blueprint_versions"
        constraints = [
            models.UniqueConstraint(fields=["blueprint", "version"], name="uniq_blueprint_version"),
        ]

    def __str__(self):
        return f"{self.blueprint.key}@{self.version}"


class SystemInstance(models.Model):
    MODE_CHOICES = (
        ("SAAS", "SaaS"),
        ("CODE_EXPORT", "代码导出"),
    )
    STATUS_CHOICES = (
        ("DRAFT", "草稿"),
        ("GENERATING", "生成中"),
        ("ACTIVE", "可用"),
        ("INACTIVE", "停用"),
        ("FAILED", "失败"),
        ("ARCHIVED", "归档"),
    )

    blueprint = models.ForeignKey(
        SystemBlueprint,
        on_delete=models.PROTECT,
        related_name="instances",
        verbose_name="蓝图",
    )
    blueprint_version = models.ForeignKey(
        SystemBlueprintVersion,
        on_delete=models.PROTECT,
        related_name="instances",
        verbose_name="蓝图版本",
    )
    instance_key = models.CharField(max_length=100, unique=True, null=True, blank=True, verbose_name="实例标识")
    name = models.CharField(max_length=100, verbose_name="实例名称")
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, verbose_name="模式")
    runtime_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="SAAS", verbose_name="运行模式")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT", verbose_name="状态")
    tenant = models.ForeignKey(
        "tenant.Tenant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="instances",
        verbose_name="租户",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_system_instances",
        verbose_name="创建人",
    )
    current_generation_job = models.ForeignKey(
        "GenerationJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_for_instances",
        verbose_name="当前生成任务",
    )
    artifact_path = models.CharField(max_length=500, blank=True, verbose_name="产物路径")
    artifact_checksum = models.CharField(max_length=128, blank=True, verbose_name="产物校验码")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="发布时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "系统实例"
        verbose_name_plural = verbose_name
        ordering = ["-created_at", "-id"]
        db_table = "sys_instances"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.instance_key:
            self.instance_key = f"inst_{uuid.uuid4().hex[:16]}"
        if not self.runtime_mode:
            self.runtime_mode = self.mode
        if not self.mode:
            self.mode = self.runtime_mode
        super().save(*args, **kwargs)


class GenerationJob(models.Model):
    JOB_TYPE_CHOICES = (
        ("CREATE_SAAS", "创建 SaaS"),
        ("EXPORT_CODE", "导出代码"),
    )
    STATUS_CHOICES = (
        ("PENDING", "待执行"),
        ("RUNNING", "执行中"),
        ("SUCCEEDED", "成功"),
        ("FAILED", "失败"),
    )

    instance = models.ForeignKey(
        SystemInstance,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="generation_jobs",
        verbose_name="实例",
    )
    blueprint_version = models.ForeignKey(
        SystemBlueprintVersion,
        on_delete=models.PROTECT,
        related_name="generation_jobs",
        verbose_name="蓝图版本",
    )
    job_key = models.CharField(max_length=100, unique=True, null=True, blank=True, verbose_name="任务标识")
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES, verbose_name="任务类型")
    job_stage = models.CharField(max_length=50, default="PENDING", verbose_name="任务阶段")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING", verbose_name="状态")
    payload_json = models.JSONField(default=dict, blank=True, verbose_name="输入参数")
    config_snapshot_json = models.JSONField(default=dict, blank=True, verbose_name="配置快照")
    result_json = models.JSONField(default=dict, blank=True, verbose_name="输出结果")
    job_logs_json = models.JSONField(default=list, blank=True, verbose_name="任务日志")
    artifact_path = models.CharField(max_length=500, blank=True, verbose_name="产物路径")
    artifact_name = models.CharField(max_length=255, blank=True, verbose_name="产物名称")
    artifact_size = models.BigIntegerField(default=0, verbose_name="产物大小")
    retry_count = models.PositiveIntegerField(default=0, verbose_name="重试次数")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_generation_jobs",
        verbose_name="发起人",
    )
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    error_message = models.TextField(blank=True, verbose_name="错误信息")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "生成任务"
        verbose_name_plural = verbose_name
        ordering = ["-id"]
        db_table = "sys_generation_jobs"

    def __str__(self):
        instance_name = self.instance.name if self.instance_id else "unbound"
        return f"{instance_name}:{self.job_type}"

    def save(self, *args, **kwargs):
        if not self.job_key:
            self.job_key = f"job_{uuid.uuid4().hex[:16]}"
        super().save(*args, **kwargs)
