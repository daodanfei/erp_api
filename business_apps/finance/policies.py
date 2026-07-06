from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_CASH_FLOW_ANALYSIS_ENABLED,
    FEATURE_MULTI_CASH_ACCOUNT,
    FEATURE_OPENING_BALANCE_EDITABLE,
    FEATURE_RECONCILIATION_ENABLED,
)


class FinancePolicy(BasePolicy):
    module_key = "finance"

    def multi_cash_account_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_MULTI_CASH_ACCOUNT, default=True)

    def reconciliation_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_RECONCILIATION_ENABLED, default=True)

    def opening_balance_editable(self) -> bool:
        return self.is_feature_enabled(FEATURE_OPENING_BALANCE_EDITABLE, default=False)

    def cash_flow_analysis_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CASH_FLOW_ANALYSIS_ENABLED, default=True)
