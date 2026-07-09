from __future__ import annotations

from business_apps.inventory.models import Warehouse
from core_apps.policies.base import BasePolicy

from .features import (
    DEFAULT_WAREHOUSE_CODE,
    FEATURE_BATCH_TRACKING,
    FEATURE_MULTI_WAREHOUSE,
    FEATURE_NEGATIVE_STOCK_ALLOWED,
    FEATURE_SERIAL_NUMBER,
    FEATURE_STOCKTAKE,
    FEATURE_WAREHOUSE_REQUIRED_ON_TRANSACTION,
    FIELD_INVENTORY_TRANSACTION_WAREHOUSE,
    FIELD_PURCHASE_ORDER_ITEM_WAREHOUSE,
    FIELD_SALES_ORDER_ITEM_WAREHOUSE,
    FIELD_STOCKTAKE_WAREHOUSE,
)


class InventoryPolicy(BasePolicy):
    module_key = "inventory"

    DEFAULT_FIELD_RULES = {
        FIELD_INVENTORY_TRANSACTION_WAREHOUSE: {"visible": True, "required": True, "readonly": False},
        FIELD_STOCKTAKE_WAREHOUSE: {"visible": True, "required": True, "readonly": False},
        FIELD_PURCHASE_ORDER_ITEM_WAREHOUSE: {"visible": True, "required": True, "readonly": False},
        FIELD_SALES_ORDER_ITEM_WAREHOUSE: {"visible": True, "required": True, "readonly": False},
    }

    def is_multi_warehouse_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_MULTI_WAREHOUSE, default=True)

    def batch_tracking_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_BATCH_TRACKING, default=False)

    def serial_number_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_SERIAL_NUMBER, default=False)

    def stocktake_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_STOCKTAKE, default=True)

    def negative_stock_allowed(self) -> bool:
        return self.is_feature_enabled(FEATURE_NEGATIVE_STOCK_ALLOWED, default=False)

    def warehouse_required_on_transaction(self) -> bool:
        return self.is_feature_enabled(FEATURE_WAREHOUSE_REQUIRED_ON_TRANSACTION, default=self.is_multi_warehouse_enabled())

    def get_default_warehouse_code(self) -> str | None:
        return self.get_default(DEFAULT_WAREHOUSE_CODE, default=None)

    def resolve_warehouse(self, input_warehouse):
        if self.is_multi_warehouse_enabled() or self.warehouse_required_on_transaction():
            if input_warehouse is None:
                raise ValueError("请选择仓库")
            return self._load_warehouse(input_warehouse)

        if input_warehouse is not None:
            return self._load_warehouse(input_warehouse)

        default_code = self.get_default(DEFAULT_WAREHOUSE_CODE)
        warehouse = None
        if default_code:
            warehouse = Warehouse.objects.filter(warehouse_code=default_code, status=True).first()
        if warehouse is None:
            warehouse = Warehouse.objects.filter(status=True).order_by("type", "id").first()
        if warehouse is None:
            raise ValueError("未找到可用默认仓库，请先配置仓库")
        return warehouse

    def get_field_rule(self, field_key):
        configured = super().get_field_rule(field_key, default=None)
        if configured is not None:
            return configured
        if field_key == FIELD_STOCKTAKE_WAREHOUSE and not self.stocktake_enabled():
            return {"visible": False, "required": False, "readonly": True}
        if not self.is_multi_warehouse_enabled() and not self.warehouse_required_on_transaction():
            return {"visible": False, "required": False, "readonly": True}
        return self.DEFAULT_FIELD_RULES.get(field_key, {"visible": True, "required": False, "readonly": False})

    def _load_warehouse(self, value):
        if isinstance(value, Warehouse):
            return value
        queryset = Warehouse.objects.all()
        if self.user is not None:
            from core_apps.common.viewsets import apply_erp_tenant_scope

            queryset = apply_erp_tenant_scope(queryset, user=self.user)
        return queryset.get(id=value)
