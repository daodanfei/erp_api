from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core_apps.authentication.models import User
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantModuleState, TenantUser
from core_apps.tenant.services import build_runtime_config, resolve_user_tenant

from .models import GenerationJob, SystemBlueprint, SystemBlueprintVersion
from .services import BlueprintService, SystemInstanceService, get_next_blueprint_version, publish_blueprint_version


def build_config(enabled_modules=None, module_configs=None):
    return {
        "basic": {
            "name": "small_trade_erp",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": enabled_modules or ["platform", "crm", "supplier", "finance", "inventory"],
        "module_configs": module_configs or {
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "crm": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "supplier": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
            "finance": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
            "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
        },
    }


class BlueprintServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="blueprint_owner", password="password")
        self.blueprint = SystemBlueprint.objects.create(key="bp_service", name="BP Service", created_by=self.user)

    def test_clone_version_copies_config(self):
        version = BlueprintService.create_version(
            blueprint=self.blueprint,
            created_by=self.user,
            config_json=build_config(),
            version="v1",
        )

        cloned = BlueprintService.clone_version(source_version=version, created_by=self.user)

        self.assertEqual(cloned.blueprint_id, self.blueprint.id)
        self.assertEqual(cloned.version, "v2")
        self.assertEqual(cloned.config_json, version.config_json)

    def test_next_blueprint_version_auto_increments(self):
        self.assertEqual(get_next_blueprint_version(self.blueprint), "v1")
        SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
        )
        self.assertEqual(get_next_blueprint_version(self.blueprint), "v2")

    def test_publish_blueprint_version_unpublishes_previous_one(self):
        first = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            is_published=True,
            config_json=build_config(),
            created_by=self.user,
        )
        second = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_config(),
            created_by=self.user,
        )

        publish_blueprint_version(second)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_published)
        self.assertTrue(second.is_published)

    def test_publish_blueprint_version_rejects_invalid_generation_dependencies(self):
        invalid = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json={
                "basic": {
                    "name": "invalid_publish",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["platform", "inventory", "sales"],
                "module_configs": {
                    "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "inventory": {
                        "features": {"multi_warehouse": False, "warehouse_required_on_transaction": False},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_warehouse_code": "MAIN"},
                    },
                    "sales": {
                        "features": {"outbound_auto_ar": True},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_currency": "CNY"},
                    },
                },
            },
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            publish_blueprint_version(invalid)

    def test_create_saas_instance_from_blueprint_version_builds_full_runtime_chain(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(
                enabled_modules=["platform", "crm", "supplier", "finance", "inventory", "purchase", "ap_payable"],
                module_configs={
                    "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "crm": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "supplier": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
                    "finance": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
                    "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "purchase": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "ap_payable": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                },
            ),
            created_by=self.user,
            is_published=True,
        )

        result = SystemInstanceService.create_saas_instance_from_blueprint_version(
            blueprint_version=version,
            created_by=self.user,
            tenant_name="Blueprint SaaS",
            instance_name="Blueprint SaaS Instance",
            industry="trade",
        )

        self.assertEqual(result.tenant.code, "blueprint-saas")
        self.assertIsNone(result.instance)
        self.assertEqual(result.generation_job.job_type, "CREATE_SAAS")
        self.assertEqual(result.generation_job.status, "SUCCEEDED")
        self.assertEqual(result.snapshot.tenant_id, result.tenant.id)
        self.assertEqual(
            set(state.module_key for state in result.module_states if state.enabled),
            {"platform", "crm", "supplier", "finance", "inventory", "purchase", "ap_payable"},
        )
        self.assertTrue(TenantUser.objects.filter(tenant=result.tenant, user=self.user, is_owner=True).exists())


class BlueprintApiTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="blueprint_api", password="password")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.blueprint = SystemBlueprint.objects.create(key="bp_api", name="BP API", created_by=self.user)

    def test_blueprint_version_endpoint_validates_stable_config_shape(self):
        response = self.client.post(
            "/api/blueprints/versions/",
            {
                "blueprint": self.blueprint.id,
                "config_json": {
                    "modules": {
                        "inventory": {"enabled": True},
                    }
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("basic.name", str(response.data))

    def test_publish_endpoint_marks_version_published(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
            is_published=False,
        )

        response = self.client.post(f"/api/blueprints/versions/{version.id}/publish/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        version.refresh_from_db()
        self.assertTrue(version.is_published)

    def test_create_blueprint_version_without_version_generates_next_version(self):
        response = self.client.post(
            "/api/blueprints/versions/",
            {
                "blueprint": self.blueprint.id,
                "config_json": build_config(
                    enabled_modules=["inventory"],
                    module_configs={
                        "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    },
                ),
                "change_note": "add inventory preset",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["version"], "v1")

    def test_blueprint_version_endpoint_rejects_duplicate_version_within_same_blueprint(self):
        SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
        )

        response = self.client.post(
            "/api/blueprints/versions/",
            {
                "blueprint": self.blueprint.id,
                "version": "v1",
                "config_json": build_config(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("版本号不能重复", str(response.data))

    def test_generation_create_saas_endpoint_returns_tenant_and_job(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(
                enabled_modules=["platform", "crm", "supplier", "finance", "inventory", "purchase", "sales", "supply_chain", "ar_receivable", "ap_payable"],
                module_configs={
                    "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "crm": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "supplier": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
                    "finance": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
                    "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "purchase": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "sales": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "supply_chain": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "ar_receivable": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "ap_payable": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                },
            ),
            created_by=self.user,
            is_published=True,
        )

        response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": version.id,
                "tenant_name": "BP API Tenant",
                "instance_name": "BP API Instance",
                "industry": "trade",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["tenant"]["code"], "bp-api-tenant")
        self.assertIsNone(response.data["instance"])
        self.assertEqual(response.data["generation_job"]["job_type"], "CREATE_SAAS")
        self.assertEqual(response.data["generation_job"]["status"], "SUCCEEDED")
        self.assertEqual(
            GenerationJob.objects.filter(
                blueprint_version=version,
                result_json__tenant_id=response.data["tenant"]["id"],
            ).count(),
            1,
        )
        self.assertEqual(
            TenantConfigSnapshot.objects.filter(blueprint_version=version, tenant__code=response.data["tenant"]["code"]).count(),
            1,
        )


class RuntimeBlueprintTenantIntegrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tenant_user", password="password")
        self.tenant = Tenant.objects.create(code="acme", name="Acme", status="ACTIVE")
        self.tenant_b = Tenant.objects.create(code="beta", name="Beta", status="ACTIVE")
        TenantUser.objects.create(tenant=self.tenant, user=self.user, is_default=True)
        TenantUser.objects.create(tenant=self.tenant_b, user=self.user, is_default=False)
        self.blueprint = SystemBlueprint.objects.create(
            key="small_trade",
            name="小商贸 ERP",
            created_by=self.user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(
                enabled_modules=["inventory", "purchase"],
                module_configs={
                    "inventory": {
                        "features": {"multi_warehouse": False},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_warehouse_code": "WH-001"},
                    },
                    "purchase": {
                        "features": {"approval": False},
                        "workflows": {"purchase_order_submit": "auto_approve"},
                        "field_rules": {},
                        "defaults": {},
                    },
                    "finance": {
                        "features": {},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {},
                    },
                },
            ),
            created_by=self.user,
        )
        TenantConfigSnapshot.objects.create(
            tenant=self.tenant,
            blueprint_version=self.version,
            config_json=self.version.config_json,
        )
        TenantModuleState.objects.create(tenant=self.tenant, module_key="finance", enabled=True)

    def test_resolve_user_tenant_prefers_default_membership(self):
        self.assertEqual(resolve_user_tenant(self.user).id, self.tenant.id)
        self.assertEqual(resolve_user_tenant(self.user, tenant_code="beta").id, self.tenant_b.id)

    def test_runtime_config_uses_snapshot_and_module_overrides(self):
        config = build_runtime_config(self.tenant)

        self.assertTrue(config.is_enabled("inventory"))
        self.assertTrue(config.is_enabled("finance"))
        self.assertEqual(config.get_default("default_warehouse_code", module_key="inventory"), "WH-001")
        self.assertEqual(config.get_workflow("purchase", "purchase_order_submit"), "auto_approve")

    def test_different_tenants_keep_runtime_config_isolated(self):
        other_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_config(
                enabled_modules=["sales"],
                module_configs={
                    "sales": {
                        "features": {"credit_control": True},
                        "workflows": {"sales_order_submit": "manual_approve"},
                        "field_rules": {},
                        "defaults": {},
                    },
                },
            ),
            created_by=self.user,
        )
        TenantConfigSnapshot.objects.create(
            tenant=self.tenant_b,
            blueprint_version=other_version,
            config_json=other_version.config_json,
        )

        tenant_a_config = build_runtime_config(self.tenant)
        tenant_b_config = build_runtime_config(self.tenant_b)

        self.assertTrue(tenant_a_config.is_enabled("inventory"))
        self.assertFalse(tenant_a_config.is_enabled("sales"))
        self.assertFalse(tenant_b_config.is_enabled("inventory"))
        self.assertTrue(tenant_b_config.is_enabled("sales"))
