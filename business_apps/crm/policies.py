from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_CREDIT_LIMIT_ENABLED,
    FEATURE_CUSTOMER_APPROVAL,
    FEATURE_CUSTOMER_ATTACHMENT_ENABLED,
    FEATURE_CUSTOMER_CODE_AUTO_GENERATE,
    FEATURE_CUSTOMER_TRANSFER_ENABLED,
    FEATURE_FOLLOW_RECORD_ENABLED,
)


class CustomerPolicy(BasePolicy):
    module_key = "crm"

    def approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_APPROVAL, default=False)

    def code_auto_generate_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_CODE_AUTO_GENERATE, default=True)

    def credit_limit_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CREDIT_LIMIT_ENABLED, default=True)

    def follow_record_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_FOLLOW_RECORD_ENABLED, default=True)

    def transfer_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_TRANSFER_ENABLED, default=True)

    def attachment_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_ATTACHMENT_ENABLED, default=True)
