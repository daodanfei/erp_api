from rest_framework import serializers

from core_apps.blueprints.models import GenerationJob, SystemBlueprintVersion
from core_apps.blueprints.serializers import GenerationJobSerializer, SystemInstanceSerializer
from core_apps.tenant.models import Tenant

from .planners import build_generation_plan, resolve_runtime_mode
from .validators import validate_blueprint_version_for_generation


class GenerationRequestSerializer(serializers.Serializer):
    blueprint_version = serializers.PrimaryKeyRelatedField(queryset=SystemBlueprintVersion.objects.select_related("blueprint"))
    runtime_mode = serializers.ChoiceField(choices=("SAAS", "CODE_EXPORT"), required=False)
    instance_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.filter(status="ACTIVE"), required=False)
    tenant_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    industry = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, attrs):
        validation = validate_blueprint_version_for_generation(
            blueprint_version=attrs["blueprint_version"],
            runtime_mode=attrs.get("runtime_mode"),
        )
        attrs["runtime_mode"] = validation.runtime_mode
        if attrs["runtime_mode"] == "SAAS":
            if attrs.get("tenant") is None and not attrs.get("tenant_name"):
                raise serializers.ValidationError("SAAS 模式必须选择租户或提供 tenant_name")
        attrs["normalized_config"] = validation.normalized_config
        attrs["generation_plan"] = build_generation_plan(attrs["blueprint_version"], runtime_mode=attrs["runtime_mode"])
        return attrs


class GenerationPlanPreviewSerializer(serializers.Serializer):
    blueprint_version = serializers.PrimaryKeyRelatedField(queryset=SystemBlueprintVersion.objects.select_related("blueprint"))
    runtime_mode = serializers.ChoiceField(choices=("SAAS", "CODE_EXPORT"), required=False)

    def validate(self, attrs):
        validation = validate_blueprint_version_for_generation(
            blueprint_version=attrs["blueprint_version"],
            runtime_mode=attrs.get("runtime_mode"),
            require_published=False,
        )
        attrs["normalized_config"] = validation.normalized_config
        attrs["runtime_mode"] = validation.runtime_mode or resolve_runtime_mode(validation.normalized_config)
        return attrs


class GenerationJobAuditSerializer(serializers.Serializer):
    job = GenerationJobSerializer()
    instance = SystemInstanceSerializer(allow_null=True)
    tenant = serializers.DictField(required=False, allow_null=True)
    plan = serializers.DictField()
