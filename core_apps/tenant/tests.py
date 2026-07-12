from rest_framework import status
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.crm.models import Customer
from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem
from business_apps.sales.models import SalesOrder, SalesOrderItem
from business_apps.supplier.models import Supplier
from core_apps.authentication.models import User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion, SystemInstance
from core_apps.erp_auth.models import ERPRole, ERPUser
from core_apps.erp_auth.services import ERPUserProvisionService

from .models import Tenant, TenantConfigSnapshot, TenantModuleState, TenantUser
from .services import TenantService, build_runtime_config, generate_tenant_code


def build_config():
    return {
        "basic": {
            "name": "small_trade_erp",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["inventory", "purchase"],
        "module_configs": {
            "inventory": {
                "features": {"multi_warehouse": False},
                "workflows": {},
                "field_rules": {},
                "defaults": {"default_warehouse_code": "MAIN"},
            },
            "purchase": {
                "features": {"approval": False},
                "workflows": {"purchase_order_submit": "auto_approve"},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


class TenantServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tenant_service", password="password")
        self.blueprint = SystemBlueprint.objects.create(key="tenant_service_bp", name="Tenant Service BP", created_by=self.user)
        self.version_v1 = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
        )
        self.version_v2 = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json={
                "basic": {
                    "name": "small_trade_erp_v2",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["sales"],
                "module_configs": {
                    "sales": {
                        "features": {"approval": False},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {},
                    },
                },
            },
            created_by=self.user,
        )
        self.tenant = Tenant.objects.create(code="tenant-service-a", name="Tenant Service A", status="ACTIVE")

    def test_apply_blueprint_version_mirrors_full_module_state_and_marks_active_snapshot(self):
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)
        TenantModuleState.objects.update_or_create(
            tenant=self.tenant,
            module_key="sales",
            defaults={"enabled": True},
        )

        snapshot = TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v2)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.active_blueprint_version.id, self.version_v2.id)
        self.assertEqual(self.tenant.active_config_snapshot.id, snapshot.id)
        self.assertEqual(snapshot.blueprint_version_id, self.version_v2.id)
        self.assertTrue(TenantModuleState.objects.get(tenant=self.tenant, module_key="sales").enabled)
        self.assertFalse(TenantModuleState.objects.get(tenant=self.tenant, module_key="inventory").enabled)
        self.assertFalse(TenantModuleState.objects.get(tenant=self.tenant, module_key="purchase").enabled)
        self.assertFalse(TenantModuleState.objects.get(tenant=self.tenant, module_key="platform").enabled)

    def test_apply_blueprint_version_keeps_other_tenant_module_states_unchanged(self):
        other_tenant = Tenant.objects.create(code="tenant-service-b", name="Tenant Service B", status="ACTIVE")
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)
        TenantService.apply_blueprint_version(tenant=other_tenant, blueprint_version=self.version_v2)

        self.assertTrue(TenantModuleState.objects.get(tenant=self.tenant, module_key="inventory").enabled)
        self.assertTrue(TenantModuleState.objects.get(tenant=self.tenant, module_key="purchase").enabled)
        self.assertTrue(TenantModuleState.objects.get(tenant=other_tenant, module_key="sales").enabled)
        self.assertFalse(TenantModuleState.objects.get(tenant=other_tenant, module_key="inventory").enabled)

    def test_build_runtime_config_uses_current_active_snapshot_only(self):
        first_snapshot = TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)
        second_snapshot = TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v2)

        config = build_runtime_config(self.tenant)

        self.assertEqual(self.tenant.active_config_snapshot.id, second_snapshot.id)
        self.assertEqual(config.snapshot.id, second_snapshot.id)
        self.assertNotEqual(first_snapshot.id, second_snapshot.id)
        self.assertTrue(config.is_enabled("sales"))
        self.assertFalse(config.is_enabled("inventory"))

    def test_generate_tenant_code_adds_unique_suffix_for_duplicate_names(self):
        Tenant.objects.create(code="tenant-a", name="Tenant A", status="ACTIVE")

        self.assertEqual(generate_tenant_code("Tenant A"), "tenant-a-2")

    def test_create_tenant_auto_creates_default_warehouse(self):
        tenant = TenantService.create_tenant(code="tenant-auto-wh", name="Tenant Auto WH")

        warehouse = Warehouse.objects.get(tenant=tenant)
        self.assertEqual(warehouse.warehouse_code, "MAIN")
        self.assertEqual(warehouse.warehouse_name, "默认仓库")
        self.assertTrue(warehouse.status)

    def test_create_second_tenant_uses_tenant_prefixed_default_warehouse_code_when_main_is_taken(self):
        TenantService.create_tenant(code="tenant-main-a", name="Tenant Main A")

        tenant_b = TenantService.create_tenant(code="tenant-main-b", name="Tenant Main B")

        warehouse = Warehouse.objects.get(tenant=tenant_b)
        self.assertEqual(warehouse.warehouse_code, "TENANT-MAIN-B-MAIN")

    def test_apply_blueprint_version_auto_creates_configured_default_warehouse(self):
        custom_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v-custom-wh",
            config_json={
                "basic": {
                    "name": "custom_wh",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["inventory"],
                "module_configs": {
                    "inventory": {
                        "features": {
                            "multi_warehouse": False,
                            "warehouse_required_on_transaction": False,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_warehouse_code": "W001"},
                    }
                },
            },
            created_by=self.user,
        )

        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=custom_version)

        self.assertTrue(Warehouse.objects.filter(tenant=self.tenant, warehouse_code="W001", status=True).exists())

    def test_apply_blueprint_version_refreshes_existing_super_admin_role_permissions(self):
        ERPUserProvisionService.ensure_tenant_super_admin(tenant=self.tenant)
        limited_role = ERPRole.objects.get(tenant=self.tenant, is_system=True)
        limited_codes = set(limited_role.permissions.values_list("code", flat=True))
        self.assertIn("inventory", limited_codes)
        self.assertNotIn("sales", limited_codes)

        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v2)

        limited_role.refresh_from_db()
        refreshed_codes = set(limited_role.permissions.values_list("code", flat=True))
        self.assertIn("sales", refreshed_codes)
        self.assertNotIn("inventory", refreshed_codes)

    def test_apply_blueprint_version_does_not_create_super_admin_when_absent(self):
        self.assertEqual(self.tenant.erp_users.count(), 0)

        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)

        self.assertEqual(self.tenant.erp_users.count(), 0)

    def test_apply_blueprint_version_blocks_switch_to_multi_warehouse_when_open_items_have_no_warehouse(self):
        category = ProductCategory.objects.create(name="默认分类", status=True, tenant=self.tenant)
        unit = Unit.objects.create(name="件", code="UNIT-TENANT-001", status=True, tenant=self.tenant)
        supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code="SUP-TENANT-001",
            supplier_name="默认供应商",
            status="ACTIVE",
        )
        product = Product.objects.create(
            tenant=self.tenant,
            product_code="PRO-TENANT-001",
            name="测试商品",
            category=category,
            unit=unit,
            status="ACTIVE",
        )
        purchase_order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO-TENANT-001",
            supplier=supplier,
            status=PurchaseOrder.STATUS_DRAFT,
        )
        PurchaseOrderItem.objects.create(
            tenant=self.tenant,
            purchase_order=purchase_order,
            product=product,
            warehouse=None,
            quantity=1,
            unit_price=10,
            amount=10,
        )
        multi_wh_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v-multi-wh",
            config_json={
                "basic": {
                    "name": "multi_wh",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["platform", "inventory", "purchase", "supplier"],
                "module_configs": {
                    "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "inventory": {
                        "features": {
                            "multi_warehouse": True,
                            "warehouse_required_on_transaction": True,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_warehouse_code": "MAIN"},
                    },
                    "purchase": {
                        "features": {"approval": False},
                        "workflows": {"purchase_order_submit": "auto_approve"},
                        "field_rules": {},
                        "defaults": {"default_currency": "CNY"},
                    },
                    "supplier": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
                },
            },
            created_by=self.user,
        )
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)

        with self.assertRaisesMessage(ValueError, "未绑定仓库"):
            TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=multi_wh_version)

    def test_clear_tenant_data_keeps_tenant_snapshot_and_recreates_admin_and_default_warehouse(self):
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)
        ERPUser.objects.create_user(
            tenant=self.tenant,
            username="operator",
            password="operator-123",
            status=True,
            must_change_password=False,
        )
        Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="TEMP-WH-001",
            warehouse_name="临时仓",
            status=True,
        )

        result = TenantService.clear_tenant_data(tenant=self.tenant)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.active_blueprint_version.id, self.version_v1.id)
        self.assertEqual(self.tenant.erp_users.count(), 1)
        self.assertEqual(self.tenant.erp_users.first().username, "admin")
        self.assertTrue(self.tenant.warehouses.filter(status=True).exists())
        self.assertTrue(self.tenant.warehouses.filter(warehouse_name="默认仓库").exists())
        self.assertIn("initial_admin", result)

    def test_clear_tenant_data_does_not_recreate_default_warehouse_for_multi_warehouse_blueprint(self):
        multi_wh_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v-clear-multi-wh",
            config_json={
                "basic": {
                    "name": "multi_wh_clear",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["platform", "inventory"],
                "module_configs": {
                    "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "inventory": {
                        "features": {
                            "multi_warehouse": True,
                            "warehouse_required_on_transaction": True,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_warehouse_code": "MAIN"},
                    },
                },
            },
            created_by=self.user,
        )
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=multi_wh_version)
        Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="WH-CLEAR-001",
            warehouse_name="业务仓",
            status=True,
        )

        TenantService.clear_tenant_data(tenant=self.tenant)

        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.warehouses.exists())
        self.assertEqual(self.tenant.erp_users.count(), 1)
        self.assertEqual(self.tenant.erp_users.first().username, "admin")

    def test_clear_tenant_data_deletes_protected_warehouse_dependencies_before_warehouse(self):
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=self.version_v1)
        category = ProductCategory.objects.create(name="销售分类", status=True, tenant=self.tenant)
        unit = Unit.objects.create(name="件", code="UNIT-TENANT-002", status=True, tenant=self.tenant)
        warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="WH-SALES-CLEAR-001",
            warehouse_name="销售仓",
            status=True,
        )
        product = Product.objects.create(
            tenant=self.tenant,
            product_code="PRO-TENANT-002",
            name="销售商品",
            category=category,
            unit=unit,
            status="ACTIVE",
        )
        customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="CUS-TENANT-002",
            customer_name="销售客户",
            status="ACTIVE",
        )
        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-TENANT-001",
            customer=customer,
            status=SalesOrder.STATUS_DRAFT,
        )
        SalesOrderItem.objects.create(
            order=sales_order,
            product=product,
            warehouse=warehouse,
            quantity=1,
            unit_price=10,
            amount=10,
        )

        TenantService.clear_tenant_data(tenant=self.tenant)

        self.assertEqual(SalesOrderItem.objects.filter(order__tenant=self.tenant).count(), 0)
        self.assertTrue(self.tenant.warehouses.filter(warehouse_name="默认仓库").exists())

    def test_business_detail_model_auto_infers_tenant_from_parent_document(self):
        category = ProductCategory.objects.create(name="自动继承分类", status=True, tenant=self.tenant)
        unit = Unit.objects.create(name="件", code="UNIT-TENANT-AUTO", status=True, tenant=self.tenant)
        customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="CUS-TENANT-AUTO",
            customer_name="自动继承客户",
            status="ACTIVE",
        )
        product = Product.objects.create(
            tenant=self.tenant,
            product_code="PRO-TENANT-AUTO",
            name="自动继承商品",
            category=category,
            unit=unit,
            status="ACTIVE",
        )
        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-TENANT-AUTO",
            customer=customer,
            status=SalesOrder.STATUS_DRAFT,
        )

        item = SalesOrderItem.objects.create(
            order=sales_order,
            product=product,
            quantity=1,
            unit_price=10,
            amount=10,
        )

        self.assertEqual(item.tenant_id, self.tenant.id)

    def test_business_detail_model_rejects_cross_tenant_relation(self):
        other_tenant = Tenant.objects.create(code="tenant-service-c", name="Tenant Service C", status="ACTIVE")
        other_category = ProductCategory.objects.create(name="跨租户分类", status=True, tenant=other_tenant)
        other_unit = Unit.objects.create(name="箱", code="UNIT-TENANT-CROSS", status=True, tenant=other_tenant)
        customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="CUS-TENANT-CROSS",
            customer_name="跨租户客户",
            status="ACTIVE",
        )
        product = Product.objects.create(
            tenant=other_tenant,
            product_code="PRO-TENANT-CROSS",
            name="跨租户商品",
            category=other_category,
            unit=other_unit,
            status="ACTIVE",
        )
        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-TENANT-CROSS",
            customer=customer,
            status=SalesOrder.STATUS_DRAFT,
        )

        with self.assertRaises(ValidationError):
            SalesOrderItem.objects.create(
                tenant=self.tenant,
                order=sales_order,
                product=product,
                quantity=1,
                unit_price=10,
                amount=10,
            )


class TenantApiTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tenant_api", password="password")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.blueprint = SystemBlueprint.objects.create(key="tenant_bp", name="Tenant BP", created_by=self.user)
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
            is_published=True,
        )

    def test_create_tenant_from_version_creates_snapshot(self):
        response = self.client.post(
            "/api/tenant/items/create-from-version/",
            {
                "code": "tenant-a",
                "name": "Tenant A",
                "industry": "trade",
                "blueprint_version": self.version.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tenant = Tenant.objects.get(code="tenant-a")
        self.assertTrue(TenantConfigSnapshot.objects.filter(tenant=tenant, blueprint_version=self.version).exists())
        self.assertEqual(tenant.active_blueprint_version.id, self.version.id)
        self.assertIsNotNone(tenant.active_config_snapshot)

    def test_create_tenant_without_code_auto_generates_code(self):
        response = self.client.post(
            "/api/tenant/items/",
            {
                "name": "Tenant Auto Code",
                "industry": "trade",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tenant = Tenant.objects.get(id=response.data["id"])
        self.assertTrue(tenant.code.startswith("tenant-auto-code"))

    def test_create_tenant_from_version_without_code_auto_generates_code(self):
        response = self.client.post(
            "/api/tenant/items/create-from-version/",
            {
                "name": "Tenant Snapshot Auto Code",
                "industry": "trade",
                "blueprint_version": self.version.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tenant = Tenant.objects.get(id=response.data["id"])
        self.assertTrue(tenant.code.startswith("tenant-snapshot-auto-code"))
        self.assertIsNotNone(tenant.active_config_snapshot)

    def test_runtime_config_endpoint_returns_enabled_modules(self):
        tenant = Tenant.objects.create(code="tenant-b", name="Tenant B", status="ACTIVE")
        snapshot = TenantConfigSnapshot.objects.create(
            tenant=tenant,
            blueprint_version=self.version,
            config_json=self.version.config_json,
        )
        TenantUser.objects.create(tenant=tenant, user=self.user, is_default=True)

        response = self.client.get("/api/tenant/runtime-config/", HTTP_X_TENANT_CODE="tenant-b")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("inventory", response.data["enabled_modules"])

    def test_runtime_config_endpoint_returns_instance_and_blueprint_context(self):
        tenant = Tenant.objects.create(code="tenant-c", name="Tenant C", status="ACTIVE")
        TenantConfigSnapshot.objects.create(
            tenant=tenant,
            blueprint_version=self.version,
            config_json=self.version.config_json,
        )
        TenantUser.objects.create(tenant=tenant, user=self.user, is_default=True)
        instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="Tenant C SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.user,
        )
        tenant.instance = instance
        tenant.save(update_fields=["instance"])

        response = self.client.get("/api/tenant/runtime-config/", HTTP_X_TENANT_CODE="tenant-c")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["tenant"]["code"], "tenant-c")
        self.assertIsNone(response.data["instance"])
        self.assertEqual(response.data["blueprint"]["key"], self.blueprint.key)
        self.assertEqual(response.data["blueprint_version"]["version"], self.version.version)

    def test_bind_instance_endpoint_sets_instance_and_returns_initial_admin(self):
        tenant = Tenant.objects.create(code="tenant-d", name="Tenant D", status="ACTIVE")
        instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="Tenant D SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/tenant/items/{tenant.id}/bind-instance/",
            {"instance": instance.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tenant.refresh_from_db()
        self.assertEqual(tenant.instance_id, instance.id)
        self.assertTrue(ERPUser.objects.filter(tenant=tenant, username="admin").exists())
        self.assertTrue(response.data["initial_admin"]["created"])
        self.assertTrue(response.data["initial_admin"]["initial_password"])

    def test_initial_admin_endpoint_returns_existing_admin(self):
        tenant = Tenant.objects.create(code="tenant-e", name="Tenant E", status="ACTIVE")
        instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="Tenant E SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.user,
        )
        TenantService.bind_instance_to_tenant(tenant=tenant, instance=instance, blueprint_version=self.version)

        response = self.client.get(f"/api/tenant/items/{tenant.id}/initial-admin/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["exists"])
        self.assertEqual(response.data["user"]["username"], "admin")

    def test_reset_initial_admin_password_endpoint_rotates_password(self):
        tenant = Tenant.objects.create(code="tenant-f", name="Tenant F", status="ACTIVE")
        instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="Tenant F SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.user,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=tenant,
            instance=instance,
            blueprint_version=self.version,
        )

        response = self.client.post(f"/api/tenant/items/{tenant.id}/reset-initial-admin-password/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        admin_user = bind_result.initial_admin.user
        admin_user.refresh_from_db()
        self.assertFalse(response.data["created"])
        self.assertTrue(response.data["initial_password"])
        self.assertTrue(admin_user.check_password(response.data["initial_password"]))
        self.assertTrue(admin_user.must_change_password)
