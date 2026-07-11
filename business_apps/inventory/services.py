from decimal import Decimal

from django.db import transaction, models
from django.utils import timezone
from core_apps.erp_auth.models import ERPUser
from .models import Product, Warehouse, Inventory, InventoryTransaction, Stocktake, StocktakeItem
from business_apps.platform.services import CodeRuleService
from business_apps.inventory.policies import InventoryPolicy
from core_apps.erp_auth.compat import build_erp_user_fk_kwargs
from core_apps.policies.registry import get_policy
from .warehouse_utils import find_default_warehouse

COMMON_UNIT_NAMES = [
    "个",
    "件",
    "箱",
    "盒",
    "包",
    "袋",
    "瓶",
    "桶",
    "罐",
    "台",
    "套",
    "只",
    "支",
    "条",
    "卷",
    "千克",
    "克",
    "吨",
    "升",
    "毫升",
    "米",
    "厘米",
    "平方米",
    "立方米",
]

FOUR_DECIMAL_PLACES = Decimal("0.0001")

class InventoryService:
    @staticmethod
    def get_policy(*, user=None, runtime_config=None):
        if runtime_config is not None:
            return InventoryPolicy(runtime_config)
        return get_policy("inventory", user=user)

    @staticmethod
    def _normalize_quantity(quantity):
        return quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))

    @staticmethod
    def _resolve_business_date(business_date=None):
        return business_date or timezone.localdate()

    @staticmethod
    def _resolve_tenant(*candidates):
        for candidate in candidates:
            if candidate is None:
                continue
            tenant = getattr(candidate, "tenant", None)
            if tenant is not None:
                return tenant
            if isinstance(candidate, ERPUser):
                return candidate.tenant
        return None

    @staticmethod
    def _build_transaction_payload(
        warehouse,
        product,
        transaction_type,
        quantity,
        before_qty,
        after_qty,
        operator,
        reference_type=None,
        reference_id=None,
        remark=None,
        business_date=None,
        unit_cost=None,
        total_cost=None,
        transaction_no_rule='INVENTORY_TRANSACTION',
    ):
        normalized_quantity = InventoryService._normalize_quantity(quantity)
        normalized_unit_cost = None if unit_cost is None else InventoryService._normalize_quantity(unit_cost)
        normalized_total_cost = None if total_cost is None else InventoryService._normalize_quantity(total_cost)
        if normalized_unit_cost is not None and normalized_total_cost is None:
            normalized_total_cost = (normalized_quantity.copy_abs() * normalized_unit_cost).quantize(
                FOUR_DECIMAL_PLACES
            )

        return {
            'tenant': InventoryService._resolve_tenant(warehouse, product, operator),
            'transaction_no': CodeRuleService.generate(transaction_no_rule),
            'business_date': InventoryService._resolve_business_date(business_date),
            'warehouse': warehouse,
            'product': product,
            'transaction_type': transaction_type,
            'direction': (
                InventoryTransaction.DIRECTION_IN
                if normalized_quantity > 0
                else InventoryTransaction.DIRECTION_OUT
            ),
            'quantity': normalized_quantity,
            'before_qty': before_qty,
            'after_qty': after_qty,
            'reference_type': reference_type,
            'reference_id': reference_id,
            'remark': remark,
            'unit_cost': normalized_unit_cost,
            'total_cost': normalized_total_cost,
            **build_erp_user_fk_kwargs(
                InventoryTransaction,
                user=operator,
                field_names=("operator",),
            ),
        }

    @staticmethod
    def _create_transaction(**payload):
        return InventoryTransaction.objects.create(**payload)

    @staticmethod
    def _sync_product_stock_cache(product):
        total_stock = Inventory.objects.filter(product=product).aggregate(total=models.Sum('current_qty'))['total'] or 0
        product.current_stock = total_stock
        product.save(update_fields=['current_stock'])
        return total_stock

    @staticmethod
    def on_inventory_increased(*, inventory, transaction_payload):
        return None

    @staticmethod
    def on_inventory_decreased(*, inventory, transaction_payload):
        return None

    @staticmethod
    @transaction.atomic
    def ensure_stocktake_items(stocktake):
        """
        Initializes stocktake items from current warehouse inventory once.
        Existing manual changes are preserved.
        """
        if stocktake.items.exists():
            return 0

        inventories = (
            Inventory.objects.filter(warehouse=stocktake.warehouse)
            .select_related("product")
            .order_by("product_id")
        )
        items = [
            StocktakeItem(
                tenant=stocktake.tenant,
                stocktake=stocktake,
                product=inventory.product,
                system_qty=inventory.current_qty,
                actual_qty=inventory.current_qty,
            )
            for inventory in inventories
        ]
        StocktakeItem.objects.bulk_create(items)
        return len(items)

    @staticmethod
    @transaction.atomic
    def change_stock(
        warehouse,
        product,
        quantity,
        transaction_type,
        operator,
        reference_type=None,
        reference_id=None,
        remark=None,
        business_date=None,
        unit_cost=None,
        total_cost=None,
    ):
        """
        Unified service for all stock changes.
        quantity: positive for increment, negative for decrement.
        """
        quantity = InventoryService._normalize_quantity(quantity)
        policy = InventoryService.get_policy(user=operator)
        warehouse = policy.resolve_warehouse(warehouse)
        # 1. Lock the inventory record for concurrency control (SELECT FOR UPDATE)
        # Use select_for_update to avoid race conditions and over-selling
        inventory, _created = Inventory.objects.select_for_update().get_or_create(
            warehouse=warehouse,
            product=product,
            defaults={
                'tenant': InventoryService._resolve_tenant(warehouse, product, operator),
                'current_qty': 0,
                'locked_qty': 0,
            }
        )

        before_qty = inventory.current_qty
        after_qty = before_qty + quantity

        if after_qty < 0:
            raise ValueError(f"库存不足：{product.name} 在 {warehouse.warehouse_name} 的可用库存不足以扣减 {abs(quantity)}")

        # 2. Update Inventory cache table
        inventory.current_qty = after_qty
        inventory.save()

        # 3. Create Transaction record (Source of Truth)
        transaction_payload = InventoryService._build_transaction_payload(
            warehouse=warehouse,
            product=product,
            transaction_type=transaction_type,
            quantity=quantity,
            before_qty=before_qty,
            after_qty=after_qty,
            operator=operator,
            reference_type=reference_type,
            reference_id=reference_id,
            remark=remark,
            business_date=business_date,
            unit_cost=unit_cost,
            total_cost=total_cost,
        )
        InventoryService._create_transaction(**transaction_payload)

        # 4. Sync product current_stock cache (for quick listing)
        InventoryService._sync_product_stock_cache(product)

        if quantity > 0:
            InventoryService.on_inventory_increased(inventory=inventory, transaction_payload=transaction_payload)
        else:
            InventoryService.on_inventory_decreased(inventory=inventory, transaction_payload=transaction_payload)

        return inventory

    @staticmethod
    @transaction.atomic
    def reserve_stock(
        warehouse,
        product,
        quantity,
        operator=None,
        reference_type=None,
        reference_id=None,
        remark=None,
        business_date=None,
    ):
        """
        Locks/Reserves stock for an order. Decreases available_qty but current_qty stays same.
        """
        quantity = InventoryService._normalize_quantity(quantity)
        policy = InventoryService.get_policy(user=operator)
        warehouse = policy.resolve_warehouse(warehouse)
        inventory, _created = Inventory.objects.select_for_update().get_or_create(
            warehouse=warehouse,
            product=product,
            defaults={
                'tenant': InventoryService._resolve_tenant(warehouse, product, operator),
                'current_qty': 0,
                'locked_qty': 0,
            }
        )
        
        if inventory.available_qty < quantity:
            raise ValueError(f"可用库存不足以锁定：{product.name} 缺少 {quantity - inventory.available_qty}")
            
        inventory.locked_qty += quantity
        inventory.save()
        return inventory

    @staticmethod
    @transaction.atomic
    def release_stock(
        warehouse,
        product,
        quantity,
        operator=None,
        reference_type=None,
        reference_id=None,
        remark=None,
        business_date=None,
    ):
        """
        Releases reserved stock. Used when an order is cancelled.
        """
        quantity = InventoryService._normalize_quantity(quantity)
        policy = InventoryService.get_policy(user=operator)
        warehouse = policy.resolve_warehouse(warehouse)
        inventory = Inventory.objects.select_for_update().get(warehouse=warehouse, product=product)
        inventory.locked_qty = max(0, inventory.locked_qty - quantity)
        inventory.save()
        return inventory

    @staticmethod
    @transaction.atomic
    def ship_stock(
        warehouse,
        product,
        quantity,
        operator,
        reference_type=None,
        reference_id=None,
        remark=None,
        business_date=None,
        unit_cost=None,
        total_cost=None,
    ):
        """
        Final shipment step: Decreases current_qty AND releases locked_qty.
        Generates SALE_OUT transaction.
        """
        quantity = InventoryService._normalize_quantity(quantity)
        policy = InventoryService.get_policy(user=operator)
        warehouse = policy.resolve_warehouse(warehouse)
        inventory = Inventory.objects.select_for_update().get(warehouse=warehouse, product=product)
        
        before_qty = inventory.current_qty
        
        # 1. Release lock
        inventory.locked_qty = max(0, inventory.locked_qty - quantity)
        
        # 2. Decrease current qty
        inventory.current_qty -= quantity
        if inventory.current_qty < 0:
            raise ValueError(f"实盘库存不足以发货：{product.name}")
        
        inventory.save()

        # 3. Transaction log
        transaction_payload = InventoryService._build_transaction_payload(
            warehouse=warehouse,
            product=product,
            transaction_type='SALE_OUT',
            quantity=-quantity,
            before_qty=before_qty,
            after_qty=inventory.current_qty,
            operator=operator,
            reference_type=reference_type,
            reference_id=reference_id,
            remark=remark,
            business_date=business_date,
            unit_cost=unit_cost,
            total_cost=total_cost,
            transaction_no_rule='SHIPMENT',
        )
        InventoryService._create_transaction(**transaction_payload)

        # 4. Sync product cache
        InventoryService._sync_product_stock_cache(product)
        InventoryService.on_inventory_decreased(inventory=inventory, transaction_payload=transaction_payload)

        return inventory

    @staticmethod
    @transaction.atomic
    def complete_stocktake(stocktake, operator):
        """Processes a stocktake and creates necessary adjustments"""
        if stocktake.status != 'IN_PROGRESS':
            raise ValueError("只有处理中的盘点单可以完成")

        adjustments = []
        for item in stocktake.items.all():
            diff = item.difference_qty
            if diff != 0:
                trx_type = 'STOCKTAKE_GAIN' if diff > 0 else 'STOCKTAKE_LOSS'
                InventoryService.change_stock(
                    warehouse=stocktake.warehouse,
                    product=item.product,
                    quantity=diff,
                    transaction_type=trx_type,
                    operator=operator,
                    reference_type='STOCKTAKE',
                    reference_id=stocktake.id,
                    remark=f"盘点单: {stocktake.stocktake_no} 差异调整",
                    business_date=timezone.localdate(),
                )
                adjustments.append(
                    {
                        'product_id': item.product_id,
                        'product_name': item.product.name,
                        'transaction_type': trx_type,
                        'direction': (
                            InventoryTransaction.DIRECTION_IN
                            if diff > 0
                            else InventoryTransaction.DIRECTION_OUT
                        ),
                        'quantity': str(diff),
                        'system_qty': str(item.system_qty),
                        'actual_qty': str(item.actual_qty),
                    }
                )
        
        stocktake.status = 'COMPLETED'
        stocktake.completed_at = timezone.now()
        stocktake.save(update_fields=['status', 'completed_at'])
        return {
            'stocktake_id': stocktake.id,
            'stocktake_no': stocktake.stocktake_no,
            'adjustment_count': len(adjustments),
            'adjustments': adjustments,
        }

    @staticmethod
    def get_default_warehouse(*, tenant, runtime_config=None):
        default_code = "MAIN"
        if runtime_config is not None:
            policy = InventoryPolicy(runtime_config)
            default_code = policy.get_default_warehouse_code() or "MAIN"
        return find_default_warehouse(tenant=tenant, configured_code=default_code, active_only=False)

    @staticmethod
    def validate_warehouse_can_be_disabled(*, warehouse: Warehouse, runtime_config) -> None:
        default_warehouse = InventoryService.get_default_warehouse(tenant=warehouse.tenant, runtime_config=runtime_config)
        policy = InventoryPolicy(runtime_config)
        if (
            default_warehouse is not None
            and default_warehouse.id == warehouse.id
            and not policy.is_multi_warehouse_enabled()
            and not policy.warehouse_required_on_transaction()
        ):
            raise ValueError("单仓模式下不能停用默认仓库，请先调整蓝图默认仓库或切换仓库模式")

        if Inventory.objects.filter(warehouse=warehouse).exclude(current_qty=0, locked_qty=0).exists():
            raise ValueError("仓库仍有库存或锁定库存，不能停用")

        if Stocktake.objects.filter(warehouse=warehouse, status__in=("DRAFT", "IN_PROGRESS")).exists():
            raise ValueError("仓库仍有关联的草稿/进行中盘点单，不能停用")

    @staticmethod
    def validate_warehouse_can_be_deleted(*, warehouse: Warehouse, runtime_config) -> None:
        default_warehouse = InventoryService.get_default_warehouse(tenant=warehouse.tenant, runtime_config=runtime_config)
        policy = InventoryPolicy(runtime_config)
        if (
            default_warehouse is not None
            and default_warehouse.id == warehouse.id
            and not policy.is_multi_warehouse_enabled()
            and not policy.warehouse_required_on_transaction()
        ):
            raise ValueError("单仓模式下不能删除默认仓库，请先调整蓝图默认仓库或切换仓库模式")

        if Inventory.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已存在库存台账记录，不能删除")
        if InventoryTransaction.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已存在库存流水记录，不能删除")
        if Stocktake.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已存在盘点单记录，不能删除")

        from business_apps.purchase.models import PurchaseOrderItem, PurchaseReceipt
        from business_apps.sales.models import SalesOrderItem
        from business_apps.supply_chain.models import (
            OutboundOrder,
            PurchaseReturnOrder,
            SalesReturnOrder,
            TransferOrder,
        )

        if PurchaseOrderItem.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已被采购订单明细引用，不能删除")
        if PurchaseReceipt.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已被采购入库单引用，不能删除")
        if SalesOrderItem.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已被销售订单明细引用，不能删除")
        if OutboundOrder.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已被销售出库单引用，不能删除")
        if TransferOrder.objects.filter(models.Q(from_warehouse=warehouse) | models.Q(to_warehouse=warehouse)).exists():
            raise ValueError("仓库已被调拨单引用，不能删除")
        if SalesReturnOrder.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已被销售退货单引用，不能删除")
        if PurchaseReturnOrder.objects.filter(warehouse=warehouse).exists():
            raise ValueError("仓库已被采购退货单引用，不能删除")


