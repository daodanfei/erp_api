from rest_framework import serializers
from django.db.models import OuterRef, Subquery
from django.utils.text import slugify

from core_apps.configuration import validate_blueprint_config
from core_apps.tenant.models import Tenant, TenantConfigSnapshot

from .models import GenerationJob, SystemBlueprint, SystemBlueprintVersion, SystemInstance
from .services import BlueprintService


class BlueprintSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    blueprint_type = serializers.SerializerMethodField()
    bound_tenants = serializers.SerializerMethodField()

    class Meta:
        model = SystemBlueprint
        fields = "__all__"
        read_only_fields = ("created_by", "created_at", "updated_at")
        extra_kwargs = {
            "key": {"required": False, "allow_blank": True},
        }

    def get_blueprint_type(self, obj):
        version = obj.versions.order_by("-created_at", "-id").first()
        if version is None:
            return None
        return version.config_json.get("basic", {}).get("mode")

    def get_bound_tenants(self, obj):
        active_snapshot_blueprint_subquery = TenantConfigSnapshot.objects.filter(
            tenant=OuterRef("pk")
        ).order_by("-applied_at", "-id").values("blueprint_version__blueprint_id")[:1]
        tenants = Tenant.objects.annotate(
            active_blueprint_id=Subquery(active_snapshot_blueprint_subquery)
        ).filter(active_blueprint_id=obj.id).order_by("name", "id")
        return [
            {
                "id": tenant.id,
                "code": tenant.code,
                "name": tenant.name,
            }
            for tenant in tenants
        ]

    def create(self, validated_data):
        created_by = validated_data.pop("created_by", None)
        key = (validated_data.get("key") or "").strip()
        if not key:
            key = self._generate_blueprint_key(validated_data.get("name", ""))
        validated_data["key"] = key
        return SystemBlueprint.objects.create(created_by=created_by, **validated_data)

    def _generate_blueprint_key(self, name: str) -> str:
        max_length = SystemBlueprint._meta.get_field("key").max_length or 100
        base_key = slugify(name or "blueprint", allow_unicode=False).replace("_", "-").strip("-")
        if not base_key:
            base_key = "blueprint"
        base_key = base_key[:max_length].rstrip("-") or "blueprint"
        candidate = base_key
        suffix = 2
        while SystemBlueprint.objects.filter(key=candidate).exists():
            suffix_text = f"-{suffix}"
            trimmed_base = base_key[: max_length - len(suffix_text)].rstrip("-")
            candidate = f"{trimmed_base}{suffix_text}" if trimmed_base else f"blueprint{suffix_text}"
            suffix += 1
        return candidate


class BlueprintVersionSerializer(serializers.ModelSerializer):
    version = serializers.CharField(required=False, allow_blank=True)
    blueprint_name = serializers.CharField(source="blueprint.name", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = SystemBlueprintVersion
        fields = "__all__"
        read_only_fields = ("created_by", "created_at")
        validators = []

    def validate_config_json(self, value):
        return validate_blueprint_config(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        blueprint = attrs.get("blueprint", getattr(self.instance, "blueprint", None))
        version = attrs.get("version")
        if version and blueprint:
            queryset = SystemBlueprintVersion.objects.filter(blueprint=blueprint, version=version)
            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError("同一蓝图下版本号不能重复")
        return attrs

    def create(self, validated_data):
        return BlueprintService.create_version(
            blueprint=validated_data["blueprint"],
            created_by=self.context["request"].user,
            config_json=validated_data["config_json"],
            version=validated_data.get("version") or None,
            change_note=validated_data.get("change_note", ""),
            is_published=validated_data.get("is_published", False),
        )

    def update(self, instance, validated_data):
        for field in ("config_json", "change_note", "version", "is_published"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        if "config_json" in validated_data:
            instance.config_json = validate_blueprint_config(validated_data["config_json"])
        instance.save()
        if instance.is_published:
            BlueprintService.publish_version(instance)
        return instance


class SystemInstanceSerializer(serializers.ModelSerializer):
    blueprint_name = serializers.CharField(source="blueprint.name", read_only=True)
    blueprint_version_name = serializers.CharField(source="blueprint_version.version", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_count = serializers.IntegerField(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    current_generation_job_key = serializers.CharField(source="current_generation_job.job_key", read_only=True)

    class Meta:
        model = SystemInstance
        fields = "__all__"
        read_only_fields = ("created_by", "created_at", "instance_key", "current_generation_job", "published_at")

    def validate(self, attrs):
        blueprint = attrs.get("blueprint", getattr(self.instance, "blueprint", None))
        blueprint_version = attrs.get("blueprint_version", getattr(self.instance, "blueprint_version", None))
        if blueprint and blueprint_version and blueprint_version.blueprint_id != blueprint.id:
            raise serializers.ValidationError("blueprint_version 必须属于 blueprint")
        tenant = attrs.get("tenant", getattr(self.instance, "tenant", None))
        if tenant is not None and not isinstance(tenant, Tenant):
            raise serializers.ValidationError("tenant 不合法")
        return attrs


class GenerationJobSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)
    instance_key = serializers.CharField(source="instance.instance_key", read_only=True)

    class Meta:
        model = GenerationJob
        fields = "__all__"
        read_only_fields = ("job_key", "created_at")

    def validate(self, attrs):
        instance = attrs.get("instance", getattr(self.instance, "instance", None))
        blueprint_version = attrs.get("blueprint_version", getattr(self.instance, "blueprint_version", None))
        if instance and blueprint_version and instance.blueprint_version_id != blueprint_version.id:
            raise serializers.ValidationError("任务版本必须与实例版本一致")
        return attrs
