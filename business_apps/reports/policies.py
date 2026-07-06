from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_CUSTOMER_ANALYSIS,
    FEATURE_DASHBOARD,
    FEATURE_EXPORT_CENTER,
    FEATURE_INVENTORY_ANALYSIS,
    FEATURE_PRODUCT_ANALYSIS,
    FEATURE_PURCHASE_ANALYSIS,
    FEATURE_SALES_ANALYSIS,
    FEATURE_SUPPLIER_ANALYSIS,
)


class ReportsPolicy(BasePolicy):
    module_key = "reports"

    def dashboard_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_DASHBOARD, default=True)

    def sales_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SALES_ANALYSIS, default=True)

    def purchase_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PURCHASE_ANALYSIS, default=True)

    def inventory_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_INVENTORY_ANALYSIS, default=True)

    def customer_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_ANALYSIS, default=True)

    def supplier_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_ANALYSIS, default=True)

    def product_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PRODUCT_ANALYSIS, default=True)

    def export_center_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_EXPORT_CENTER, default=True)
