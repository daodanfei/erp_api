from types import SimpleNamespace

from django.test import RequestFactory, TestCase

from business_apps.inventory.models import Product, ProductCategory, Unit
from business_apps.inventory.services import InventoryService
from business_apps.inventory.serializers import ProductCategorySerializer, ProductSerializer, StocktakeSerializer
from business_apps.inventory.models import Warehouse
from business_apps.supply_chain.serializers import TransferOrderSerializer
from business_apps.inventory.views import ProductCategoryViewSet
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
