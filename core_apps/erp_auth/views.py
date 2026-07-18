from django.utils import timezone
from rest_framework import permissions, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from core_apps.common.permissions import ERPActionPermission, ERPUserOnly
from core_apps.system.operation_log import (
    OperationLogModelViewSetMixin,
    build_operation_log_change,
    collect_serializer_operation_log_changes,
    set_operation_log_changes,
)

from .models import ERPDataPermissionPolicy, ERPDataSpecialGrant, ERPDepartment, ERPPermission, ERPRole, ERPUser
from .authentication import ERPJWTAuthentication
from .serializers import (
    ERPChangePasswordSerializer,
    ERPDepartmentTreeSerializer,
    ERPDepartmentWriteSerializer,
    ERPLoginSerializer,
    ERPPermissionSerializer,
    ERPRoleSerializer,
    ERPUserReferenceSerializer,
    ERPTokenRefreshSerializer,
    ERPUserSerializer,
    ERPUserWriteSerializer,
    ERPDataSpecialGrantSerializer,
)
from .services import ERPUserProvisionService, get_enabled_erp_permission_codes
from core_apps.common.authz import has_erp_super_admin_role
from .tokens import ERPRefreshToken


class ERPPermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ERPPermission.objects.select_related("parent").all()
    serializer_class = ERPPermissionSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["type", "status"]
    permission_map = {
        "list": "system:role:view",
        "retrieve": "system:role:view",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if not isinstance(self.request.user, ERPUser):
            return queryset.none()
        enabled_codes = get_enabled_erp_permission_codes(tenant=self.request.user.tenant)
        return (
            queryset.filter(code__in=enabled_codes, role_editor_visible=True)
            .exclude(code__endswith=":reference")
            .order_by("order", "id")
        )


class ERPDepartmentViewSet(OperationLogModelViewSetMixin, viewsets.ModelViewSet):
    queryset = ERPDepartment.objects.select_related("tenant", "parent").all()
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["status"]
    permission_map = {
        "list": "system:dept:view",
        "retrieve": "system:dept:view",
        "create": "dept:create",
        "update": "dept:update",
        "partial_update": "dept:update",
        "destroy": "dept:delete",
    }

    def get_queryset(self):
        queryset = super().get_queryset().filter(tenant=self.request.user.tenant)
        if self.action == "list":
            return queryset.filter(parent__isnull=True).order_by("order", "id")
        return queryset.order_by("order", "id")

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return ERPDepartmentWriteSerializer
        return ERPDepartmentTreeSerializer

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        child_count = instance.children.count()
        if child_count:
            raise ValidationError(f"该部门下仍有 {child_count} 个子部门，不能删除")
        user_count = instance.users.count()
        if user_count:
            raise ValidationError(f"该部门下仍有 {user_count} 个用户绑定，不能删除")
        return super().destroy(request, *args, **kwargs)


class ERPRoleViewSet(OperationLogModelViewSetMixin, viewsets.ModelViewSet):
    queryset = ERPRole.objects.select_related("tenant").prefetch_related("permissions").all()
    serializer_class = ERPRoleSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["tenant", "status", "is_system"]
    permission_map = {
        "list": "system:role:view",
        "retrieve": "system:role:view",
        "create": "role:create",
        "update": "role:update",
        "partial_update": "role:update",
        "destroy": "role:delete",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if isinstance(self.request.user, ERPUser):
            return queryset.filter(tenant=self.request.user.tenant)
        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system:
            raise ValidationError("系统角色不能删除")
        if instance.users.exists():
            raise ValidationError("当前角色已分配给用户，不能删除")
        return super().destroy(request, *args, **kwargs)


class ERPDataResourceView(APIView):
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    permission_map = {"get": "system:role:view", "put": "role:update"}

    def get(self, request):
        from .data_permissions import DATA_RESOURCES, get_special_options, resolve_permission_type, supported_permission_types

        result = []
        for resource in DATA_RESOURCES:
            permission_type = resolve_permission_type(
                user=request.user, resource_code=resource.code, default_type=resource.default_type
            )
            result.append({
                "code": resource.code,
                "name": resource.name,
                "module": resource.module,
                "default_type": resource.default_type,
                "permission_type": permission_type,
                "supported_types": supported_permission_types(resource),
                "special_options": get_special_options(resource, tenant=request.user.tenant) if permission_type == "SPECIAL" else [],
            })
        return response.Response(result)

    def put(self, request):
        from django.db import transaction
        from .data_permissions import RESOURCE_BY_CODE, VALID_TYPES, supported_permission_types

        items = request.data.get("resources")
        if not isinstance(items, list):
            raise ValidationError({"resources": "请提交数据资源配置列表"})
        seen = set()
        for item in items:
            code = item.get("code") if isinstance(item, dict) else None
            permission_type = item.get("permission_type") if isinstance(item, dict) else None
            if code not in RESOURCE_BY_CODE or permission_type not in VALID_TYPES:
                raise ValidationError({"resources": "包含未知资源或权限类型"})
            if permission_type not in supported_permission_types(RESOURCE_BY_CODE[code]):
                raise ValidationError({"resources": f"{RESOURCE_BY_CODE[code].name}没有业务归属字段，不能配置为业务数据"})
            if code in seen:
                raise ValidationError({"resources": "数据资源不能重复"})
            seen.add(code)
        current_types = {
            policy.resource_code: policy.permission_type
            for policy in ERPDataPermissionPolicy.objects.filter(
                tenant=request.user.tenant,
                resource_code__in=[item["code"] for item in items],
            )
        }
        type_labels = {"BASIC": "租户共享", "BUSINESS": "按业务数据范围", "SPECIAL": "按专项授权"}
        changes = []
        with transaction.atomic():
            for item in items:
                definition = RESOURCE_BY_CODE[item["code"]]
                old_type = current_types.get(item["code"], definition.default_type)
                new_type = item["permission_type"]
                if old_type != new_type:
                    changes.append(build_operation_log_change(
                        "resources",
                        f"{definition.name}：{type_labels.get(old_type, old_type)}",
                        f"{definition.name}：{type_labels.get(new_type, new_type)}",
                    ))
                ERPDataPermissionPolicy.objects.update_or_create(
                    tenant=request.user.tenant,
                    resource_code=item["code"],
                    defaults={"permission_type": item["permission_type"]},
                )
                if item["permission_type"] != "SPECIAL":
                    ERPDataSpecialGrant.objects.filter(
                        tenant=request.user.tenant, resource_code=item["code"]
                    ).delete()
        set_operation_log_changes(request, changes)
        return self.get(request)


class ERPDataSpecialGrantViewSet(viewsets.ModelViewSet):
    serializer_class = ERPDataSpecialGrantSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    http_method_names = ["get", "post", "delete", "head", "options"]
    permission_map = {"list": "system:role:view", "create": "role:update", "destroy": "role:update"}

    def get_queryset(self):
        queryset = ERPDataSpecialGrant.objects.filter(tenant=self.request.user.tenant).select_related(
            "user", "role", "department"
        )
        resource_code = self.request.query_params.get("resource_code")
        return queryset.filter(resource_code=resource_code) if resource_code else queryset


class ERPUserViewSet(OperationLogModelViewSetMixin, viewsets.ModelViewSet):
    queryset = ERPUser.objects.select_related("tenant", "dept").prefetch_related("roles").all()
    serializer_class = ERPUserSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["tenant", "status", "must_change_password"]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    permission_map = {
        "list": "system:user:view",
        "retrieve": "system:user:view",
        "reference_options": "system:user:reference",
        "create": "user:create",
        "update": "user:update",
        "partial_update": "user:update",
        "destroy": "user:delete",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if isinstance(self.request.user, ERPUser):
            return queryset.filter(tenant=self.request.user.tenant)
        return queryset

    def get_serializer_class(self):
        if self.action == "reference_options":
            return ERPUserReferenceSerializer
        if self.action in {"create", "update", "partial_update"}:
            return ERPUserWriteSerializer
        return ERPUserSerializer

    @action(detail=False, methods=["get"], url_path="reference-options")
    def reference_options(self, request):
        queryset = self.get_queryset().filter(status=True).order_by("username", "id")
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.id == request.user.id:
            raise ValidationError("不能删除当前登录用户")
        if instance.roles.filter(is_system=True, data_scope="ALL", status=True).exists():
            raise ValidationError("租户超级管理员不能删除")
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return response.Response(ERPUserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        set_operation_log_changes(request, collect_serializer_operation_log_changes(serializer))
        user = serializer.save()
        return response.Response(ERPUserSerializer(user).data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


class ERPLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ERPLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        if has_erp_super_admin_role(user):
            # Keep existing tenant administrators aligned with newly released ERP permissions.
            ERPUserProvisionService.ensure_super_admin_role(user=user)
        refresh = ERPRefreshToken.for_user(user)
        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at"])
        return response.Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "tenant": {
                    "id": user.tenant.id,
                    "code": user.tenant.code,
                    "name": user.tenant.name,
                },
                "must_change_password": user.must_change_password,
            },
            status=status.HTTP_200_OK,
        )


class ERPTokenRefreshView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ERPTokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return response.Response(serializer.validated_data, status=status.HTTP_200_OK)


class ERPMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [ERPJWTAuthentication]

    def get(self, request):
        user = request.user
        enabled_codes = get_enabled_erp_permission_codes(tenant=user.tenant)
        permissions_qs = user.roles.filter(
            status=True,
            permissions__code__in=enabled_codes,
        ).values_list("permissions__code", flat=True)
        return response.Response(
            {
                "user": ERPUserSerializer(user).data,
                "tenant": {
                    "id": user.tenant.id,
                    "code": user.tenant.code,
                    "name": user.tenant.name,
                },
                "role_codes": list(user.roles.filter(status=True).values_list("code", flat=True)),
                "permissions": sorted(set(code for code in permissions_qs if code)),
                "must_change_password": user.must_change_password,
            }
        )


class ERPChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [ERPJWTAuthentication]

    def post(self, request):
        serializer = ERPChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        return response.Response({"detail": "密码修改成功"}, status=status.HTTP_200_OK)
