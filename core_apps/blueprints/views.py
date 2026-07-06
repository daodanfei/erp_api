from rest_framework import decorators, permissions, response, status, viewsets

from core_apps.common.permissions import PlatformUserOnly

from .models import SystemBlueprint, SystemBlueprintVersion
from .serializers import BlueprintSerializer, BlueprintVersionSerializer
from .services import BlueprintService


class BlueprintViewSet(viewsets.ModelViewSet):
    queryset = SystemBlueprint.objects.all()
    serializer_class = BlueprintSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["key", "status", "industry"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class BlueprintVersionViewSet(viewsets.ModelViewSet):
    queryset = SystemBlueprintVersion.objects.select_related("blueprint", "created_by").all()
    serializer_class = BlueprintVersionSerializer
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    filterset_fields = ["blueprint", "is_published", "version"]

    @decorators.action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, pk=None):
        version = self.get_object()
        BlueprintService.publish_version(version)
        return response.Response(self.get_serializer(version).data)

    @decorators.action(detail=True, methods=["post"], url_path="clone")
    def clone(self, request, pk=None):
        source = self.get_object()
        version = BlueprintService.clone_version(
            source_version=source,
            created_by=request.user,
            version=request.data.get("version"),
            change_note=request.data.get("change_note", ""),
        )
        serializer = self.get_serializer(version)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)
