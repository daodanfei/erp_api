from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_INVENTORY_ALERT_ENABLED,
    FEATURE_OUTBOUND_REQUIRES_ALLOCATION,
    FEATURE_PURCHASE_RETURN_ENABLED,
    FEATURE_RETURN_APPROVAL,
    FEATURE_SALES_RETURN_ENABLED,
    FEATURE_TRACE_ENABLED,
    FEATURE_TRANSFER_APPROVAL,
    FEATURE_TRANSFER_ENABLED,
)


class SupplyChainPolicy(BasePolicy):
    module_key = "supply_chain"

    def transfer_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_TRANSFER_ENABLED, default=True)

    def sales_return_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SALES_RETURN_ENABLED, default=True)

    def purchase_return_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PURCHASE_RETURN_ENABLED, default=True)

    def inventory_alert_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_INVENTORY_ALERT_ENABLED, default=True)

    def trace_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_TRACE_ENABLED, default=True)

    def outbound_requires_allocation(self) -> bool:
        return self.is_feature_enabled(FEATURE_OUTBOUND_REQUIRES_ALLOCATION, default=True)

    def transfer_approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_TRANSFER_APPROVAL, default=True)

    def return_approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_RETURN_APPROVAL, default=True)
