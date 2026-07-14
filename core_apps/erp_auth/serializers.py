from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from .models import ERPDataSpecialGrant, ERPDepartment, ERPPermission, ERPRole, ERPUser
from .services import (
    ERPUserProvisionService,
    expand_permission_ids_with_dependencies,
    generate_erp_role_code,
    get_enabled_erp_permission_codes,
)
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
        if not value.status:
            raise serializers.ValidationError("禁用部门不能作为上级部门")
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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None and self.instance.is_system:
            raise serializers.ValidationError("租户超级管理员角色由系统维护，不能手工修改")
        return attrs

    def create(self, validated_data):
        tenant = self.context["request"].user.tenant
        permission_ids = validated_data.pop("permission_ids", [])
        role = ERPRole.objects.create(
            tenant=tenant,
            code=generate_erp_role_code(tenant_code=tenant.code, role_name=validated_data["name"]),
            **validated_data,
        )
        if permission_ids is not None:
            permission_ids = expand_permission_ids_with_dependencies(tenant=tenant, permission_ids=permission_ids)
            role.permissions.set(ERPPermission.objects.filter(id__in=permission_ids))
        return role

    def update(self, instance, validated_data):
        tenant = self.context["request"].user.tenant
        permission_ids = validated_data.pop("permission_ids", None)
        for field_name, field_value in validated_data.items():
            setattr(instance, field_name, field_value)
        if validated_data:
            instance.save(update_fields=list(validated_data.keys()))
        if permission_ids is not None:
            permission_ids = expand_permission_ids_with_dependencies(tenant=tenant, permission_ids=permission_ids)
            instance.permissions.set(ERPPermission.objects.filter(id__in=permission_ids))
        return instance


class ERPDataSpecialGrantSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.name", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = ERPDataSpecialGrant
        fields = (
            "id", "resource_code", "object_id", "user", "role", "department",
            "user_name", "role_name", "department_name",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        from .data_permissions import RESOURCE_BY_CODE, SPECIAL, get_special_options, resolve_permission_type

        request = self.context["request"]
        tenant = request.user.tenant
        subjects = [attrs.get("user"), attrs.get("role"), attrs.get("department")]
        if sum(subject is not None for subject in subjects) != 1:
            raise serializers.ValidationError("用户、角色、部门必须且只能选择一个")
        for field in ("user", "role", "department"):
            subject = attrs.get(field)
            if subject is not None and subject.tenant_id != tenant.id:
                raise serializers.ValidationError({field: "授权对象不属于当前租户"})
        resource_code = attrs["resource_code"]
        definition = RESOURCE_BY_CODE.get(resource_code)
        if definition is None:
            raise serializers.ValidationError({"resource_code": "未知的数据资源"})
        if resolve_permission_type(user=request.user, resource_code=resource_code, default_type=definition.default_type) != SPECIAL:
            raise serializers.ValidationError({"resource_code": "只有特殊数据可以单独授权"})
        valid_ids = {item["id"] for item in get_special_options(definition, tenant=tenant)}
        if attrs["object_id"] not in valid_ids:
            raise serializers.ValidationError({"object_id": "授权数据不存在或不属于当前租户"})
        duplicate_filter = {
            "tenant": tenant,
            "resource_code": resource_code,
            "object_id": attrs["object_id"],
            "user": attrs.get("user"),
            "role": attrs.get("role"),
            "department": attrs.get("department"),
        }
        if ERPDataSpecialGrant.objects.filter(**duplicate_filter).exists():
            raise serializers.ValidationError("该数据已经授权给此对象")
        return attrs

    def create(self, validated_data):
        return ERPDataSpecialGrant.objects.create(tenant=self.context["request"].user.tenant, **validated_data)


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


class ERPUserReferenceSerializer(serializers.ModelSerializer):
    dept_name = serializers.CharField(source="dept.name", read_only=True)

    class Meta:
        model = ERPUser
        fields = (
            "id",
            "username",
            "name",
            "dept",
            "dept_name",
        )


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
        roles = list(ERPRole.objects.filter(tenant=tenant, id__in=role_ids))
        matched_ids = {role.id for role in roles}
        missing_ids = [role_id for role_id in role_ids if role_id not in matched_ids]
        if missing_ids:
            raise serializers.ValidationError("包含不属于当前租户的角色")
        if any(not role.status for role in roles):
            raise serializers.ValidationError("禁用角色不能分配给用户")
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
        if not department.status:
            raise serializers.ValidationError("禁用部门不能绑定用户")
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
        else:
            from core_apps.tenant.services import TenantService

            runtime_config = TenantService.get_runtime_config(tenant)
            if not runtime_config.is_feature_enabled("system", "role_management", default=True):
                ERPUserProvisionService.ensure_super_admin_role(user=user)
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
            .first()
        )
        if tenant is None:
            raise serializers.ValidationError("租户不存在或已停用")
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


class ERPTokenRefreshSerializer(TokenRefreshSerializer):
    token_class = ERPRefreshToken

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        if refresh.get("user_scope") != "erp":
            raise AuthenticationFailed("Invalid ERP refresh token", code="token_not_valid")

        user_id = refresh.get(api_settings.USER_ID_CLAIM)
        try:
            user = ERPUser.objects.select_related("tenant").get(
                **{api_settings.USER_ID_FIELD: user_id}
            )
        except ERPUser.DoesNotExist as exc:
            raise AuthenticationFailed("ERP user not found", code="user_not_found") from exc

        if not user.status:
            raise AuthenticationFailed("ERP user inactive", code="user_inactive")
        if user.tenant.status != "ACTIVE":
            raise AuthenticationFailed("Tenant inactive", code="tenant_inactive")
        if user.tenant_id != refresh.get("tenant_id"):
            raise AuthenticationFailed("Tenant mismatch", code="tenant_mismatch")

        data = {"access": str(refresh.access_token)}
        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()
            data["refresh"] = str(refresh)
        return data


class ERPChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("当前密码错误")
        return value
