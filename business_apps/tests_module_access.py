from rest_framework import status
from rest_framework.test import APITestCase

from core_apps.authentication.models import Permission, Role, User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.tenant.models import Tenant, TenantUser
from core_apps.tenant.services import TenantService


def build_config(enabled_modules: list[str]):
    module_configs = {
        "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
        "purchase": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
        "sales": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
        "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
    }
    return {
        "basic": {
            "name": "module_access_test",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": enabled_modules,
        "module_configs": {key: value for key, value in module_configs.items() if key in enabled_modules},
    }


class ModuleAccessControlApiTest(APITestCase):
    def setUp(self):
        inventory_view = Permission.objects.create(name="查看商品", code="inventory:product:view", type="BUTTON")
        purchase_view = Permission.objects.create(name="查看采购订单", code="purchase:order:view", type="BUTTON")
        sales_view = Permission.objects.create(name="查看销售订单", code="sales:order:view", type="BUTTON")
        role = Role.objects.create(name="模块访问查看", code="module_access_viewer", data_scope="ALL")
        role.permissions.add(inventory_view, purchase_view, sales_view)

        self.user = User.objects.create_user(username="module_access_user", password="testpass")
        self.user.roles.add(role)
        self.client.force_authenticate(self.user)

        tenant = Tenant.objects.create(code="module-access", name="Module Access", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=self.user, is_default=True, is_owner=True)

        blueprint = SystemBlueprint.objects.create(
            key="module_access_bp",
            name="Module Access BP",
            created_by=self.user,
        )
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=build_config(["platform"]),
            created_by=self.user,
        )
        TenantService.apply_blueprint_version(tenant=tenant, blueprint_version=version)

    def test_inventory_api_returns_403_when_module_disabled(self):
        response = self.client.get("/api/inventory/products/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("未启用", str(response.data))

    def test_purchase_api_returns_403_when_module_disabled(self):
        response = self.client.get("/api/purchase/orders/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("未启用", str(response.data))

    def test_sales_api_returns_403_when_module_disabled(self):
        response = self.client.get("/api/sales/orders/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("未启用", str(response.data))
