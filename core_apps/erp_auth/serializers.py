from rest_framework import serializers

from .models import ERPDepartment, ERPPermission, ERPRole, ERPUser
from .services import ERPUserProvisionService, generate_erp_role_code, get_enabled_erp_permission_codes
from .tokens import ERPRefreshToken


class ERPPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ERPPermission
        fields = "__all__"


class ERPDepartmentTreeSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = ERPDepartment
        fields = "__all__"

    def get_children(self, obj):
        queryset = obj.children.order_by("order", "id")
        return ERPDepartmentTreeSerializer(queryset, many=True).data


class ERPDepartmentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ERPDepartment
        fields = (
            "id",
            "parent",
            "name",
            "leader",
            "phone",
            "email",
            "order",
            "status",
        )

    def validate_parent(self, value):
        if value is None:
            return value
        tenant = self.context["request"].user.tenant
        if value.tenant_id != tenant.id:
            raise serializers.ValidationError("上级部门不属于当前租户")
        instance = getattr(self, "instance", None)
        if instance is not None and value.id == instance.id:
            raise serializers.ValidationError("上级部门不能选择自己")
        current = value
        while current is not None:
            if instance is not None and current.id == instance.id:
                raise serializers.ValidationError("不能形成部门循环关系")
            current = current.parent
        return value


class ERPRoleSerializer(serializers.ModelSerializer):
    permissions = ERPPermissionSerializer(many=True, read_only=True)
    permission_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    class Meta:
        model = ERPRole
        fields = (
            "id",
            "tenant",
            "name",
            "code",
            "data_scope",
            "status",
            "is_system",
            "permissions",
            "permission_ids",
        )
        read_only_fields = ("id", "tenant", "code", "is_system", "permissions")

    def validate_permission_ids(self, value):
        tenant = self.context["request"].user.tenant
        permission_ids = list(dict.fromkeys(value))
        if not permission_ids:
            return permission_ids
        enabled_codes = get_enabled_erp_permission_codes(tenant=tenant)
        permissions = list(ERPPermission.objects.filter(id__in=permission_ids))
        matched_ids = {permission.id for permission in permissions}
        missing_ids = [permission_id for permission_id in permission_ids if permission_id not in matched_ids]
        if missing_ids:
            raise serializers.ValidationError("包含不存在的权限")
        invalid_permissions = [
            permission.code for permission in permissions if permission.code not in enabled_codes
        ]
        if invalid_permissions:
            raise serializers.ValidationError("包含当前租户未启用的权限")
        return permission_ids

    def create(self, validated_data):
        tenant = self.context["request"].user.tenant
        permission_ids = validated_data.pop("permission_ids", [])
        role = ERPRole.objects.create(
            tenant=tenant,
            code=generate_erp_role_code(tenant_code=tenant.code, role_name=validated_data["name"]),
            **validated_data,
        )
        if permission_ids is not None:
            role.permissions.set(ERPPermission.objects.filter(id__in=permission_ids))
        return role

    def update(self, instance, validated_data):
        permission_ids = validated_data.pop("permission_ids", None)
        for field_name, field_value in validated_data.items():
            setattr(instance, field_name, field_value)
        if validated_data:
            instance.save(update_fields=list(validated_data.keys()))
        if permission_ids is not None:
            instance.permissions.set(ERPPermission.objects.filter(id__in=permission_ids))
        return instance


class ERPUserSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    dept_name = serializers.CharField(source="dept.name", read_only=True)
    role_names = serializers.SerializerMethodField()
    role_ids = serializers.SerializerMethodField()

    class Meta:
        model = ERPUser
        fields = (
            "id",
            "tenant",
            "tenant_name",
            "dept",
            "dept_name",
            "username",
            "name",
            "phone",
            "email",
            "status",
            "is_super_admin",
            "must_change_password",
            "last_login_at",
            "role_names",
            "role_ids",
            "created_at",
            "updated_at",
        )

    def get_role_names(self, obj):
        return [role.name for role in obj.roles.all()]

    def get_role_ids(self, obj):
        return list(obj.roles.values_list("id", flat=True))


