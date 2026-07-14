from rest_framework import decorators, permissions, response, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from core_apps.blueprints.models import SystemBlueprintVersion, SystemInstance
from core_apps.common.permissions import PlatformUserOnly
from core_apps.erp_auth.authentication import ERPJWTAuthentication
from core_apps.erp_auth.models import ERPUser
from core_apps.erp_auth.services import ERPUserProvisionService
from core_apps.policies.registry import get_runtime_config_for_user

from .models import Tenant, TenantConfigSnapshot, TenantModuleState, TenantUser
from .serializers import (
    TenantConfigSnapshotSerializer,
    TenantModuleStateSerializer,
    TenantSerializer,
    TenantUserSerializer,
)
from .services import TenantService, resolve_user_tenant


class TenantViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.all()
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["code", "status", "industry"]

    def create(self, request, *args, **kwargs):
        try:
            tenant = TenantService.create_tenant(
                code=request.data.get("code", ""),
                name=request.data["name"],
                industry=request.data.get("industry", ""),
                owner=request.user,
                user_limit=request.data.get("user_limit"),
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        serializer = self.get_serializer(tenant)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["post"], url_path="apply-version")
    def apply_version(self, request, pk=None):
        tenant = self.get_object()
        blueprint_version = get_object_or_404(SystemBlueprintVersion, pk=request.data["blueprint_version"])
        try:
            snapshot = TenantService.apply_blueprint_version(tenant=tenant, blueprint_version=blueprint_version)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        serializer = TenantConfigSnapshotSerializer(snapshot)
        return response.Response(serializer.data)

    @decorators.action(detail=False, methods=["post"], url_path="create-from-version")
    def create_from_version(self, request):
        blueprint_version = get_object_or_404(SystemBlueprintVersion, pk=request.data["blueprint_version"])
        try:
            tenant = TenantService.create_from_blueprint_version(
                code=request.data.get("code", ""),
                name=request.data["name"],
                blueprint_version=blueprint_version,
                industry=request.data.get("industry", ""),
                owner=request.user,
                user_limit=request.data.get("user_limit"),
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        serializer = self.get_serializer(tenant)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["post"], url_path="bind-instance")
    def bind_instance(self, request, pk=None):
        tenant = self.get_object()
        instance = get_object_or_404(SystemInstance.objects.select_related("blueprint_version"), pk=request.data["instance"])
        blueprint_version = None
        if request.data.get("blueprint_version"):
            blueprint_version = get_object_or_404(SystemBlueprintVersion, pk=request.data["blueprint_version"])
        try:
            result = TenantService.bind_instance_to_tenant(
                tenant=tenant,
                instance=instance,
                blueprint_version=blueprint_version,
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return response.Response(
            {
                "tenant": self.get_serializer(result.tenant).data,
                "instance": None,
                "snapshot": (
                    TenantConfigSnapshotSerializer(result.snapshot).data
                    if result.snapshot is not None
                    else None
                ),
                "initial_admin": {
                    "user_id": result.initial_admin.user.id,
                    "username": result.initial_admin.user.username,
                    "initial_password": result.initial_admin.initial_password,
                    "created": result.initial_admin.created,
                },
            }
        )

    @decorators.action(detail=True, methods=["get"], url_path="initial-admin")
    def initial_admin(self, request, pk=None):
        tenant = self.get_object()
        user = ERPUserProvisionService.get_tenant_super_admin(tenant=tenant)
        if user is None:
            return response.Response(
                {
                    "exists": False,
                    "user": None,
                }
            )
        return response.Response(
            {
                "exists": True,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "status": user.status,
                    "must_change_password": user.must_change_password,
                    "role_names": list(user.roles.values_list("name", flat=True)),
                },
            }
        )

    @decorators.action(detail=True, methods=["post"], url_path="reset-initial-admin-password")
    def reset_initial_admin_password(self, request, pk=None):
        tenant = self.get_object()
        provision_result = ERPUserProvisionService.ensure_tenant_super_admin(tenant=tenant)
        user = provision_result.user
        initial_password = provision_result.initial_password
        created = provision_result.created
        if not created:
            initial_password = ERPUserProvisionService.reset_password(user=user)
        return response.Response(
            {
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "status": user.status,
                    "must_change_password": user.must_change_password,
                    "role_names": list(user.roles.values_list("name", flat=True)),
                },
                "initial_password": initial_password,
                "created": created,
            }
        )

    @decorators.action(detail=True, methods=["post"], url_path="refresh-super-admin-permissions")
    def refresh_super_admin_permissions(self, request, pk=None):
        tenant = self.get_object()
        provision_result = ERPUserProvisionService.ensure_tenant_super_admin(tenant=tenant)
        role = provision_result.role
        permission_count = role.permissions.count()
        return response.Response(
            {
                "tenant": self.get_serializer(tenant).data,
                "user": {
                    "id": provision_result.user.id,
                    "username": provision_result.user.username,
                    "name": provision_result.user.name,
                    "status": provision_result.user.status,
                    "must_change_password": provision_result.user.must_change_password,
                },
                "role": {
                    "id": role.id,
                    "name": role.name,
                    "code": role.code,
                    "permission_count": permission_count,
                },
                "created": provision_result.created,
            }
        )

    @decorators.action(detail=True, methods=["post"], url_path="clear-data")
    def clear_data(self, request, pk=None):
        tenant = self.get_object()
        confirm_code = str(request.data.get("confirm_code", "")).strip()
        if confirm_code != tenant.code:
            raise ValidationError({"detail": "请输入正确的租户编码以确认清空操作"})
        result = TenantService.clear_tenant_data(tenant=tenant)
        return response.Response(result, status=status.HTTP_200_OK)


