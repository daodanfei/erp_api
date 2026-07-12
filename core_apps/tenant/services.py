from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.db.models import ProtectedError
from django.utils.text import slugify

from business_apps.inventory.features import (
    DEFAULT_WAREHOUSE_CODE,
    FEATURE_MULTI_WAREHOUSE,
    FEATURE_WAREHOUSE_REQUIRED_ON_TRANSACTION,
)
from business_apps.inventory.warehouse_utils import ensure_default_warehouse
from core_apps.erp_auth.services import ERPAdminProvisionResult, ERPUserProvisionService
from core_apps.erp_auth.models import ERPUser
from core_apps.configuration import ConfigurationService, validate_blueprint_config
from core_apps.blueprints.models import SystemBlueprintVersion, SystemInstance
from core_apps.modules import get_business_modules, get_core_modules

from .models import Tenant, TenantConfigSnapshot, TenantModuleState, TenantUser


def get_registered_module_keys() -> set[str]:
    modules = (*get_core_modules(), *get_business_modules())
    return {module.key for module in modules}


def resolve_user_tenant(user, tenant_code: str | None = None) -> Tenant | None:
    if isinstance(user, ERPUser):
        if tenant_code and user.tenant.code != tenant_code:
            return None
        return user.tenant if user.tenant.status == "ACTIVE" else None
    memberships = TenantUser.objects.select_related("tenant").filter(user=user, tenant__status="ACTIVE")
    if tenant_code:
        membership = memberships.filter(tenant__code=tenant_code).first()
        return membership.tenant if membership else None
    default_membership = memberships.filter(is_default=True).first()
    if default_membership:
        return default_membership.tenant
    first_membership = memberships.order_by("id").first()
    return first_membership.tenant if first_membership else None


def get_latest_tenant_snapshot(tenant: Tenant) -> TenantConfigSnapshot | None:
    return tenant.active_config_snapshot


def generate_tenant_code(*parts: str) -> str:
    raw_name = " ".join(part.strip() for part in parts if part and part.strip())
    base_code = slugify(raw_name, allow_unicode=False).replace("_", "-").strip("-")
    if not base_code:
        source = raw_name or "tenant"
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
        base_code = f"tenant-{digest}"

    max_length = Tenant._meta.get_field("code").max_length or 100
    base_code = base_code[:max_length].rstrip("-") or "tenant"

    candidate = base_code
    suffix = 2
    while Tenant.objects.filter(code=candidate).exists():
        suffix_text = f"-{suffix}"
        trimmed_base = base_code[: max_length - len(suffix_text)].rstrip("-")
        candidate = f"{trimmed_base}{suffix_text}" if trimmed_base else f"tenant{suffix_text}"
        suffix += 1
    return candidate


@dataclass(frozen=True, slots=True)
class TenantRuntimeConfig:
    tenant: Any
    snapshot: TenantConfigSnapshot | None
    config_json: dict[str, Any]
    module_overrides: dict[str, bool]

    def is_enabled(self, module_key: str) -> bool:
        if module_key in self.module_overrides:
            return self.module_overrides[module_key]
        return module_key in self.config_json.get("enabled_modules", [])

    def get_default(self, key: str, default: Any = None, module_key: str | None = None) -> Any:
        if module_key is None:
            return self.config_json.get("basic", {}).get(key, default)
        return ConfigurationService.get_default_value(self, module_key, key, default=default)

    def get_workflow(self, module_key: str, workflow_key: str, default: Any = None) -> Any:
        return ConfigurationService.get_workflow(self, module_key, workflow_key, default=default)

    def get_field_rule(self, module_key: str, field_key: str, default: Any = None) -> Any:
        return ConfigurationService.get_field_rule(self, module_key, field_key, default=default)

    def is_feature_enabled(self, module_key: str, feature_key: str) -> bool:
        return ConfigurationService.is_feature_enabled(self, module_key, feature_key)

    def enabled_modules(self) -> list[str]:
        module_keys = get_registered_module_keys()
        return sorted(module_key for module_key in module_keys if self.is_enabled(module_key))


@dataclass(frozen=True, slots=True)
class TenantProvisionResult:
    tenant: Tenant
    snapshot: TenantConfigSnapshot
    module_states: tuple[TenantModuleState, ...]


