from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_AR_AP_POSTING_ENABLED,
    FEATURE_INVENTORY_POSTING_ENABLED,
    FEATURE_PERIOD_CLOSE_ENABLED,
    FEATURE_SUBJECT_EDITABLE_AFTER_INIT,
    FEATURE_VOUCHER_AUTO_POSTING,
)


class AccountingPolicy(BasePolicy):
    module_key = "accounting"

    def voucher_auto_posting_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_VOUCHER_AUTO_POSTING, default=True)

    def period_close_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PERIOD_CLOSE_ENABLED, default=True)

    def subject_editable_after_init(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUBJECT_EDITABLE_AFTER_INIT, default=True)

    def ar_ap_posting_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_AR_AP_POSTING_ENABLED, default=True)

    def inventory_posting_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_INVENTORY_POSTING_ENABLED, default=True)
