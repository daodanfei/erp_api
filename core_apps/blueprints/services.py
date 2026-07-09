from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core_apps.configuration import validate_blueprint_config
from core_apps.generation.validators import validate_blueprint_version_for_generation
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantModuleState
from core_apps.tenant.services import TenantService

from .models import GenerationJob, SystemBlueprint, SystemBlueprintVersion, SystemInstance


def get_next_blueprint_version(blueprint: SystemBlueprint) -> str:
    last_version = blueprint.versions.order_by("-id").values_list("version", flat=True).first()
    if not last_version:
        return "v1"
    if last_version.startswith("v") and last_version[1:].isdigit():
        return f"v{int(last_version[1:]) + 1}"
    return f"{last_version}.1"


@transaction.atomic
def publish_blueprint_version(version: SystemBlueprintVersion) -> SystemBlueprintVersion:
    validate_blueprint_version_for_generation(
        blueprint_version=version,
        require_published=False,
    )
    SystemBlueprintVersion.objects.filter(blueprint=version.blueprint, is_published=True).exclude(
        pk=version.pk
    ).update(is_published=False)
    version.is_published = True
    version.save(update_fields=["is_published"])
    return version


@dataclass(frozen=True, slots=True)
class SaasInstanceCreationResult:
    tenant: Tenant
    instance: SystemInstance | None
    generation_job: GenerationJob
    snapshot: TenantConfigSnapshot
    module_states: tuple[TenantModuleState, ...]


class GenerationJobService:
    @staticmethod
    def create_job(
        *,
        instance: SystemInstance | None,
        blueprint_version: SystemBlueprintVersion,
        job_type: str,
        status: str = "PENDING",
        payload_json: dict | None = None,
        config_snapshot_json: dict | None = None,
        result_json: dict | None = None,
        job_stage: str = "PENDING",
        job_logs_json: list | None = None,
        artifact_path: str = "",
        artifact_name: str = "",
        artifact_size: int = 0,
        retry_count: int = 0,
        requested_by=None,
        started_at=None,
        finished_at=None,
        error_message: str = "",
    ) -> GenerationJob:
        job = GenerationJob.objects.create(
            instance=instance,
            blueprint_version=blueprint_version,
            job_type=job_type,
            status=status,
            job_stage=job_stage,
            payload_json=payload_json or {},
            config_snapshot_json=config_snapshot_json or blueprint_version.config_json or {},
            result_json=result_json or {},
            job_logs_json=job_logs_json or [],
            artifact_path=artifact_path,
            artifact_name=artifact_name,
            artifact_size=artifact_size,
            retry_count=retry_count,
            requested_by=requested_by,
            started_at=started_at,
            finished_at=finished_at,
            error_message=error_message,
        )
        if instance is not None and instance.current_generation_job_id != job.id:
            instance.current_generation_job = job
            instance.save(update_fields=["current_generation_job"])
        return job

    @staticmethod
    def attach_instance(job: GenerationJob, *, instance: SystemInstance) -> GenerationJob:
        job.instance = instance
        job.save(update_fields=["instance"])
        if instance.current_generation_job_id != job.id:
            instance.current_generation_job = job
            instance.save(update_fields=["current_generation_job"])
        return job

    @staticmethod
    def append_log(job: GenerationJob, *, stage: str, message: str, level: str = "INFO", extra: dict | None = None) -> GenerationJob:
        logs = list(job.job_logs_json or [])
        logs.append(
            {
                "timestamp": timezone.now().isoformat(),
                "level": level,
                "stage": stage,
                "message": message,
                "extra": extra or {},
            }
        )
        job.job_logs_json = logs
        job.job_stage = stage
        job.save(update_fields=["job_logs_json", "job_stage"])
        return job

    @staticmethod
    def mark_failed(job: GenerationJob, *, stage: str = "FAILED", error_message: str = "") -> GenerationJob:
        finished_at = timezone.now()
        job.status = "FAILED"
        job.job_stage = stage
        job.finished_at = finished_at
        job.error_message = error_message
        if job.started_at is None:
            job.started_at = finished_at
        job.save(update_fields=["status", "job_stage", "started_at", "finished_at", "error_message"])
        return job

    @staticmethod
    def mark_succeeded(
        job: GenerationJob,
        *,
        result_json: dict | None = None,
        job_stage: str = "COMPLETED",
        artifact_path: str | None = None,
        artifact_name: str | None = None,
        artifact_size: int | None = None,
    ) -> GenerationJob:
        finished_at = timezone.now()
        job.status = "SUCCEEDED"
        job.job_stage = job_stage
        job.finished_at = finished_at
        job.result_json = result_json or job.result_json
        if artifact_path is not None:
            job.artifact_path = artifact_path
        if artifact_name is not None:
            job.artifact_name = artifact_name
        if artifact_size is not None:
            job.artifact_size = artifact_size
        if job.started_at is None:
            job.started_at = finished_at
        job.save(
            update_fields=[
                "status",
                "job_stage",
                "started_at",
                "finished_at",
                "result_json",
                "artifact_path",
                "artifact_name",
                "artifact_size",
            ]
        )
        return job


