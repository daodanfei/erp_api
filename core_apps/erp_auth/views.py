from django.utils import timezone
from rest_framework import permissions, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from core_apps.common.permissions import ERPActionPermission, ERPUserOnly

from .models import ERPDepartment, ERPPermission, ERPRole, ERPUser
from .authentication import ERPJWTAuthentication
from .serializers import (
    ERPChangePasswordSerializer,
    ERPDepartmentTreeSerializer,
    ERPDepartmentWriteSerializer,
    ERPLoginSerializer,
    ERPPermissionSerializer,
    ERPRoleSerializer,
    ERPTokenRefreshSerializer,
    ERPUserSerializer,
    ERPUserWriteSerializer,
)
from .services import get_enabled_erp_permission_codes
from .tokens import ERPRefreshToken


class ERPPermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ERPPermission.objects.select_related("parent").all()
    serializer_class = ERPPermissionSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["type", "status"]
    permission_map = {
        "list": "system:role",
        "retrieve": "system:role",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if not isinstance(self.request.user, ERPUser):
            return queryset.none()
        enabled_codes = get_enabled_erp_permission_codes(tenant=self.request.user.tenant)
        return queryset.filter(code__in=enabled_codes).order_by("order", "id")


class ERPDepartmentViewSet(viewsets.ModelViewSet):
    queryset = ERPDepartment.objects.select_related("tenant", "parent").all()
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["status"]
    permission_map = {
        "list": "system:dept",
        "retrieve": "system:dept",
        "create": "system:dept",
        "update": "system:dept",
        "partial_update": "system:dept",
        "destroy": "system:dept",
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


class ERPRoleViewSet(viewsets.ModelViewSet):
    queryset = ERPRole.objects.select_related("tenant").prefetch_related("permissions").all()
    serializer_class = ERPRoleSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["tenant", "status", "is_system"]
    permission_map = {
        "list": "system:role",
        "retrieve": "system:role",
        "create": "system:role",
        "update": "system:role",
        "partial_update": "system:role",
        "destroy": "system:role",
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
        return super().destroy(request, *args, **kwargs)


class ERPUserViewSet(viewsets.ModelViewSet):
    queryset = ERPUser.objects.select_related("tenant", "dept").prefetch_related("roles").all()
    serializer_class = ERPUserSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["tenant", "status", "is_super_admin", "must_change_password"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    permission_map = {
        "list": "system:user",
        "retrieve": "system:user",
        "create": "user:create",
        "update": "user:update",
        "partial_update": "user:update",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if isinstance(self.request.user, ERPUser):
            return queryset.filter(tenant=self.request.user.tenant)
        return queryset

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return ERPUserWriteSerializer
        return ERPUserSerializer

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
                    "instance_id": user.tenant.instance_id,
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
