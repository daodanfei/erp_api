from rest_framework import serializers

from .models import Tenant, TenantConfigSnapshot, TenantModuleState, TenantUser


class TenantSerializer(serializers.ModelSerializer):
    instance_name = serializers.CharField(source="instance.name", read_only=True)
    user_count = serializers.SerializerMethodField()
    remaining_user_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = "__all__"
        read_only_fields = ("created_at",)

    def get_user_count(self, obj):
        return getattr(obj, "erp_user_count", None) or obj.erp_users.count()

    def get_remaining_user_count(self, obj):
        if obj.user_limit is None:
            return None
        user_count = getattr(obj, "erp_user_count", None)
        if user_count is None:
            user_count = obj.erp_users.count()
        return max(obj.user_limit - user_count, 0)


class TenantUserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = TenantUser
        fields = "__all__"
        read_only_fields = ("created_at",)


class TenantModuleStateSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = TenantModuleState
        fields = "__all__"


class TenantConfigSnapshotSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    blueprint_version_name = serializers.CharField(source="blueprint_version.version", read_only=True)

    class Meta:
        model = TenantConfigSnapshot
        fields = "__all__"
        read_only_fields = ("applied_at",)