class SystemInstanceService:
    @staticmethod
    def create_instance(
        *,
        blueprint: SystemBlueprint,
        blueprint_version: SystemBlueprintVersion,
        name: str,
        mode: str,
        created_by,
        status: str = "DRAFT",
        tenant: Tenant | None = None,
    ) -> SystemInstance:
        return SystemInstance.objects.create(
            blueprint=blueprint,
            blueprint_version=blueprint_version,
            name=name,
            mode=mode,
            runtime_mode=mode,
            status=status,
            tenant=tenant,
            created_by=created_by,
        )

    @staticmethod
    @transaction.atomic
    def create_saas_instance_from_blueprint_version(
        *,
        blueprint_version: SystemBlueprintVersion,
        created_by,
        tenant_name: str,
        instance_name: str,
        industry: str = "",
        tenant_owner=None,
    ) -> SaasInstanceCreationResult:
        from core_apps.generation.services import GenerationService

        result = GenerationService.create_saas_instance_from_version(
            blueprint_version=blueprint_version,
            requested_by=created_by,
            instance_name=instance_name,
            tenant_name=tenant_name,
            industry=industry,
        )
        tenant = result.tenant
        snapshot = tenant.active_config_snapshot
        module_states = tuple(tenant.module_states.order_by("module_key"))
        return SaasInstanceCreationResult(
            tenant=tenant,
            instance=result.instance,
            generation_job=result.job,
            snapshot=snapshot,
            module_states=module_states,
        )


class BlueprintService:
    @staticmethod
    @transaction.atomic
    def create_blueprint(*, created_by, key: str, name: str, description: str = "", industry: str = "", status: str = "DRAFT"):
        return SystemBlueprint.objects.create(
            key=key,
            name=name,
            description=description,
            industry=industry,
            status=status,
            created_by=created_by,
        )

    @staticmethod
    @transaction.atomic
    def create_version(
        *,
        blueprint: SystemBlueprint,
        created_by,
        config_json: dict,
        version: str | None = None,
        change_note: str = "",
        is_published: bool = False,
    ):
        normalized = validate_blueprint_config(config_json)
        instance = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version=version or get_next_blueprint_version(blueprint),
            config_json=normalized,
            change_note=change_note,
            created_by=created_by,
            is_published=is_published,
        )
        if is_published:
            publish_blueprint_version(instance)
        return instance

    @staticmethod
    @transaction.atomic
    def publish_version(version: SystemBlueprintVersion):
        return publish_blueprint_version(version)

    @staticmethod
    @transaction.atomic
    def clone_version(*, source_version: SystemBlueprintVersion, created_by, version: str | None = None, change_note: str = ""):
        return BlueprintService.create_version(
            blueprint=source_version.blueprint,
            created_by=created_by,
            config_json=source_version.config_json,
            version=version,
            change_note=change_note or f"Clone from {source_version.version}",
            is_published=False,
        )