class ERPUserWriteSerializer(serializers.ModelSerializer):
    dept = serializers.IntegerField(required=False, allow_null=True)
    role_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    password = serializers.CharField(min_length=8, required=False, allow_blank=False, write_only=True)

    class Meta:
        model = ERPUser
        fields = (
            "username",
            "dept",
            "name",
            "phone",
            "email",
            "status",
            "is_super_admin",
            "password",
            "role_ids",
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "创建用户时必须设置密码"})
        return attrs

    def validate_role_ids(self, value):
        tenant = self.context["request"].user.tenant
        role_ids = list(dict.fromkeys(value))
        if not role_ids:
            return role_ids
        matched_ids = set(
            ERPRole.objects.filter(tenant=tenant, id__in=role_ids).values_list("id", flat=True)
        )
        missing_ids = [role_id for role_id in role_ids if role_id not in matched_ids]
        if missing_ids:
            raise serializers.ValidationError("包含不属于当前租户的角色")
        return role_ids

    def validate_username(self, value):
        tenant = self.context["request"].user.tenant
        queryset = ERPUser.objects.filter(tenant=tenant, username=value.strip())
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("用户名已存在")
        return value.strip()

    def validate_dept(self, value):
        if value is None:
            return None
        tenant = self.context["request"].user.tenant
        department = ERPDepartment.objects.filter(tenant=tenant, id=value).first()
        if department is None:
            raise serializers.ValidationError("部门不存在或不属于当前租户")
        return department

    def create(self, validated_data):
        request = self.context["request"]
        tenant = request.user.tenant
        role_ids = validated_data.pop("role_ids", [])
        password = validated_data.pop("password")
        ERPUserProvisionService.ensure_tenant_user_capacity(tenant=tenant)
        user = ERPUser.objects.create_user(
            tenant=tenant,
            password=password,
            must_change_password=True,
            **validated_data,
        )
        if role_ids:
            user.roles.set(ERPRole.objects.filter(tenant=tenant, id__in=role_ids))
        return user

    def update(self, instance, validated_data):
        tenant = self.context["request"].user.tenant
        role_ids = validated_data.pop("role_ids", None)
        password = validated_data.pop("password", None)
        for field_name, field_value in validated_data.items():
            setattr(instance, field_name, field_value)
        update_fields = list(validated_data.keys())
        if password:
            instance.set_password(password)
            instance.must_change_password = True
            update_fields.extend(["password", "must_change_password"])
        if update_fields:
            instance.save(update_fields=update_fields)
        if role_ids is not None:
            instance.roles.set(ERPRole.objects.filter(tenant=tenant, id__in=role_ids))
        return instance


class ERPLoginSerializer(serializers.Serializer):
    tenant_code = serializers.CharField(max_length=100)
    username = serializers.CharField(max_length=150)
    password = serializers.CharField()

    def validate(self, attrs):
        from core_apps.tenant.models import Tenant

        tenant = (
            Tenant.objects.filter(code=attrs["tenant_code"], status="ACTIVE")
            .select_related("instance")
            .first()
        )
        if tenant is None:
            raise serializers.ValidationError("租户不存在或已停用")
        if tenant.instance_id is None:
            raise serializers.ValidationError("当前租户尚未绑定实例")
        user = (
            ERPUser.objects.select_related("tenant")
            .prefetch_related("roles")
            .filter(tenant=tenant, username=attrs["username"], status=True)
            .first()
        )
        if user is None or not user.check_password(attrs["password"]):
            raise serializers.ValidationError("用户名或密码错误")
        attrs["tenant"] = tenant
        attrs["user"] = user
        return attrs


class ERPTokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs):
        refresh = ERPRefreshToken(attrs["refresh"])
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


class ERPChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("当前密码错误")
        return value
