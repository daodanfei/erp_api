from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_ALLOCATION_ENABLED,
    FEATURE_ALLOW_PARTIAL_PAYMENT,
    FEATURE_AUTO_CREATE_PAYABLE,
    FEATURE_PAYMENT_APPROVAL,
    FEATURE_SUPPLIER_RECONCILIATION_ENABLED,
    FEATURE_WRITEOFF_ENABLED,
)


class APPayablePolicy(BasePolicy):
    module_key = "ap_payable"

    def auto_create_payable_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_AUTO_CREATE_PAYABLE, default=True)

    def payment_approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PAYMENT_APPROVAL, default=True)

    def allow_partial_payment(self) -> bool:
        return self.is_feature_enabled(FEATURE_ALLOW_PARTIAL_PAYMENT, default=True)

    def supplier_reconciliation_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_RECONCILIATION_ENABLED, default=True)

    def allocation_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_ALLOCATION_ENABLED, default=True)

    def writeoff_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_WRITEOFF_ENABLED, default=True)
