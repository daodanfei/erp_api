from django.http import FileResponse, Http404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, permissions, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView

from core_apps.blueprints.models import SystemBlueprintVersion
from core_apps.blueprints.serializers import SystemInstanceSerializer
from core_apps.common.permissions import PlatformUserOnly
from core_apps.tenant.models import Tenant
from core_apps.tenant.serializers import TenantConfigSnapshotSerializer, TenantModuleStateSerializer, TenantSerializer
from .selectors import get_generation_job_queryset, get_system_instance_queryset
from .serializers import GenerationPlanPreviewSerializer, GenerationRequestSerializer
from .services import GenerationService


class GenerationJobViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = get_generation_job_queryset()
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    serializer_class = GenerationRequestSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        data = [GenerationService.get_generation_result(generation_job=job) for job in queryset]
        return response.Response(data)

    def retrieve(self, request, *args, **kwargs):
        job = self.get_object()
        return response.Response(GenerationService.get_generation_result(generation_job=job))

    @action(detail=False, methods=["get"], url_path="plan-preview")
    def plan_preview(self, request):
        serializer = GenerationPlanPreviewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        plan = GenerationService.preview_plan(
            blueprint_version=serializer.validated_data["blueprint_version"],
            runtime_mode=serializer.validated_data["runtime_mode"],
        )
        return response.Response(plan.to_dict())

    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request, pk=None):
        job = self.get_object()
        tenant = Tenant.objects.filter(pk=request.data.get("tenant"), status="ACTIVE").first() if request.data.get("tenant") else None
        result = GenerationService.retry_generation_job(
            source_job=job,
            requested_by=request.user,
            instance_name=request.data.get("instance_name", job.instance.name if job.instance_id else ""),
            tenant=tenant,
            tenant_name=request.data.get("tenant_name", (job.payload_json or {}).get("tenant_name", "")),
            industry=request.data.get("industry", (job.payload_json or {}).get("industry", "")),
        )
        return response.Response(result.to_dict(), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="audit")
    def audit(self, request, pk=None):
        return response.Response(GenerationService.get_generation_result(generation_job=self.get_object()))

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        job = self.get_object()
        artifact_path = job.artifact_path or job.instance.artifact_path
        if not artifact_path:
            raise Http404("当前任务没有可下载产物")
        try:
            handle = open(artifact_path, "rb")
        except FileNotFoundError as exc:
            raise Http404("产物不存在或已被清理") from exc
        return FileResponse(handle, as_attachment=True, filename=job.artifact_name or "generation-artifact.zip")


class SystemInstanceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = get_system_instance_queryset()
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]
    serializer_class = SystemInstanceSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "runtime_mode", "blueprint", "blueprint_version", "tenant", "tenants"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return response.Response(GenerationService.get_instance_result(instance=instance))

    @action(detail=True, methods=["post"], url_path="reapply-version")
    def reapply_version(self, request, pk=None):
        instance = self.get_object()
        blueprint_version = SystemBlueprintVersion.objects.select_related("blueprint").get(
            pk=request.data["blueprint_version"]
        )
        result = GenerationService.reapply_blueprint_version(
            instance=instance,
            blueprint_version=blueprint_version,
            requested_by=request.user,
        )
        return response.Response(result.to_dict(), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        instance = GenerationService.update_instance_status(instance=self.get_object(), status_value="INACTIVE")
        return response.Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        instance = GenerationService.update_instance_status(instance=self.get_object(), status_value="ACTIVE")
        return response.Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        instance = GenerationService.update_instance_status(instance=self.get_object(), status_value="ARCHIVED")
        return response.Response(self.get_serializer(instance).data)


class CreateSaasGenerationView(APIView):
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def post(self, request):
        serializer = GenerationRequestSerializer(data={**request.data, "runtime_mode": "SAAS"})
        serializer.is_valid(raise_exception=True)
        result = GenerationService.create_saas_instance_from_version(
            blueprint_version=serializer.validated_data["blueprint_version"],
            requested_by=request.user,
            instance_name=serializer.validated_data.get("instance_name", ""),
            tenant=serializer.validated_data.get("tenant"),
            tenant_name=serializer.validated_data.get("tenant_name", ""),
            industry=serializer.validated_data.get("industry", ""),
        )
        tenant = result.instance.tenant
        snapshot = tenant.active_config_snapshot if tenant is not None else None
        module_states = tenant.module_states.order_by("module_key") if tenant is not None else []
        payload = result.to_dict()
        payload.update(
            {
                "tenant": TenantSerializer(tenant).data if tenant is not None else None,
                "snapshot": TenantConfigSnapshotSerializer(snapshot).data if snapshot is not None else None,
                "module_states": TenantModuleStateSerializer(module_states, many=True).data,
            }
        )
        return response.Response(payload, status=status.HTTP_201_CREATED)


class ExportCodeGenerationView(APIView):
    permission_classes = [permissions.IsAuthenticated, PlatformUserOnly]

    def post(self, request):
        serializer = GenerationRequestSerializer(data={**request.data, "runtime_mode": "CODE_EXPORT"})
        serializer.is_valid(raise_exception=True)
        result = GenerationService.export_code_from_version(
            blueprint_version=serializer.validated_data["blueprint_version"],
            requested_by=request.user,
            instance_name=serializer.validated_data.get("instance_name", ""),
        )
        return response.Response(result.to_dict(), status=status.HTTP_201_CREATED)
