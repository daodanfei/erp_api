from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core_apps.blueprints.models import GenerationJob, SystemBlueprintVersion, SystemInstance
from core_apps.blueprints.serializers import GenerationJobSerializer, SystemInstanceSerializer
from core_apps.blueprints.services import GenerationJobService
from core_apps.tenant.models import Tenant, TenantModuleState
from core_apps.tenant.serializers import TenantConfigSnapshotSerializer, TenantModuleStateSerializer, TenantSerializer
from core_apps.tenant.services import TenantService, generate_tenant_code

from .exporters import export_code_package
from .planners import GenerationPlan, build_generation_plan
from .validators import validate_blueprint_version_for_generation


@dataclass(frozen=True, slots=True)
class GenerationExecutionResult:
    instance: SystemInstance | None
    tenant: Tenant | None
    job: GenerationJob
    plan: GenerationPlan

    def to_dict(self) -> dict:
        return {
            "instance": SystemInstanceSerializer(self.instance).data if self.instance is not None else None,
            "tenant": TenantSerializer(self.tenant).data if self.tenant is not None else None,
            "generation_job": GenerationJobSerializer(self.job).data,
            "plan": self.plan.to_dict(),
        }


class GenerationService:
    @staticmethod
    def preview_plan(*, blueprint_version: SystemBlueprintVersion, runtime_mode: str) -> GenerationPlan:
        validation = validate_blueprint_version_for_generation(
            blueprint_version=blueprint_version,
            runtime_mode=runtime_mode,
            require_published=False,
        )
        return build_generation_plan(blueprint_version, runtime_mode=runtime_mode)

    @staticmethod
    def create_saas_instance_from_version(
        *,
        blueprint_version: SystemBlueprintVersion,
        requested_by,
        instance_name: str = "",
        tenant: Tenant | None = None,
        tenant_name: str = "",
        industry: str = "",
        retry_count: int = 0,
    ) -> GenerationExecutionResult:
        return GenerationService.create_generation(
            blueprint_version=blueprint_version,
            runtime_mode="SAAS",
            requested_by=requested_by,
            instance_name=instance_name,
            tenant=tenant,
            tenant_name=tenant_name,
            industry=industry,
            retry_count=retry_count,
        )

    @staticmethod
    def export_code_from_version(
        *,
        blueprint_version: SystemBlueprintVersion,
        requested_by,
        instance_name: str = "",
        retry_count: int = 0,
    ) -> GenerationExecutionResult:
        return GenerationService.create_generation(
            blueprint_version=blueprint_version,
            runtime_mode="CODE_EXPORT",
            requested_by=requested_by,
            instance_name=instance_name,
            retry_count=retry_count,
        )

    @staticmethod
    @transaction.atomic
    def create_generation(
        *,
        blueprint_version: SystemBlueprintVersion,
        runtime_mode: str,
        requested_by,
        instance_name: str = "",
        tenant: Tenant | None = None,
        tenant_name: str = "",
        industry: str = "",
        retry_count: int = 0,
    ) -> GenerationExecutionResult:
        validation = validate_blueprint_version_for_generation(
            blueprint_version=blueprint_version,
            runtime_mode=runtime_mode,
        )
        plan = build_generation_plan(
            blueprint_version,
            runtime_mode=runtime_mode,
        )
        resolved_instance_name = instance_name or f"{blueprint_version.blueprint.name} {runtime_mode}"
        resolved_tenant_name = tenant.name if tenant is not None else tenant_name
        resolved_tenant_code = (
            tenant.code if tenant is not None else generate_tenant_code(resolved_tenant_name)
        ) if runtime_mode == "SAAS" else ""
        job = GenerationJobService.create_job(
            instance=None,
            blueprint_version=blueprint_version,
            job_type="CREATE_SAAS" if runtime_mode == "SAAS" else "EXPORT_CODE",
            status="RUNNING",
            job_stage="VALIDATING",
            payload_json={
                "runtime_mode": runtime_mode,
                "instance_name": resolved_instance_name,
                "tenant_id": tenant.id if tenant is not None else None,
                "tenant_code": resolved_tenant_code,
                "tenant_name": resolved_tenant_name,
                "industry": industry,
            },
            config_snapshot_json=validation.normalized_config,
            requested_by=requested_by,
            retry_count=retry_count,
            started_at=timezone.now(),
        )
        GenerationJobService.append_log(job, stage="VALIDATING", message="Blueprint version validated.")
        GenerationJobService.append_log(
            job,
            stage="PLANNING",
            message="Generation plan resolved.",
            extra={"module_keys": list(plan.module_keys)},
        )

        try:
            if runtime_mode == "SAAS":
                result = GenerationService._execute_saas(
                    job=job,
                    blueprint_version=blueprint_version,
                    plan=plan,
                    instance_name=resolved_instance_name,
                    tenant=tenant,
                    tenant_code=resolved_tenant_code,
                    tenant_name=resolved_tenant_name,
                    industry=industry or blueprint_version.blueprint.industry,
                    requested_by=requested_by,
                )
            else:
                result = GenerationService._execute_code_export(
                    job=job,
                    blueprint_version=blueprint_version,
                    plan=plan,
                )
        except Exception as exc:
            GenerationJobService.append_log(job, stage="FAILED", level="ERROR", message=str(exc))
            GenerationJobService.mark_failed(job, stage="FAILED", error_message=str(exc))
            raise

        return GenerationExecutionResult(instance=result.instance, tenant=result.tenant, job=result.job, plan=plan)

    @staticmethod
    def retry_generation(*, source_job: GenerationJob, requested_by) -> GenerationExecutionResult:
        payload = source_job.payload_json or {}
        return GenerationService.retry_generation_job(
            source_job=source_job,
            requested_by=requested_by,
            instance_name=payload.get("instance_name", ""),
            tenant=Tenant.objects.filter(pk=payload.get("tenant_id")).first() if payload.get("tenant_id") else None,
            tenant_name=payload.get("tenant_name", ""),
            industry=payload.get("industry", ""),
        )

    @staticmethod
    def retry_generation_job(
        *,
        source_job: GenerationJob,
        requested_by,
        instance_name: str = "",
        tenant: Tenant | None = None,
        tenant_name: str = "",
        industry: str = "",
    ) -> GenerationExecutionResult:
        payload = source_job.payload_json or {}
        runtime_mode = payload.get("runtime_mode", "SAAS")
        if runtime_mode == "SAAS":
            return GenerationService.create_saas_instance_from_version(
                blueprint_version=source_job.blueprint_version,
                requested_by=requested_by,
                instance_name=instance_name or payload.get("instance_name", ""),
                tenant=tenant,
                tenant_name=tenant_name,
                industry=industry,
                retry_count=source_job.retry_count + 1,
            )
        return GenerationService.export_code_from_version(
            blueprint_version=source_job.blueprint_version,
            requested_by=requested_by,
            instance_name=instance_name or payload.get("instance_name", ""),
            retry_count=source_job.retry_count + 1,
        )

    @staticmethod
    def build_audit_payload(*, job: GenerationJob) -> dict:
        payload = job.payload_json or {}
        result = job.result_json or {}
        runtime_mode = payload.get("runtime_mode", "SAAS")
        plan = build_generation_plan(
            job.blueprint_version,
            normalized_config=job.config_snapshot_json or job.blueprint_version.config_json,
            runtime_mode=runtime_mode,
        )
        tenant_id = result.get("tenant_id") or payload.get("tenant_id")
        tenant = Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
        return {
            "job": GenerationJobSerializer(job).data,
            "tenant": TenantSerializer(tenant).data if tenant is not None else None,
            "instance": SystemInstanceSerializer(job.instance).data if job.instance_id else None,
            "plan": plan.to_dict(),
        }

    @staticmethod
    def get_generation_result(*, generation_job: GenerationJob) -> dict:
        return GenerationService.build_audit_payload(job=generation_job)

    @staticmethod
    def get_instance_result(*, instance: SystemInstance) -> dict:
        recent_jobs = list(
            instance.generation_jobs.select_related("requested_by", "blueprint_version", "blueprint_version__blueprint")
            .order_by("-id")[:10]
        )
        latest_job = recent_jobs[0] if recent_jobs else None
        latest_failed_job = next((job for job in recent_jobs if job.status == "FAILED"), None)
        tenant = instance.tenant or instance.tenants.order_by("id").first()
        snapshot = tenant.active_config_snapshot if tenant is not None else None
        module_states = tenant.module_states.order_by("module_key") if tenant is not None else []
        return {
            "instance": SystemInstanceSerializer(instance).data,
            "tenant": TenantSerializer(tenant).data if tenant is not None else None,
            "tenants": TenantSerializer(instance.tenants.order_by("id"), many=True).data,
            "snapshot": TenantConfigSnapshotSerializer(snapshot).data if snapshot is not None else None,
            "module_states": TenantModuleStateSerializer(module_states, many=True).data,
            "current_job": GenerationJobSerializer(instance.current_generation_job).data if instance.current_generation_job_id else None,
            "latest_job": GenerationJobSerializer(latest_job).data if latest_job is not None else None,
            "latest_failed_job": GenerationJobSerializer(latest_failed_job).data if latest_failed_job is not None else None,
            "recent_jobs": GenerationJobSerializer(recent_jobs, many=True).data,
        }

    @staticmethod
    @transaction.atomic
    def reapply_blueprint_version(
        *,
        instance: SystemInstance,
        blueprint_version: SystemBlueprintVersion,
        requested_by,
    ) -> GenerationExecutionResult:
        if instance.runtime_mode != "SAAS":
            raise ValueError("只有 SaaS 实例支持重新应用蓝图版本")
        if instance.tenant_id is None:
            raise ValueError("当前实例未绑定租户，无法重新应用蓝图版本")

        validation = validate_blueprint_version_for_generation(
            blueprint_version=blueprint_version,
            runtime_mode="SAAS",
        )
        plan = build_generation_plan(blueprint_version, runtime_mode="SAAS")
        job = GenerationJobService.create_job(
            instance=instance,
            blueprint_version=blueprint_version,
            job_type="CREATE_SAAS",
            status="RUNNING",
            job_stage="VALIDATING",
            payload_json={
                "runtime_mode": "SAAS",
                "operation": "REAPPLY_BLUEPRINT_VERSION",
                "instance_name": instance.name,
                "tenant_code": instance.tenant.code,
                "tenant_name": instance.tenant.name,
            },
            config_snapshot_json=validation.normalized_config,
            requested_by=requested_by,
            retry_count=0,
            started_at=timezone.now(),
        )
        instance.status = "GENERATING"
        instance.current_generation_job = job
        instance.save(update_fields=["status", "current_generation_job"])
        GenerationJobService.append_log(job, stage="VALIDATING", message="Blueprint version validated for reapply.")
        GenerationJobService.append_log(
            job,
            stage="PLANNING",
            message="Generation plan resolved for existing instance.",
            extra={"module_keys": list(plan.module_keys), "instance_id": instance.id},
        )
        try:
            GenerationJobService.append_log(job, stage="APPLYING_BLUEPRINT", message="Applying blueprint version to existing tenant.")
            TenantService.apply_blueprint_version(tenant=instance.tenant, blueprint_version=blueprint_version)
            instance.blueprint = blueprint_version.blueprint
            instance.blueprint_version = blueprint_version
            instance.status = "ACTIVE"
            instance.published_at = timezone.now()
            instance.current_generation_job = job
            instance.save(
                update_fields=["blueprint", "blueprint_version", "status", "published_at", "current_generation_job"]
            )
            GenerationJobService.append_log(job, stage="FINALIZING", message="Existing instance blueprint version updated.")
            GenerationJobService.mark_succeeded(
                job,
                result_json={"operation": "REAPPLY_BLUEPRINT_VERSION", "instance_id": instance.id},
                job_stage="COMPLETED",
            )
        except Exception as exc:
            instance.status = "FAILED"
            instance.current_generation_job = job
            instance.save(update_fields=["status", "current_generation_job"])
            GenerationJobService.append_log(job, stage="FAILED", level="ERROR", message=str(exc))
            GenerationJobService.mark_failed(job, stage="FAILED", error_message=str(exc))
            raise
        return GenerationExecutionResult(instance=instance, job=job, plan=plan)

    @staticmethod
    @transaction.atomic
    def update_instance_status(*, instance: SystemInstance, status_value: str) -> SystemInstance:
        if status_value not in {"ACTIVE", "INACTIVE", "ARCHIVED"}:
            raise ValueError("不支持的实例状态")
        bound_tenants = list(instance.tenants.all())
        legacy_tenant = instance.tenant
        if instance.runtime_mode == "SAAS" and (legacy_tenant is not None or bound_tenants):
            tenant_status = "ACTIVE" if status_value == "ACTIVE" else "INACTIVE" if status_value == "INACTIVE" else "ARCHIVED"
            for tenant in [*bound_tenants, *( [legacy_tenant] if legacy_tenant is not None and legacy_tenant not in bound_tenants else [])]:
                if tenant.status != tenant_status:
                    tenant.status = tenant_status
                    tenant.save(update_fields=["status"])
        instance.status = status_value
        instance.save(update_fields=["status"])
        return instance

    @staticmethod
    def _execute_saas(
        *,
        job: GenerationJob,
        blueprint_version: SystemBlueprintVersion,
        plan: GenerationPlan,
        instance_name: str,
        tenant: Tenant | None = None,
        tenant_code: str = "",
        tenant_name: str = "",
        industry: str = "",
        requested_by=None,
    ) -> GenerationExecutionResult:
        GenerationJobService.append_log(job, stage="PROVISIONING", message="Provisioning tenant runtime.")
        if tenant is None:
            tenant = TenantService.create_tenant(
                code=tenant_code or generate_tenant_code(tenant_name),
                name=tenant_name,
                industry=industry,
                owner=requested_by,
            )
            GenerationJobService.append_log(job, stage="PROVISIONING", message="Tenant created.")
        else:
            update_fields = []
            if tenant_name and tenant.name != tenant_name:
                tenant.name = tenant_name
                update_fields.append("name")
            if industry and tenant.industry != industry:
                tenant.industry = industry
                update_fields.append("industry")
            if update_fields:
                tenant.save(update_fields=update_fields)
            GenerationJobService.append_log(job, stage="PROVISIONING", message="Tenant selected.")
        GenerationJobService.append_log(job, stage="APPLYING_BLUEPRINT", message="Applying blueprint version to tenant.")
        snapshot = TenantService.apply_blueprint_version(tenant=tenant, blueprint_version=blueprint_version)
        module_states = tuple(TenantModuleState.objects.filter(tenant=tenant).order_by("module_key"))
        GenerationJobService.append_log(job, stage="FINALIZING", message="Tenant runtime is active.")
        job = GenerationJobService.mark_succeeded(
            job,
            job_stage="COMPLETED",
            result_json={
                "tenant_id": tenant.id,
                "snapshot_id": snapshot.id,
                "instance_name": instance_name,
                "enabled_modules": [state.module_key for state in module_states if state.enabled],
            },
        )
        return GenerationExecutionResult(instance=None, tenant=tenant, job=job, plan=plan)

    @staticmethod
    def _execute_code_export(
        *,
        job: GenerationJob,
        blueprint_version: SystemBlueprintVersion,
        plan: GenerationPlan,
    ) -> GenerationExecutionResult:
        GenerationJobService.append_log(job, stage="EXPORTING", message="Collecting export sources and building artifact.")
        artifact = export_code_package(
            job_key=job.job_key,
            blueprint_payload={
                "blueprint_key": blueprint_version.blueprint.key,
                "blueprint_name": blueprint_version.blueprint.name,
                "blueprint_version": blueprint_version.version,
                "config_snapshot_json": job.config_snapshot_json,
            },
            plan=plan,
        )
        GenerationJobService.append_log(
            job,
            stage="FINALIZING",
            message="Code export artifact generated.",
            extra={"artifact_name": artifact.artifact_name},
        )
        job = GenerationJobService.mark_succeeded(
            job,
            job_stage="COMPLETED",
            artifact_path=artifact.artifact_path,
            artifact_name=artifact.artifact_name,
            artifact_size=artifact.artifact_size,
            result_json={
                "artifact_name": artifact.artifact_name,
                "artifact_checksum": artifact.artifact_checksum,
                "artifact_size": artifact.artifact_size,
                "module_keys": list(plan.module_keys),
            },
        )
        return GenerationExecutionResult(instance=None, tenant=None, job=job, plan=plan)
