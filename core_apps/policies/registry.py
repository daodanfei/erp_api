from __future__ import annotations

from dataclasses import dataclass

from core_apps.tenant.services import TenantRuntimeConfig, build_runtime_config, resolve_user_tenant
from core_apps.configuration.catalog import MODULE_CONFIGURATION_CATALOG

from business_apps.inventory.policies import InventoryPolicy
from business_apps.purchase.policies import PurchasePolicy
from business_apps.sales.policies import SalesPolicy
from business_apps.supplier.policies import SupplierPolicy
from business_apps.crm.policies import CustomerPolicy
from business_apps.supply_chain.policies import SupplyChainPolicy
from business_apps.finance.policies import FinancePolicy
from business_apps.ar_receivable.policies import ARReceivablePolicy
from business_apps.ap_payable.policies import APPayablePolicy
from business_apps.accounting.policies import AccountingPolicy
from business_apps.platform.policies import PlatformPolicy
from business_apps.reports.policies import ReportsPolicy


DEFAULT_RUNTIME_CONFIG_JSON = {
    "basic": {
        "name": "default_runtime",
        "industry": "general",
        "mode": "saas",
    },
    "enabled_modules": [
        "system",
        "platform",
        "crm",
        "inventory",
        "supplier",
        "purchase",
        "sales",
        "supply_chain",
        "finance",
        "ar_receivable",
        "ap_payable",
        "accounting",
        "reports",
    ],
    "module_configs": {
        **MODULE_CONFIGURATION_CATALOG,
        "system": {
            **MODULE_CONFIGURATION_CATALOG["system"],
        },
        "inventory": {
            **MODULE_CONFIGURATION_CATALOG["inventory"],
            "features": {
                **MODULE_CONFIGURATION_CATALOG["inventory"]["features"],
                "multi_warehouse": True,
                "warehouse_required_on_transaction": True,
            },
            "field_rules": {
                "inventory_transaction.warehouse": {
                    "visible": True,
                    "required": True,
                    "readonly": False,
                },
                "stocktake.warehouse": {
                    "visible": True,
                    "required": True,
                    "readonly": False,
                },
                "purchase_order_item.warehouse": {
                    "visible": True,
                    "required": True,
                    "readonly": False,
                },
                "sales_order_item.warehouse": {
                    "visible": True,
                    "required": True,
                    "readonly": False,
                },
            },
        },
        "purchase": {
            **MODULE_CONFIGURATION_CATALOG["purchase"],
            "features": {
                **MODULE_CONFIGURATION_CATALOG["purchase"]["features"],
                "approval": True,
            },
            "workflows": {
                **MODULE_CONFIGURATION_CATALOG["purchase"]["workflows"],
                "purchase_order_submit": "manual_approve",
            },
            "field_rules": {
                **MODULE_CONFIGURATION_CATALOG["purchase"]["field_rules"],
                "purchase_order.approver": {
                    "visible": True,
                    "required": False,
                    "readonly": True,
                },
            },
        },
        "sales": {
            **MODULE_CONFIGURATION_CATALOG["sales"],
            "features": {
                **MODULE_CONFIGURATION_CATALOG["sales"]["features"],
                "approval": True,
                "credit_control": True,
            },
            "workflows": {
                **MODULE_CONFIGURATION_CATALOG["sales"]["workflows"],
                "sales_order_submit": "manual_approve",
            },
        },
    },
}


POLICY_REGISTRY = {
    "platform": PlatformPolicy,
    "inventory": InventoryPolicy,
    "purchase": PurchasePolicy,
    "sales": SalesPolicy,
    "supplier": SupplierPolicy,
    "crm": CustomerPolicy,
    "supply_chain": SupplyChainPolicy,
    "finance": FinancePolicy,
    "ar_receivable": ARReceivablePolicy,
    "ap_payable": APPayablePolicy,
    "accounting": AccountingPolicy,
    "reports": ReportsPolicy,
}


@dataclass(frozen=True, slots=True)
class DefaultRuntimeTenant:
    id: int | None = None
    code: str = "default"
    name: str = "Default Runtime"
    status: str = "ACTIVE"


def build_default_runtime_config() -> TenantRuntimeConfig:
    return TenantRuntimeConfig(
        tenant=DefaultRuntimeTenant(),
        snapshot=None,
        config_json=DEFAULT_RUNTIME_CONFIG_JSON,
        module_overrides={},
    )


def get_runtime_config_for_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return build_default_runtime_config()
    tenant = resolve_user_tenant(user)
    if tenant is None:
        return build_default_runtime_config()
    return build_runtime_config(tenant)


def get_policy(module_key: str, *, user=None, runtime_config=None):
    policy_class = POLICY_REGISTRY[module_key]
    resolved_runtime_config = runtime_config or get_runtime_config_for_user(user)
    return policy_class(resolved_runtime_config, user=user)
