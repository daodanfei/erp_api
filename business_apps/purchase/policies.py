from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_APPROVAL,
    FEATURE_EXPECTED_ARRIVAL_REQUIRED,
    FEATURE_PARTIAL_RECEIPT,
    FEATURE_PURCHASE_RETURN,
    FEATURE_RECEIPT_AUTO_AP,
    FEATURE_SUPPLIER_BLACKLIST_BLOCK,
    FIELD_PURCHASE_ORDER_APPROVER,
    FIELD_PURCHASE_ORDER_EXPECTED_ARRIVAL_DATE,
    WORKFLOW_PURCHASE_ORDER_SUBMIT,
)
from .models import PurchaseOrder


class PurchasePolicy(BasePolicy):
    module_key = "purchase"

    def approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_APPROVAL, default=True)

    def partial_receipt_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PARTIAL_RECEIPT, default=True)

    def purchase_return_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PURCHASE_RETURN, default=True)

    def receipt_auto_ap_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_RECEIPT_AUTO_AP, default=True)

    def expected_arrival_required(self) -> bool:
        return self.is_feature_enabled(FEATURE_EXPECTED_ARRIVAL_REQUIRED, default=False)

    def supplier_blacklist_block(self) -> bool:
        return self.is_feature_enabled(FEATURE_SUPPLIER_BLACKLIST_BLOCK, default=True)

    def get_submit_workflow(self) -> str:
        if not self.approval_enabled():
            return "auto_approve"
        return self.get_workflow(WORKFLOW_PURCHASE_ORDER_SUBMIT, default="manual_approve")

    def next_submit_status(self) -> str:
        if self.get_submit_workflow() == "auto_approve":
            return PurchaseOrder.STATUS_APPROVED
        return PurchaseOrder.STATUS_PENDING_APPROVAL

    def get_field_rule(self, field_key):
        configured = super().get_field_rule(field_key, default=None)
        if configured is not None:
            return configured
        if field_key == FIELD_PURCHASE_ORDER_APPROVER and not self.approval_enabled():
            return {"visible": False, "required": False, "readonly": True}
        if field_key == FIELD_PURCHASE_ORDER_EXPECTED_ARRIVAL_DATE:
            return {"visible": True, "required": self.expected_arrival_required(), "readonly": False}
        return {"visible": True, "required": False, "readonly": True}
