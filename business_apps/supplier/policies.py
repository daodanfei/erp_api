from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_SUPPLIER_APPROVAL,
    FEATURE_SUPPLIER_ATTACHMENT_ENABLED,
    FEATURE_SUPPLIER_CODE_AUTO_GENERATE,
    FEATURE_SUPPLIER_CREDIT_MANAGEMENT,
    FEATURE_SUPPLIER_OWNER_TRANSFER_ENABLED,
    FEATURE_SUPPLIER_RATING_ENABLED,
)


class SupplierPolicy(BasePolicy):
    module_key = "supplier"

    def approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_APPROVAL, default=False)

    def code_auto_generate_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_CODE_AUTO_GENERATE, default=True)

    def credit_management_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_CREDIT_MANAGEMENT, default=False)

    def rating_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_RATING_ENABLED, default=True)

    def attachment_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_ATTACHMENT_ENABLED, default=True)

    def owner_transfer_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_OWNER_TRANSFER_ENABLED, default=True)