class UnitService:
    @staticmethod
    @transaction.atomic
    def init_common_units():
        """Create common units once and keep existing units unchanged."""
        from .models import Unit

        created_units = []
        for unit_name in COMMON_UNIT_NAMES:
            unit = Unit.objects.filter(name=unit_name).first()
            if unit:
                if not unit.status:
                    unit.status = True
                    unit.save(update_fields=["status"])
                continue

            created_units.append(
                Unit.objects.create(name=unit_name, code=generate_unit_code(), status=True)
            )
        return created_units

def generate_stocktake_no():
    return CodeRuleService.generate('STOCKTAKE')

def generate_product_code():
    """Generates a code in format PRO2026050001"""
    return CodeRuleService.generate('PRODUCT_CODE')

def generate_unit_code():
    """Generates a stable unit code such as UNIT0001."""
    return CodeRuleService.generate('UNIT_CODE')

def generate_warehouse_code():
    """Generates a stable warehouse code such as WH0001."""
    return CodeRuleService.generate('WAREHOUSE_CODE')

def check_duplicate_product(name, barcode=None, exclude_id=None, tenant=None):
    """Checks if a product already exists with same name or barcode"""
    from .models import Product
    q = Product.objects.filter(is_deleted=False)
    if tenant:
        q = q.filter(tenant=tenant)
    if exclude_id:
        q = q.exclude(id=exclude_id)
        
    errors = []
    if q.filter(name=name).exists():
        errors.append("商品名称已存在")
    if barcode and q.filter(barcode=barcode).exists():
        errors.append("条码已存在")
        
    return errors

def check_can_delete_product(product):
    """Checks if a product can be deleted"""
    reasons = []
    if product.current_stock > 0:
        reasons.append("当前库存不为0")
    return reasons
