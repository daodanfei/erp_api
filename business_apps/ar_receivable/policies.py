from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_ALLOW_PARTIAL_RECEIPT,
    FEATURE_AUTO_CREATE_RECEIVABLE,
    FEATURE_CUSTOMER_RECONCILIATION_ENABLED,
    FEATURE_OVERDUE_TRACKING,
    FEATURE_RECEIPT_APPROVAL,
    FEATURE_WRITEOFF_ENABLED,
)


class ARReceivablePolicy(BasePolicy):
    module_key = "ar_receivable"

    def auto_create_receivable_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_AUTO_CREATE_RECEIVABLE, default=True)

    def receipt_approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_RECEIPT_APPROVAL, default=True)

    def allow_partial_receipt(self) -> bool:
        return self.is_feature_enabled(FEATURE_ALLOW_PARTIAL_RECEIPT, default=True)

    def overdue_tracking_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_OVERDUE_TRACKING, default=True)

    def customer_reconciliation_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_RECONCILIATION_ENABLED, default=True)

    def writeoff_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_WRITEOFF_ENABLED, default=True)
