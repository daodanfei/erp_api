from rest_framework import status
from rest_framework.test import APITestCase

from core_apps.authentication.models import Permission, Role, User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.tenant.models import Tenant, TenantUser
from core_apps.tenant.services import TenantService


def build_config(*, file_center=True, dashboard=True):
    return {
        "basic": {
            "name": "feature_access_test",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["platform", "reports"],
        "module_configs": {
            "platform": {
                "features": {
                    "file_center": file_center,
                    "dict_center": False,
                    "code_rule_center": False,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "reports": {
                "features": {
                    "dashboard": dashboard,
                    "sales_analysis": True,
                    "purchase_analysis": True,
                    "inventory_analysis": True,
                    "customer_analysis": True,
                    "supplier_analysis": True,
                    "product_analysis": True,
                    "export_center": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


class FeatureAccessControlApiTest(APITestCase):
    def setUp(self):
        role = Role.objects.create(name="功能访问查看", code="feature_access_viewer", data_scope="ALL")
        role.permissions.add(
            Permission.objects.create(name="查看文件", code="platform:file:view", type="BUTTON"),
            Permission.objects.create(name="查看驾驶舱", code="reports:dashboard:view", type="BUTTON"),
        )

        self.user = User.objects.create_user(username="feature_access_user", password="testpass")
        self.user.roles.add(role)
        self.client.force_authenticate(self.user)

        tenant = Tenant.objects.create(code="feature-access", name="Feature Access", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=self.user, is_default=True, is_owner=True)
        self.tenant = tenant

    def _apply_runtime_config(self, config):
        blueprint = SystemBlueprint.objects.create(
            key=f"feature_access_bp_{SystemBlueprint.objects.count()}",
            name="Feature Access BP",
            created_by=self.user,
        )
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=self.user,
        )
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=version)

    def test_platform_file_api_returns_400_when_feature_disabled(self):
        self._apply_runtime_config(build_config(file_center=False))

        response = self.client.get("/api/platform/files/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("文件中心", response.data["detail"])

    def test_reports_dashboard_api_returns_400_when_feature_disabled(self):
        self._apply_runtime_config(build_config(dashboard=False))

        response = self.client.get("/api/reports/dashboard")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("经营驾驶舱", response.data["detail"])
