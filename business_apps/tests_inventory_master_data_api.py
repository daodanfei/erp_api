from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIRequestFactory

from business_apps.inventory.models import Inventory, Product, ProductCategory, Unit
from business_apps.inventory.services import InventoryService
from business_apps.inventory.serializers import ProductCategorySerializer, ProductSerializer, StocktakeSerializer
from business_apps.inventory.models import Stocktake, Warehouse
from business_apps.inventory.views import StocktakeViewSet, WarehouseViewSet
from business_apps.supply_chain.models import TransferOrder
from business_apps.supply_chain.serializers import TransferOrderSerializer
from business_apps.supply_chain.services import TransferService
from business_apps.inventory.views import ProductCategoryViewSet
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant


class InventoryMasterDataValidationTest(TestCase):
    def test_product_serializer_rejects_disabled_category(self):
        category = ProductCategory.objects.create(name="禁用分类", status=False)
        unit = Unit.objects.create(name="件", code="INV-UNIT-001", status=True)

        serializer = ProductSerializer(
            data={
                "name": "测试商品",
                "category": category.id,
                "unit": unit.id,
                "status": "ACTIVE",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("禁用商品分类不能用于商品", str(serializer.errors["category"]))

    def test_product_serializer_rejects_disabled_unit(self):
        category = ProductCategory.objects.create(name="有效分类", status=True)
        unit = Unit.objects.create(name="禁用单位", code="INV-UNIT-002", status=False)

        serializer = ProductSerializer(
            data={
                "name": "测试商品",
                "category": category.id,
                "unit": unit.id,
                "status": "ACTIVE",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("禁用计量单位不能用于商品", str(serializer.errors["unit"]))

    def test_category_serializer_rejects_disabled_parent(self):
        parent = ProductCategory.objects.create(name="禁用父分类", status=False)
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, tenant=SimpleNamespace(id=1))
        )
        serializer = ProductCategorySerializer(
            data={
                "name": "子分类",
                "parent": parent.id,
                "status": True,
            },
            context={"request": request},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("禁用分类不能作为上级分类", str(serializer.errors["parent"]))

    def test_stocktake_serializer_rejects_disabled_warehouse(self):
        warehouse = Warehouse.objects.create(
            warehouse_code="INV-WH-001",
            warehouse_name="禁用仓库",
            status=False,
        )

        serializer = StocktakeSerializer(
            data={
                "stocktake_no": "STK-001",
                "warehouse": warehouse.id,
                "status": "DRAFT",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("禁用仓库不能用于业务", str(serializer.errors["warehouse"]))

    def test_transfer_serializer_rejects_disabled_warehouse(self):
        from_warehouse = Warehouse.objects.create(
            warehouse_code="INV-WH-002",
            warehouse_name="禁用调出仓",
            status=False,
        )
        to_warehouse = Warehouse.objects.create(
            warehouse_code="INV-WH-003",
            warehouse_name="启用调入仓",
            status=True,
        )

        serializer = TransferOrderSerializer(
            data={
                "from_warehouse": from_warehouse.id,
                "to_warehouse": to_warehouse.id,
                "status": "DRAFT",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("禁用仓库不能用于业务", str(serializer.errors["from_warehouse"]))


class ProductCategoryDestroyGuardTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_destroy_rejects_when_used_by_product(self):
        category = ProductCategory.objects.create(name="被引用分类", status=True)
        unit = Unit.objects.create(name="件", code="INV-UNIT-003", status=True)
        Product.objects.create(
            product_code="INV-PRO-001",
            name="引用商品",
            category=category,
            unit=unit,
            status="ACTIVE",
        )

        request = self.factory.delete(f"/api/inventory/categories/{category.id}/")
        view = ProductCategoryViewSet()
        view.request = request
        view.get_object = lambda: category

        response = view.destroy(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("已有商品使用该分类", response.data["detail"])

    def test_destroy_rejects_when_has_children(self):
        parent = ProductCategory.objects.create(name="父分类", status=True)
        ProductCategory.objects.create(name="子分类", parent=parent, status=True)

        request = self.factory.delete(f"/api/inventory/categories/{parent.id}/")
        view = ProductCategoryViewSet()
        view.request = request
        view.get_object = lambda: parent

        response = view.destroy(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("存在下级分类", response.data["detail"])


class WarehouseGuardTest(TestCase):
    def _single_warehouse_runtime_config(self, tenant):
        return SimpleNamespace(
            tenant=tenant,
            is_enabled=lambda module_key: module_key == "inventory",
            is_feature_enabled=lambda module_key, feature_key: False,
            get_default=lambda key, default=None, module_key=None: "MAIN",
        )

    def test_default_warehouse_cannot_be_disabled_in_single_warehouse_mode(self):
        tenant = Tenant.objects.create(code="tenant-wh-guard", name="Tenant WH Guard", status="ACTIVE")
        warehouse = Warehouse.objects.create(
            tenant=tenant,
            warehouse_code="MAIN",
            warehouse_name="默认仓库",
            status=True,
        )

        with self.assertRaisesMessage(ValueError, "不能停用默认仓库"):
            InventoryService.validate_warehouse_can_be_disabled(
                warehouse=warehouse,
                runtime_config=self._single_warehouse_runtime_config(tenant),
            )

    def test_default_warehouse_cannot_be_deleted_in_single_warehouse_mode(self):
        tenant = Tenant.objects.create(code="tenant-wh-delete", name="Tenant WH Delete", status="ACTIVE")
        warehouse = Warehouse.objects.create(
            tenant=tenant,
            warehouse_code="MAIN",
            warehouse_name="默认仓库",
            status=True,
        )

        with self.assertRaisesMessage(ValueError, "不能删除默认仓库"):
            InventoryService.validate_warehouse_can_be_deleted(
                warehouse=warehouse,
                runtime_config=self._single_warehouse_runtime_config(tenant),
            )

    def test_warehouse_destroy_returns_400_with_business_reason(self):
        tenant = Tenant.objects.create(code="tenant-wh-api", name="Tenant WH API", status="ACTIVE")
        category = ProductCategory.objects.create(tenant=tenant, name="仓库删除分类", status=True)
        unit = Unit.objects.create(tenant=tenant, name="件", code="INV-UNIT-WH-DEL-001", status=True)
        product = Product.objects.create(
            tenant=tenant,
            product_code="INV-WH-DEL-001",
            name="仓库删除商品",
            category=category,
            unit=unit,
            status="ACTIVE",
        )
        warehouse = Warehouse.objects.create(
            tenant=tenant,
            warehouse_code="WH-DELETE-001",
            warehouse_name="历史仓库",
            status=True,
        )
        Inventory.objects.create(
            tenant=tenant,
            warehouse=warehouse,
            product=product,
            current_qty=0,
            locked_qty=0,
        )
        user = ERPUser.objects.create_user(
            tenant=tenant,
            username="warehouse_delete_user",
            password="password",
            must_change_password=False,
        )
        request = APIRequestFactory().delete(f"/api/inventory/warehouses/{warehouse.id}/")
        request.user = user
        request.tenant = tenant
        view = WarehouseViewSet()
        view.request = request
        view.action = "destroy"

        with patch("business_apps.inventory.views.TenantService.get_runtime_config", return_value=self._single_warehouse_runtime_config(tenant)):
            with self.assertRaises(ValidationError) as exc:
                view.perform_destroy(warehouse)

        self.assertEqual(exc.exception.detail["detail"].code, "invalid")
        self.assertEqual(str(exc.exception.detail["detail"]), "仓库已存在库存台账记录，不能删除")

    def test_stocktake_create_returns_400_when_default_warehouse_unavailable(self):
        tenant = Tenant.objects.create(code="tenant-stocktake-create", name="Tenant Stocktake Create", status="ACTIVE")
        user = ERPUser.objects.create_user(
            tenant=tenant,
            username="stocktake_create_user",
            password="password",
            must_change_password=False,
        )
        serializer = Mock()
        serializer.validated_data = {"warehouse": None}
        stocktake_view = StocktakeViewSet()
        stocktake_view.request = SimpleNamespace(user=user)

        fake_policy = Mock()
        fake_policy.resolve_warehouse.side_effect = ValueError("未找到可用默认仓库，请先配置仓库")

        with patch("business_apps.inventory.views.get_policy", return_value=fake_policy):
            with self.assertRaises(ValidationError) as exc:
                stocktake_view.perform_create(serializer)

        self.assertEqual(str(exc.exception.detail["detail"]), "未找到可用默认仓库，请先配置仓库")


class TransferOrderQuantityValidationTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            code="tenant-transfer-qty",
            name="Tenant Transfer Qty",
            status="ACTIVE",
        )
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="transfer_qty_user",
            password="password",
            must_change_password=False,
        )
        self.category = ProductCategory.objects.create(
            tenant=self.tenant,
            name="调拨分类",
            status=True,
        )
        self.unit = Unit.objects.create(
            tenant=self.tenant,
            name="件",
            code="INV-UNIT-TRANSFER-001",
            status=True,
        )
        self.product = Product.objects.create(
            tenant=self.tenant,
            product_code="INV-TRANSFER-001",
            name="调拨商品",
            category=self.category,
            unit=self.unit,
            status="ACTIVE",
            created_by=self.user,
        )
        self.from_warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="INV-TR-WH-001",
            warehouse_name="调出仓",
            status=True,
        )
        self.to_warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="INV-TR-WH-002",
            warehouse_name="调入仓",
            status=True,
        )
        Inventory.objects.create(
            tenant=self.tenant,
            warehouse=self.from_warehouse,
            product=self.product,
            current_qty=Decimal("10"),
            locked_qty=Decimal("4"),
        )

    def _policy(self):
        return SimpleNamespace(
            transfer_enabled=lambda: True,
            transfer_approval_enabled=lambda: True,
        )

    @patch("business_apps.supply_chain.services.get_policy")
    def test_create_order_rejects_quantity_above_available_stock(self, mocked_get_policy):
        mocked_get_policy.return_value = self._policy()

        with self.assertRaisesMessage(ValueError, "调出仓库可用库存不足：调拨商品，可用库存6.000，调拨数量6.500"):
            TransferService.create_order(
                self.from_warehouse,
                self.to_warehouse,
                [{"product": self.product, "quantity": Decimal("6.5")}],
                self.user,
            )

    @patch("business_apps.supply_chain.services.get_policy")
    def test_update_order_rejects_aggregated_duplicate_item_quantity_above_available_stock(self, mocked_get_policy):
        mocked_get_policy.return_value = self._policy()
        order = TransferOrder.objects.create(
            tenant=self.tenant,
            transfer_no="TR-TEST-001",
            from_warehouse=self.from_warehouse,
            to_warehouse=self.to_warehouse,
            status="DRAFT",
            created_by=self.user,
        )

        with self.assertRaisesMessage(ValueError, "调出仓库可用库存不足：调拨商品，可用库存6.000，调拨数量7.000"):
            TransferService.update_order(
                order,
                self.from_warehouse,
                self.to_warehouse,
                [
                    {"product": self.product, "quantity": Decimal("3")},
                    {"product": self.product, "quantity": Decimal("4")},
                ],
                self.user,
            )


class StocktakeApprovalWorkflowTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            code="tenant-stocktake-approval",
            name="Tenant Stocktake Approval",
            status="ACTIVE",
        )
        self.creator = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="stocktake_creator",
            password="password",
            must_change_password=False,
        )
        self.approver = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="stocktake_approver",
            password="password",
            must_change_password=False,
        )
        self.warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="STK-WH-001",
            warehouse_name="盘点仓库",
            status=True,
        )

    def _runtime_config(self, approval_enabled: bool):
        return SimpleNamespace(
            tenant=self.tenant,
            is_enabled=lambda module_key: module_key == "inventory",
            is_feature_enabled=lambda module_key, feature_key: (
                feature_key == "stocktake" or (feature_key == "stocktake_approval" and approval_enabled)
            ),
            get_default=lambda key, default=None, module_key=None: "MAIN",
        )

    def _create_stocktake(self, status="DRAFT"):
        return Stocktake.objects.create(
            tenant=self.tenant,
            stocktake_no=f"STK-{Stocktake.objects.count() + 1:03d}",
            warehouse=self.warehouse,
            status=status,
            created_by=self.creator,
        )

    def test_submit_moves_to_pending_approval_when_feature_enabled(self):
        stocktake = self._create_stocktake()

        InventoryService.submit_stocktake(
            stocktake=stocktake,
            operator=self.creator,
            runtime_config=self._runtime_config(True),
        )

        stocktake.refresh_from_db()
        self.assertEqual(stocktake.status, "PENDING_APPROVAL")
        self.assertEqual(stocktake.submitted_by, self.creator)
        self.assertIsNone(stocktake.approved_by)
        self.assertIsNotNone(stocktake.submitted_at)

    def test_submit_auto_approves_when_feature_disabled(self):
        stocktake = self._create_stocktake()

        InventoryService.submit_stocktake(
            stocktake=stocktake,
            operator=self.creator,
            runtime_config=self._runtime_config(False),
        )

        stocktake.refresh_from_db()
        self.assertEqual(stocktake.status, "APPROVED")
        self.assertEqual(stocktake.submitted_by, self.creator)
        self.assertEqual(stocktake.approved_by, self.creator)
        self.assertIsNotNone(stocktake.approved_at)

    def test_approve_rejects_creator_or_submitter(self):
        stocktake = self._create_stocktake(status="PENDING_APPROVAL")
        stocktake.submitted_by = self.creator
        stocktake.save(update_fields=["submitted_by"])

        with self.assertRaisesMessage(ValueError, "审核人不能是盘点单创建人或提交人"):
            InventoryService.approve_stocktake(
                stocktake=stocktake,
                operator=self.creator,
                runtime_config=self._runtime_config(True),
            )

    def test_complete_requires_approved_status_when_feature_enabled(self):
        stocktake = self._create_stocktake(status="PENDING_APPROVAL")

        with self.assertRaisesMessage(ValueError, "只有已审核的盘点单可以完成"):
            InventoryService.complete_stocktake(
                stocktake=stocktake,
                operator=self.approver,
                runtime_config=self._runtime_config(True),
            )

    def test_disable_warehouse_rejects_pending_or_approved_stocktake(self):
        Stocktake.objects.create(
            tenant=self.tenant,
            stocktake_no="STK-PENDING-001",
            warehouse=self.warehouse,
            status="PENDING_APPROVAL",
            created_by=self.creator,
        )

        with self.assertRaisesMessage(ValueError, "仓库仍有关联的未完成盘点单，不能停用"):
            InventoryService.validate_warehouse_can_be_disabled(
                warehouse=self.warehouse,
                runtime_config=self._runtime_config(True),
            )
