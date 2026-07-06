from rest_framework import mixins, permissions, viewsets

from core_apps.common.permissions import PlatformUserOnly
from .models import OperationLog
from .serializers import OperationLogSerializer


class OperationLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = OperationLog.objects.all()
    serializer_class = OperationLogSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["user", "method", "status_code"]

    def get_queryset(self):
        queryset = super().get_queryset()
        path_prefix = self.request.query_params.get("path_prefix")
        if path_prefix:
            queryset = queryset.filter(path__startswith=path_prefix)
        return queryset
