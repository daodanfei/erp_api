from rest_framework import viewsets, permissions
from core_apps.common.permissions import PlatformUserOnly
from .models import Department
from .serializers import DepartmentSerializer, DepartmentTreeSerializer

class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all().order_by('order')
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def get_queryset(self):
        queryset = Department.objects.all().order_by("order", "id")
        if self.action == "list":
            return queryset.filter(parent__isnull=True)
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return DepartmentTreeSerializer
        return DepartmentSerializer
