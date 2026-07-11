from __future__ import annotations

from business_apps.inventory.models import Warehouse


def normalize_default_warehouse_code(configured_code: str | None) -> str:
    code = (configured_code or "MAIN").strip().upper()
    return code or "MAIN"


def build_default_warehouse_code_candidates(*, tenant, configured_code: str | None) -> list[str]:
    normalized_code = normalize_default_warehouse_code(configured_code)
    candidates = [normalized_code]
    tenant_code = getattr(tenant, "code", "") or "TENANT"
    tenant_prefix = tenant_code.strip().upper().replace("_", "-")
    prefixed_code = f"{tenant_prefix}-{normalized_code}"[: Warehouse._meta.get_field("warehouse_code").max_length]
    if prefixed_code not in candidates:
        candidates.append(prefixed_code)
    return candidates


def resolve_tenant_default_warehouse_code(*, tenant, configured_code: str | None) -> str:
    candidates = build_default_warehouse_code_candidates(tenant=tenant, configured_code=configured_code)
    tenant_warehouses = Warehouse.objects.filter(tenant=tenant, warehouse_code__in=candidates)
    existing = tenant_warehouses.order_by("id").first()
    if existing is not None:
        return existing.warehouse_code

    for candidate in candidates:
        if not Warehouse.objects.filter(warehouse_code=candidate).exclude(tenant=tenant).exists():
            return candidate
    return candidates[-1]


def find_default_warehouse(*, tenant, configured_code: str | None, active_only: bool = True) -> Warehouse | None:
    candidates = build_default_warehouse_code_candidates(tenant=tenant, configured_code=configured_code)
    queryset = Warehouse.objects.filter(tenant=tenant, warehouse_code__in=candidates)
    if active_only:
        queryset = queryset.filter(status=True)
    return queryset.order_by("id").first()


def ensure_default_warehouse(*, tenant, configured_code: str | None, warehouse_name: str | None = None) -> Warehouse:
    warehouse_code = resolve_tenant_default_warehouse_code(tenant=tenant, configured_code=configured_code)
    warehouse, created = Warehouse.objects.get_or_create(
        tenant=tenant,
        warehouse_code=warehouse_code,
        defaults={
            "warehouse_name": warehouse_name or "默认仓库",
            "type": "MAIN",
            "status": True,
        },
    )
    update_fields: list[str] = []
    if not warehouse.status:
        warehouse.status = True
        update_fields.append("status")
    if warehouse.type != "MAIN":
        warehouse.type = "MAIN"
        update_fields.append("type")
    if created is False and not warehouse.warehouse_name and warehouse_name:
        warehouse.warehouse_name = warehouse_name
        update_fields.append("warehouse_name")
    if update_fields:
        warehouse.save(update_fields=update_fields)
    return warehouse