@dataclass(frozen=True, slots=True)
class TenantInstanceBindingResult:
    tenant: Tenant
    instance: SystemInstance
    snapshot: TenantConfigSnapshot | None
    initial_admin: ERPAdminProvisionResult


def build_runtime_config(tenant: Tenant) -> TenantRuntimeConfig:
    snapshot = get_latest_tenant_snapshot(tenant)
    module_overrides = {
        state.module_key: state.enabled
        for state in TenantModuleState.objects.filter(tenant=tenant)
    }
    config_json = (
        validate_blueprint_config(snapshot.config_json)
        if snapshot
        else ConfigurationService.build_empty_config()
    )
    return TenantRuntimeConfig(
        tenant=tenant,
        snapshot=snapshot,
        config_json=config_json,
        module_overrides=module_overrides,
    )


def _get_inventory_transition_state(config_json: dict | None) -> dict[str, object]:
    if not config_json:
        normalized = {
            "basic": {},
            "enabled_modules": [],
            "module_configs": {},
        }
    else:
        normalized = validate_blueprint_config(config_json)
    inventory_config = normalized["module_configs"].get("inventory", {})
    inventory_features = inventory_config.get("features", {})
    inventory_defaults = inventory_config.get("defaults", {})
    return {
        "normalized": normalized,
        "multi_warehouse": bool(inventory_features.get(FEATURE_MULTI_WAREHOUSE, False)),
        "warehouse_required": bool(inventory_features.get(FEATURE_WAREHOUSE_REQUIRED_ON_TRANSACTION, False)),
        "default_warehouse_code": inventory_defaults.get(DEFAULT_WAREHOUSE_CODE) or "MAIN",
    }


def _validate_inventory_mode_transition(*, tenant: Tenant, current_config_json: dict | None, next_config_json: dict) -> None:
    current_state = _get_inventory_transition_state(current_config_json)
    next_state = _get_inventory_transition_state(next_config_json)
    current_single_warehouse = not current_state["multi_warehouse"] and not current_state["warehouse_required"]
    next_requires_explicit_warehouse = bool(next_state["multi_warehouse"] or next_state["warehouse_required"])
    if not current_single_warehouse or not next_requires_explicit_warehouse:
        return

    from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem
    from business_apps.sales.models import SalesOrder, SalesOrderItem

    purchase_missing_count = PurchaseOrderItem.objects.filter(
        tenant=tenant,
        warehouse__isnull=True,
        purchase_order__status__in=(
            PurchaseOrder.STATUS_DRAFT,
            PurchaseOrder.STATUS_PENDING_APPROVAL,
            PurchaseOrder.STATUS_APPROVED,
            PurchaseOrder.STATUS_REJECTED,
        ),
    ).count()
    sales_missing_count = SalesOrderItem.objects.filter(
        tenant=tenant,
        warehouse__isnull=True,
        order__status__in=(
            SalesOrder.STATUS_DRAFT,
            SalesOrder.STATUS_PENDING_APPROVAL,
            SalesOrder.STATUS_APPROVED,
            SalesOrder.STATUS_REJECTED,
            SalesOrder.STATUS_ALLOCATED,
        ),
    ).count()
    if purchase_missing_count or sales_missing_count:
        raise ValueError(
            "切换为多仓/按单据选仓前校验失败："
            f"仍有 {purchase_missing_count} 条采购明细、{sales_missing_count} 条销售明细未绑定仓库。"
            "请先清理或删除这些在途单据后再切换。"
        )


def _should_auto_create_default_warehouse(inventory_state: dict[str, object]) -> bool:
    return not bool(inventory_state["multi_warehouse"]) and not bool(inventory_state["warehouse_required"])


def _refresh_existing_tenant_super_admin_role(*, tenant: Tenant) -> None:
    user = ERPUserProvisionService.get_tenant_super_admin(tenant=tenant)
    if user is None:
        return
    ERPUserProvisionService.ensure_super_admin_role(user=user)


