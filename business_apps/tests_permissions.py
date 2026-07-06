from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from business_apps.inventory.models import Inventory, InventoryTransaction, Product, ProductCategory, Unit, Warehouse
from business_apps.inventory.services import InventoryService
from business_apps.platform.services import CodeRuleService
from core_apps.authentication.models import Permission, Role, User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.blueprints.models import SystemInstance
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser
from core_apps.tenant.services import TenantService


class ProductPermissionApiTest(APITestCase):
    def setUp(self):
        self.view_permission = Permission.objects.create(
            name="查看商品",
            code="inventory:product:view",
            type="BUTTON",
        )
        self.update_permission = Permission.objects.create(
            name="编辑商品",
            code="inventory:product:update",
            type="BUTTON",
        )
        self.viewer_role = Role.objects.create(name="商品查看", code="product_viewer")
        self.viewer_role.permissions.add(self.view_permission)
        self.editor_role = Role.objects.create(name="商品编辑", code="product_editor")
        self.editor_role.permissions.add(self.view_permission, self.update_permission)
        self.viewer = User.objects.create_user(username="viewer", password="testpass")
        self.viewer.roles.add(self.viewer_role)
        self.editor = User.objects.create_user(username="editor", password="testpass")
        self.editor.roles.add(self.editor_role)
        self.category = ProductCategory.objects.create(name="测试分类")
        self.unit = Unit.objects.create(name="个", code="UNIT001")
        self.product = Product.objects.create(
            product_code="PRO-PERM-001",
            name="权限测试商品",
            category=self.category,
            unit=self.unit,
            sale_price=10,
            cost_price=5,
            created_by=self.editor,
        )
        self.url = f"/api/inventory/products/{self.product.id}/"

    def test_product_update_requires_update_permission(self):
        self.client.force_authenticate(self.viewer)

        response = self.client.patch(self.url, {"name": "无权修改"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "权限测试商品")

    def test_product_update_allows_user_with_update_permission(self):
        self.client.force_authenticate(self.editor)

        response = self.client.patch(self.url, {"name": "允许修改"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "允许修改")

    def test_superuser_flag_without_role_permission_does_not_bypass_business_api(self):
        superuser = User.objects.create_user(
            username="plain_superuser",
            password="testpass",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_authenticate(superuser)

        response = self.client.patch(self.url, {"name": "不应穿透"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "权限测试商品")

    def test_admin_role_without_superuser_flag_can_access_like_business_super_admin(self):
        admin_role = Role.objects.create(
            name="超级管理员",
            code="admin",
            data_scope="ALL",
        )
        admin_role.permissions.add(self.view_permission, self.update_permission)
        admin_user = User.objects.create_user(
            username="business_admin",
            password="testpass",
            is_superuser=False,
            is_staff=False,
        )
        admin_user.roles.add(admin_role)
        self.client.force_authenticate(admin_user)

        response = self.client.patch(self.url, {"name": "角色超级管理员修改"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "角色超级管理员修改")


class WarehouseCodeApiTest(APITestCase):
    def setUp(self):
        self.create_permission = Permission.objects.create(
            name="创建仓库",
            code="inventory:warehouse:create",
            type="BUTTON",
        )
        self.role = Role.objects.create(name="仓库创建", code="warehouse_creator")
        self.role.permissions.add(self.create_permission)
        self.user = User.objects.create_user(username="warehouse_user", password="testpass")
        self.user.roles.add(self.role)
        self.client.force_authenticate(self.user)

    def test_create_warehouse_generates_code(self):
        response = self.client.post(
            "/api/inventory/warehouses/",
            {"warehouse_name": "测试仓库", "type": "MAIN", "status": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        warehouse = Warehouse.objects.get(warehouse_name="测试仓库")
        self.assertEqual(warehouse.warehouse_code, "WH0001")
        self.assertEqual(response.data["warehouse_code"], "WH0001")

    def test_create_warehouse_ignores_client_code(self):
        response = self.client.post(
            "/api/inventory/warehouses/",
            {
                "warehouse_code": "MANUAL001",
                "warehouse_name": "忽略手工编码仓库",
                "type": "MAIN",
                "status": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        warehouse = Warehouse.objects.get(warehouse_name="忽略手工编码仓库")
        self.assertNotEqual(warehouse.warehouse_code, "MANUAL001")
        self.assertEqual(warehouse.warehouse_code, "WH0001")


class StocktakeApiTest(APITestCase):
    def setUp(self):
        CodeRuleService.init_default_rules()

        self.view_permission = Permission.objects.create(
            name="查看盘点单",
            code="inventory:stocktake:view",
            type="BUTTON",
        )
        self.create_permission = Permission.objects.create(
            name="创建盘点单",
            code="inventory:stocktake:create",
            type="BUTTON",
        )
        self.update_permission = Permission.objects.create(
            name="编辑盘点单",
            code="inventory:stocktake:update",
            type="BUTTON",
        )
        self.complete_permission = Permission.objects.create(
            name="完成盘点",
            code="inventory:stocktake:complete",
            type="BUTTON",
        )
        self.role = Role.objects.create(name="盘点管理员", code="stocktake_manager")
        self.role.permissions.add(
            self.view_permission,
            self.create_permission,
            self.update_permission,
            self.complete_permission,
        )

        self.user = User.objects.create_user(username="stocktake_user", password="testpass")
        self.user.roles.add(self.role)
        self.client.force_authenticate(self.user)

        self.category = ProductCategory.objects.create(name="盘点分类")
        self.unit = Unit.objects.create(name="个", code="UNIT-STOCKTAKE-01")
        self.product = Product.objects.create(
            product_code="PRO-STOCKTAKE-001",
            name="盘点商品",
            category=self.category,
            unit=self.unit,
            sale_price=10,
            cost_price=5,
            status="ACTIVE",
            created_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="WH-STOCKTAKE-001",
            warehouse_name="盘点仓库",
        )

    def _apply_runtime_config(self, user, config):
        blueprint = SystemBlueprint.objects.create(key=f"inventory-bp-{Tenant.objects.count()}", name="Inventory Policy", created_by=user)
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=user,
        )
        tenant = Tenant.objects.create(code=f"inventory-tenant-{Tenant.objects.count()}", name="Inventory Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(tenant=tenant, blueprint_version=version, config_json=config)
        return tenant

    def _build_inventory_config(self, *, stocktake=True):
        return {
            "basic": {"name": "inventory_policy", "industry": "trade", "mode": "saas"},
            "enabled_modules": ["inventory"],
            "module_configs": {
                "inventory": {
                    "features": {
                        "stocktake": stocktake,
                        "multi_warehouse": True,
                    },
                    "workflows": {},
                    "field_rules": {},
                    "defaults": {},
                }
            },
        }

    def test_create_stocktake_initializes_items_from_inventory(self):
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("8.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.user,
            remark="Seed stocktake inventory",
        )

        response = self.client.post(
            "/api/inventory/stocktakes/",
            {
                "stocktake_no": "STK-TEST-001",
                "warehouse": self.warehouse.id,
                "status": "IN_PROGRESS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["product"], self.product.id)
        self.assertEqual(Decimal(response.data["items"][0]["system_qty"]), Decimal("8.000"))
        self.assertEqual(Decimal(response.data["items"][0]["actual_qty"]), Decimal("8.000"))

    def test_retrieve_stocktake_backfills_missing_items(self):
        Inventory.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            current_qty=Decimal("6.000"),
            locked_qty=Decimal("0.000"),
        )
        self.product.current_stock = Decimal("6.000")
        self.product.save(update_fields=["current_stock"])

        create_response = self.client.post(
            "/api/inventory/stocktakes/",
            {
                "stocktake_no": "STK-TEST-002",
                "warehouse": self.warehouse.id,
                "status": "IN_PROGRESS",
            },
            format="json",
        )
        stocktake_id = create_response.data["id"]

        # Simulate historical empty stocktake records created before the fix.
        stocktake = self.user.created_stocktakes.get(id=stocktake_id)
        stocktake.items.all().delete()

        response = self.client.get(f"/api/inventory/stocktakes/{stocktake_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["product"], self.product.id)
        self.assertEqual(Decimal(response.data["items"][0]["system_qty"]), Decimal("6.000"))

    def test_update_stocktake_items_persists_actual_qty_and_remark(self):
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("5.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.user,
            remark="Seed stocktake inventory for update",
        )

        create_response = self.client.post(
            "/api/inventory/stocktakes/",
            {
                "stocktake_no": "STK-TEST-003",
                "warehouse": self.warehouse.id,
                "status": "IN_PROGRESS",
            },
            format="json",
        )
        stocktake_item = create_response.data["items"][0]

        response = self.client.post(
            f"/api/inventory/stocktakes/{create_response.data['id']}/update_items/",
            {
                "items": [
                    {
                        "id": stocktake_item["id"],
                        "actual_qty": "3.500",
                        "remark": "盘点少了半箱",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(response.data["items"][0]["actual_qty"]), Decimal("3.500"))
        self.assertEqual(Decimal(response.data["items"][0]["difference_qty"]), Decimal("-1.500"))
        self.assertEqual(response.data["items"][0]["remark"], "盘点少了半箱")

    def test_complete_stocktake_returns_adjustment_summary_and_keeps_inventory_consistent(self):
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("5.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.user,
            remark="Seed stocktake inventory for complete",
        )

        create_response = self.client.post(
            "/api/inventory/stocktakes/",
            {
                "stocktake_no": "STK-TEST-004",
                "warehouse": self.warehouse.id,
                "status": "IN_PROGRESS",
            },
            format="json",
        )
        stocktake_id = create_response.data["id"]
        stocktake_item = create_response.data["items"][0]

        self.client.post(
            f"/api/inventory/stocktakes/{stocktake_id}/update_items/",
            {
                "items": [
                    {
                        "id": stocktake_item["id"],
                        "actual_qty": "3.500",
                        "remark": "盘亏调整",
                    }
                ]
            },
            format="json",
        )

        response = self.client.post(
            f"/api/inventory/stocktakes/{stocktake_id}/complete/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["summary"]["adjustment_count"], 1)
        self.assertEqual(response.data["summary"]["adjustments"][0]["transaction_type"], "STOCKTAKE_LOSS")
        self.assertEqual(Decimal(response.data["summary"]["adjustments"][0]["quantity"]), Decimal("-1.500"))

        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        self.product.refresh_from_db()
        tx = InventoryTransaction.objects.get(reference_type="STOCKTAKE", reference_id=stocktake_id)

        self.assertEqual(inventory.current_qty, Decimal("3.500"))
        self.assertEqual(self.product.current_stock, Decimal("3.500"))
        self.assertEqual(tx.after_qty, inventory.current_qty)

    def test_stocktake_api_rejects_requests_when_policy_disabled(self):
        self._apply_runtime_config(self.user, self._build_inventory_config(stocktake=False))

        list_response = self.client.get("/api/inventory/stocktakes/")
        self.assertEqual(list_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("当前配置未启用库存盘点", list_response.data["detail"])

        create_response = self.client.post(
            "/api/inventory/stocktakes/",
            {
                "stocktake_no": "STK-DISABLED-001",
                "warehouse": self.warehouse.id,
                "status": "IN_PROGRESS",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("当前配置未启用库存盘点", create_response.data["detail"])


class UnitTenantScopeApiTest(APITestCase):
    @staticmethod
    def _build_inventory_config():
        return {
            "basic": {
                "name": "unit_scope",
                "industry": "trade",
                "mode": "saas",
            },
            "enabled_modules": ["platform", "inventory"],
            "module_configs": {
                "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            },
        }

    def setUp(self):
        self.platform_user = User.objects.create_user(username="unit_scope_owner", password="testpass")
        self.blueprint = SystemBlueprint.objects.create(
            key="unit_scope_bp",
            name="Unit Scope BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=self._build_inventory_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="Unit Scope Instance",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="unit-scope-tenant",
            name="Unit Scope Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.client.force_authenticate(self.erp_user)

        self.other_tenant = Tenant.objects.create(
            code="unit-scope-other",
            name="Unit Scope Other",
            status="ACTIVE",
            instance=self.instance,
        )
        Unit.objects.create(tenant=self.other_tenant, name="Other Unit", code="OTHER001")

    def test_created_unit_is_visible_in_current_tenant_list(self):
        create_response = self.client.post(
            "/api/inventory/units/",
            {"name": "箱", "status": True},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["tenant"], self.tenant.id)

        list_response = self.client.get("/api/inventory/units/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        tenant_ids = {item["tenant"] for item in list_response.data}
        self.assertEqual(tenant_ids, {self.tenant.id})
        self.assertTrue(any(item["name"] == "箱" for item in list_response.data))
