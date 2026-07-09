from rest_framework import status
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core_apps.authentication.models import User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion, SystemInstance
from core_apps.erp_auth.models import ERPUser

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
