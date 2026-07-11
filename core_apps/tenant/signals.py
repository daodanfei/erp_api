from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant


BUSINESS_MODULE_PREFIX = "business_apps."
MAX_TENANT_INFERENCE_DEPTH = 4


def _is_business_tenant_model(sender) -> bool:
    if not sender.__module__.startswith(BUSINESS_MODULE_PREFIX):
        return False
    try:
        tenant_field = sender._meta.get_field("tenant")
    except Exception:
        return False
    remote_model = getattr(getattr(tenant_field, "remote_field", None), "model", None)
    return remote_model is Tenant


def _get_direct_tenant(instance):
    if instance is None:
        return None
    if isinstance(instance, Tenant):
        return instance
    if isinstance(instance, ERPUser):
        return instance.tenant if instance.tenant_id else None

    tenant_id = getattr(instance, "tenant_id", None)
    if tenant_id is None:
        return None
    try:
        return instance.tenant
    except ObjectDoesNotExist:
        return None


def _collect_related_tenants(
    instance,
    *,
    depth: int = MAX_TENANT_INFERENCE_DEPTH,
    visited=None,
    include_self: bool = False,
) -> dict[int, Tenant]:
    if instance is None or depth < 0 or not hasattr(instance, "_meta"):
        return {}

    visited = visited or set()
    marker = (instance.__class__, getattr(instance, "pk", None), id(instance))
    if marker in visited:
        return {}
    visited.add(marker)

    direct_tenant = _get_direct_tenant(instance)
    if include_self and direct_tenant is not None:
        return {direct_tenant.id: direct_tenant}

    tenants: dict[int, Tenant] = {}
    for field in instance._meta.get_fields():
        if getattr(field, "auto_created", False) or not getattr(field, "is_relation", False):
            continue
        if getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False):
            continue
        if field.name == "tenant":
            continue

        try:
            related_obj = getattr(instance, field.name)
        except ObjectDoesNotExist:
            continue
        if related_obj is None:
            continue

        related_tenant = _get_direct_tenant(related_obj)
        if related_tenant is not None:
            tenants[related_tenant.id] = related_tenant
            continue

        if depth == 0:
            continue
        tenants.update(
            _collect_related_tenants(
                related_obj,
                depth=depth - 1,
                visited=visited,
                include_self=True,
            )
        )

    return tenants


@receiver(pre_save, dispatch_uid="enforce_business_model_tenant_consistency")
def enforce_business_model_tenant_consistency(sender, instance, raw=False, **kwargs):
    if raw or not _is_business_tenant_model(sender):
        return

    related_tenants = _collect_related_tenants(instance)
    if not related_tenants:
        return
    if len(related_tenants) > 1:
        raise ValidationError({"tenant": "关联数据租户不一致，禁止保存"})

    inferred_tenant = next(iter(related_tenants.values()))
    current_tenant = _get_direct_tenant(instance)
    if current_tenant is None:
        instance.tenant = inferred_tenant
        return
    if current_tenant.id != inferred_tenant.id:
        raise ValidationError({"tenant": "租户与关联数据不一致，禁止保存"})