class TenantService:
    PURGE_EXCLUDED_MODELS = {
        ("tenant", "Tenant"),
        ("tenant", "TenantConfigSnapshot"),
        ("tenant", "TenantModuleState"),
        ("tenant", "TenantUser"),
    }

    @staticmethod
    @transaction.atomic
    def create_tenant(
        *,
        code: str,
        name: str,
        industry: str = "",
        owner=None,
        instance: SystemInstance | None = None,
        user_limit: int | None = None,
    ) -> Tenant:
        if not code:
            code = generate_tenant_code(name)
        tenant = Tenant.objects.create(
            code=code,
            name=name,
            instance=instance,
            industry=industry,
            status="ACTIVE",
            user_limit=user_limit,
        )
        if owner is not None:
            TenantUser.objects.create(tenant=tenant, user=owner, is_owner=True, is_default=True)
        ensure_default_warehouse(tenant=tenant, configured_code="MAIN")
        return tenant

    @staticmethod
    @transaction.atomic
    def provision_from_blueprint_version(
        *,
        code: str,
        name: str,
        blueprint_version: SystemBlueprintVersion,
        industry: str = "",
        owner=None,
        instance: SystemInstance | None = None,
        user_limit: int | None = None,
    ) -> TenantProvisionResult:
        tenant = TenantService.create_tenant(
            code=code,
            name=name,
            industry=industry,
            owner=owner,
            instance=instance,
            user_limit=user_limit,
        )
        snapshot = TenantService.apply_blueprint_version(tenant=tenant, blueprint_version=blueprint_version)
        module_states = tuple(TenantModuleState.objects.filter(tenant=tenant).order_by("module_key"))
        return TenantProvisionResult(
            tenant=tenant,
            snapshot=snapshot,
            module_states=module_states,
        )

    @staticmethod
    @transaction.atomic
    def create_from_blueprint_version(
        *,
        code: str,
        name: str,
        blueprint_version: SystemBlueprintVersion,
        industry: str = "",
        owner=None,
        instance: SystemInstance | None = None,
        user_limit: int | None = None,
    ):
        result = TenantService.provision_from_blueprint_version(
            code=code,
            name=name,
            blueprint_version=blueprint_version,
            industry=industry,
            owner=owner,
            instance=instance,
            user_limit=user_limit,
        )
        return result.tenant

    @staticmethod
    @transaction.atomic
    def apply_blueprint_version(*, tenant: Tenant, blueprint_version: SystemBlueprintVersion):
        normalized = validate_blueprint_config(blueprint_version.config_json)
        current_snapshot = get_latest_tenant_snapshot(tenant)
        _validate_inventory_mode_transition(
            tenant=tenant,
            current_config_json=current_snapshot.config_json if current_snapshot is not None else None,
            next_config_json=normalized,
        )
        snapshot = TenantConfigSnapshot.objects.create(
            tenant=tenant,
            blueprint_version=blueprint_version,
            config_json=normalized,
        )
        registered_module_keys = get_registered_module_keys()
        enabled_modules = set(normalized["enabled_modules"])
        mirrored_module_keys = registered_module_keys | enabled_modules
        existing_states = {
            state.module_key: state
            for state in TenantModuleState.objects.filter(tenant=tenant)
        }
        for module_key in mirrored_module_keys:
            enabled = module_key in enabled_modules
            state = existing_states.get(module_key)
            if state is None:
                TenantModuleState.objects.create(tenant=tenant, module_key=module_key, enabled=enabled)
            elif state.enabled != enabled:
                state.enabled = enabled
                state.save(update_fields=["enabled"])
        ensure_default_warehouse(
            tenant=tenant,
            configured_code=normalized["module_configs"].get("inventory", {}).get("defaults", {}).get(DEFAULT_WAREHOUSE_CODE),
        )
        _refresh_existing_tenant_super_admin_role(tenant=tenant)
        return snapshot

    @staticmethod
    @transaction.atomic
    def ensure_tenant_snapshot(*, tenant: Tenant, blueprint_version: SystemBlueprintVersion) -> TenantConfigSnapshot:
        return TenantConfigSnapshot.objects.create(
            tenant=tenant,
            blueprint_version=blueprint_version,
            config_json=validate_blueprint_config(blueprint_version.config_json),
        )

    @staticmethod
    @transaction.atomic
    def bind_instance_to_tenant(
        *,
        tenant: Tenant,
        instance: SystemInstance,
        blueprint_version: SystemBlueprintVersion | None = None,
    ) -> TenantInstanceBindingResult:
        if instance.runtime_mode != "SAAS":
            raise ValueError("只有 SaaS 实例可以绑定租户")
        tenant.instance = instance
        tenant.save(update_fields=["instance"])
        resolved_version = blueprint_version or instance.blueprint_version
        snapshot = None
        if resolved_version is not None:
            snapshot = TenantService.apply_blueprint_version(tenant=tenant, blueprint_version=resolved_version)
        initial_admin = ERPUserProvisionService.ensure_tenant_super_admin(tenant=tenant)
        return TenantInstanceBindingResult(
            tenant=tenant,
            instance=instance,
            snapshot=snapshot,
            initial_admin=initial_admin,
        )

    @staticmethod
    def _iter_purgeable_tenant_models():
        models = []
        for model in apps.get_models():
            if (model._meta.app_label, model.__name__) in TenantService.PURGE_EXCLUDED_MODELS:
                continue
            if TenantService._iter_tenant_lookup_paths(model):
                models.append(model)
        return models

    @staticmethod
    def _iter_tenant_lookup_paths(model, *, max_depth: int = 4) -> list[str]:
        paths: set[str] = set()
        queue: list[tuple[type, list[str], set[type]]] = [(model, [], {model})]

        while queue:
            current_model, prefix, visited_models = queue.pop(0)
            for field in current_model._meta.get_fields():
                if not getattr(field, "is_relation", False):
                    continue
                if not getattr(field, "many_to_one", False) and not getattr(field, "one_to_one", False):
                    continue
                remote_model = getattr(getattr(field, "remote_field", None), "model", None)
                if remote_model is None:
                    continue

                path_segments = [*prefix, field.name]
                path = "__".join(path_segments)
                if remote_model is Tenant:
                    paths.add(path)
                    continue
                if len(path_segments) >= max_depth:
                    continue
                if remote_model in visited_models:
                    continue
                queue.append((remote_model, path_segments, {remote_model, *visited_models}))

        return sorted(paths)

    @staticmethod
    def _tenant_scoped_queryset(*, model, tenant: Tenant):
        lookup_paths = TenantService._iter_tenant_lookup_paths(model)
        if not lookup_paths:
            return model.objects.none()

        query = Q()
        for path in lookup_paths:
            query |= Q(**{path: tenant})
        return model.objects.filter(query).distinct()

    @staticmethod
    @transaction.atomic
    def clear_tenant_data(*, tenant: Tenant) -> dict[str, object]:
        deleted_summary: dict[str, int] = {}
        purgeable_models = TenantService._iter_purgeable_tenant_models()
        remaining_models = list(purgeable_models)

        while remaining_models:
            progressed = False
            blocked_models = []
            for model in remaining_models:
                queryset = TenantService._tenant_scoped_queryset(model=model, tenant=tenant)
                count = queryset.count()
                if count <= 0:
                    progressed = True
                    continue
                try:
                    queryset.delete()
                except ProtectedError:
                    blocked_models.append(model)
                    continue
                deleted_summary[f"{model._meta.app_label}.{model.__name__}"] = (
                    deleted_summary.get(f"{model._meta.app_label}.{model.__name__}", 0) + count
                )
                progressed = True

            if not blocked_models:
                break
            if not progressed:
                blocked_names = ", ".join(
                    sorted(f"{model._meta.app_label}.{model.__name__}" for model in blocked_models)
                )
                raise ValueError(f"清空租户数据失败，仍存在受保护引用未解除：{blocked_names}")
            remaining_models = blocked_models

        config_json = tenant.active_config_snapshot.config_json if tenant.active_config_snapshot is not None else None
        inventory_state = _get_inventory_transition_state(config_json)
        if _should_auto_create_default_warehouse(inventory_state):
            ensure_default_warehouse(
                tenant=tenant,
                configured_code=inventory_state["default_warehouse_code"],
            )
        provision_result = ERPUserProvisionService.ensure_tenant_super_admin(tenant=tenant)
        return {
            "tenant_id": tenant.id,
            "tenant_code": tenant.code,
            "deleted_models": deleted_summary,
            "initial_admin": {
                "user_id": provision_result.user.id,
                "username": provision_result.user.username,
                "created": provision_result.created,
                "initial_password": provision_result.initial_password,
            },
        }

    @staticmethod
    def get_runtime_config(tenant: Tenant):
        return build_runtime_config(tenant)
