from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_APPROVAL,
    FEATURE_CREDIT_CONTROL,
    FEATURE_CUSTOMER_BLACKLIST_BLOCK,
    FEATURE_OUTBOUND_AUTO_AR,
    FEATURE_PARTIAL_SHIPMENT,
    FEATURE_PRICE_EDITABLE,
    FIELD_SALES_ORDER_APPROVER,
    FIELD_SALES_ORDER_ITEM_WAREHOUSE,
    WORKFLOW_SALES_ORDER_SUBMIT,
)
from .models import SalesOrder


class SalesPolicy(BasePolicy):
    module_key = "sales"

    def approval_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_APPROVAL, default=True)

    def credit_control_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CREDIT_CONTROL, default=True)

    def partial_shipment_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_PARTIAL_SHIPMENT, default=True)

    def outbound_auto_ar_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_OUTBOUND_AUTO_AR, default=True)

    def customer_blacklist_block(self) -> bool:
        return self.is_feature_enabled(FEATURE_CUSTOMER_BLACKLIST_BLOCK, default=True)

    def price_editable(self) -> bool:
        return self.is_feature_enabled(FEATURE_PRICE_EDITABLE, default=True)

    def get_submit_workflow(self) -> str:
        if not self.approval_enabled():
            return "auto_approve"
        return self.get_workflow(WORKFLOW_SALES_ORDER_SUBMIT, default="manual_approve")

    def next_submit_status(self) -> str:
        if self.get_submit_workflow() == "auto_approve":
            return SalesOrder.STATUS_APPROVED
        return SalesOrder.STATUS_PENDING_APPROVAL

    def get_field_rule(self, field_key):
        configured = super().get_field_rule(field_key, default=None)
        if configured is not None:
            return configured
        if field_key == FIELD_SALES_ORDER_APPROVER and not self.approval_enabled():
            return {"visible": False, "required": False, "readonly": True}
        if field_key == FIELD_SALES_ORDER_ITEM_WAREHOUSE:
            return {"visible": True, "required": False, "readonly": False}
        return {"visible": True, "required": False, "readonly": False}