class TenantUserViewSet(viewsets.ModelViewSet):
    queryset = TenantUser.objects.select_related("tenant", "user").all()
    serializer_class = TenantUserSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["tenant", "user", "is_owner", "is_default"]


class TenantModuleStateViewSet(viewsets.ModelViewSet):
    queryset = TenantModuleState.objects.select_related("tenant").all()
    serializer_class = TenantModuleStateSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["tenant", "module_key", "enabled"]


class TenantConfigSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TenantConfigSnapshot.objects.select_related("tenant", "blueprint_version").all()
    serializer_class = TenantConfigSnapshotSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["tenant", "blueprint_version"]


class RuntimeConfigView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [ERPJWTAuthentication, JWTAuthentication]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if isinstance(request.user, ERPUser):
            tenant = request.user.tenant
        elif tenant is None and request.user.is_authenticated:
            tenant = resolve_user_tenant(request.user, tenant_code=request.META.get("HTTP_X_TENANT_CODE"))
        runtime_config = TenantService.get_runtime_config(tenant) if tenant is not None else get_runtime_config_for_user(request.user)
        snapshot = tenant.active_config_snapshot if tenant is not None else None
        blueprint_version = snapshot.blueprint_version if snapshot is not None else None
        blueprint = blueprint_version.blueprint if blueprint_version is not None else None
        return response.Response(
            {
                "tenant": (
                    {"id": tenant.id, "code": tenant.code, "name": tenant.name}
                    if tenant is not None
                    else None
                ),
                "instance": None,
                "blueprint": (
                    {"id": blueprint.id, "key": blueprint.key, "name": blueprint.name}
                    if blueprint is not None
                    else None
                ),
                "blueprint_version": (
                    {
                        "id": blueprint_version.id,
                        "version": blueprint_version.version,
                        "published_at": snapshot.applied_at if snapshot is not None else None,
                    }
                    if blueprint_version is not None
                    else None
                ),
                "config_json": runtime_config.config_json,
                "enabled_modules": runtime_config.enabled_modules(),
            }
        )
