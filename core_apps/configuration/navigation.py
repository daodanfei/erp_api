from __future__ import annotations

from collections.abc import Iterable


NAVIGATION_GROUPS = (
    {"key": "sales_center", "label": "销售中心", "order": 1},
    {"key": "purchase_center", "label": "采购中心", "order": 2},
    {"key": "warehouse_logistics", "label": "仓储物流", "order": 3},
    {"key": "finance_center", "label": "财务中心", "order": 4},
    {"key": "reports_center", "label": "报表中心", "order": 5},
    {"key": "system_settings", "label": "系统设置", "order": 6},
)


def build_navigation_catalog(modules: Iterable[object]) -> list[dict]:
    """Build the fixed presentation navigation without changing module ownership."""
    items_by_group: dict[str, list[dict]] = {group["key"]: [] for group in NAVIGATION_GROUPS}
    seen_codes: set[str] = set()

    for module in modules:
        for menu in module.menus:
            group_key = menu.get("navigation_group")
            if not group_key:
                continue
            if group_key not in items_by_group:
                raise ValueError(f"Unknown navigation group: {module.key}:{menu['code']}->{group_key}")
            if menu["code"] in seen_codes:
                continue
            seen_codes.add(menu["code"])
            items_by_group[group_key].append(
                {
                    "module_key": module.key,
                    "code": menu["code"],
                    "label": menu["name"],
                    "path": menu["path"],
                    "order": menu["navigation_order"],
                    "feature_key": menu.get("feature_key"),
                    "feature_value": menu.get("feature_value", True),
                }
            )

    return [
        {
            **group,
            "items": sorted(items_by_group[group["key"]], key=lambda item: (item["order"], item["code"])),
        }
        for group in NAVIGATION_GROUPS
    ]
