from core_apps.blueprints.models import GenerationJob, SystemInstance


def get_generation_job_queryset():
    return GenerationJob.objects.select_related(
        "instance",
        "instance__tenant",
        "blueprint_version",
        "blueprint_version__blueprint",
        "requested_by",
    ).all()


def get_generation_job_result(job_id: int) -> GenerationJob:
    return get_generation_job_queryset().get(pk=job_id)


def get_system_instance_queryset():
    return SystemInstance.objects.select_related(
        "tenant",
        "blueprint",
        "blueprint_version",
        "current_generation_job",
        "current_generation_job__requested_by",
    ).prefetch_related("tenants").all()
