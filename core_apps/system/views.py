from rest_framework import mixins, permissions, viewsets

from core_apps.common.permissions import ERPActionPermission, ERPUserOnly
from core_apps.common.viewsets import apply_erp_tenant_scope
from .models import OperationLog
from .serializers import OperationLogSerializer


class OperationLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = OperationLog.objects.all()
    serializer_class = OperationLogSerializer
    permission_classes = [permissions.IsAuthenticated, ERPUserOnly, ERPActionPermission]
    filterset_fields = ["erp_user", "method", "status_code"]
    permission_map = {
        "list": "system:log:view",
        "retrieve": "system:log:view",
    }

    def get_queryset(self):
        queryset = apply_erp_tenant_scope(super().get_queryset(), user=self.request.user)
        path_prefix = self.request.query_params.get("path_prefix")
        if path_prefix:
            queryset = queryset.filter(path__startswith=path_prefix)
        return queryset
