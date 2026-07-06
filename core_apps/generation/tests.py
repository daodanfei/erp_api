import json
import zipfile

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core_apps.authentication.models import User
from core_apps.blueprints.models import GenerationJob, SystemBlueprint, SystemBlueprintVersion, SystemInstance
from core_apps.tenant.models import Tenant
from .planners import build_generation_plan


def build_config(mode="code_export"):
    return {
        "basic": {
            "name": "stage3_erp",
            "industry": "trade",
            "mode": mode,
        },
        "enabled_modules": ["platform", "crm", "supplier", "finance", "inventory", "purchase", "ap_payable"],
        "module_configs": {
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "crm": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "supplier": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
            "finance": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
            "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "purchase": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "ap_payable": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
        },
    }


def build_prunable_config():
    return {
        "basic": {
            "name": "stage3_prunable_erp",
            "industry": "trade",
            "mode": "code_export",
        },
        "enabled_modules": ["platform", "crm", "supplier", "finance", "inventory", "purchase", "sales"],
        "module_configs": {
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "crm": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "supplier": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
            "finance": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {"default_currency": "CNY"}},
            "inventory": {
                "features": {"stocktake": False, "multi_warehouse": True},
                "workflows": {},
                "field_rules": {},
                "defaults": {"default_warehouse_code": "MAIN"},
            },
            "purchase": {
                "features": {"approval": False, "partial_receipt": False, "receipt_auto_ap": False},
                "workflows": {"purchase_order_submit": "auto_approve"},
                "field_rules": {},
                "defaults": {},
            },
            "sales": {
                "features": {"approval": False, "credit_control": True, "outbound_auto_ar": False},
                "workflows": {"sales_order_submit": "auto_approve"},
                "field_rules": {},
                "defaults": {"default_currency": "CNY"},
            },
        },
    }


class GenerationApiTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="generation_api", password="password")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.blueprint = SystemBlueprint.objects.create(key="bp_generation", name="Generation BP", created_by=self.user)
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
            is_published=True,
        )

    def test_plan_preview_returns_resolved_modules(self):
        response = self.client.get(
            "/api/generation/jobs/plan-preview/",
            {
                "blueprint_version": self.version.id,
                "runtime_mode": "CODE_EXPORT",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("inventory", response.data["module_keys"])
        self.assertIn("configuration", response.data["module_keys"])
        self.assertIn("inventory", response.data["enabled_modules"])
        self.assertIn("inventory", response.data["retained_frontend_modules"])
        self.assertIn("business_apps.inventory", response.data["retained_backend_apps"])
        self.assertIn("reports", response.data["removed_modules"])

    def test_plan_preview_allows_unpublished_blueprint_version(self):
        draft_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_config(),
            created_by=self.user,
            is_published=False,
        )

        response = self.client.get(
            "/api/generation/jobs/plan-preview/",
            {
                "blueprint_version": draft_version.id,
                "runtime_mode": "CODE_EXPORT",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("module_keys", response.data)

    def test_create_code_export_job_builds_artifact_and_audit_fields(self):
        response = self.client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "Export Instance",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job = GenerationJob.objects.get(job_key=response.data["generation_job"]["job_key"])
        instance = SystemInstance.objects.get(pk=response.data["instance"]["id"])
        self.assertEqual(job.status, "SUCCEEDED")
        self.assertEqual(job.job_stage, "COMPLETED")
        self.assertTrue(job.artifact_path.endswith(".zip"))
        self.assertGreater(job.artifact_size, 0)
        self.assertEqual(instance.runtime_mode, "CODE_EXPORT")
        self.assertEqual(instance.current_generation_job_id, job.id)
        self.assertTrue(instance.artifact_checksum)
        self.assertIn("retained_frontend_modules", response.data["plan"]["export_manifest"])
        with zipfile.ZipFile(job.artifact_path) as archive:
            members = set(archive.namelist())
        self.assertIn("export_bundle/backend/core_project/settings.py", members)
        self.assertIn("export_bundle/backend/core_project/urls.py", members)
        self.assertIn("export_bundle/frontend/src/core/modules/registry.ts", members)
        self.assertIn("export_bundle/module-lock.json", members)
        self.assertIn("export_bundle/erp_blueprint.json", members)
        self.assertNotIn("export_bundle/backend/business_apps/reports/module.py", members)
        self.assertNotIn("export_bundle/frontend/src/modules/sales/module.tsx", members)
        with zipfile.ZipFile(job.artifact_path) as archive:
            registry_source = archive.read("export_bundle/frontend/src/core/modules/registry.ts").decode("utf-8")
            settings_source = archive.read("export_bundle/backend/core_project/settings.py").decode("utf-8")
        self.assertIn("inventoryModule", registry_source)
        self.assertIn("purchaseModule", registry_source)
        self.assertNotIn("salesModule", registry_source)
        self.assertIn("business_apps.inventory", settings_source)
        self.assertIn("business_apps.purchase", settings_source)
        self.assertNotIn("business_apps.sales", settings_source)

    def test_create_saas_job_provisions_tenant_and_links_audit_snapshot(self):
        self.version.config_json = build_config(mode="saas")
        self.version.save(update_fields=["config_json"])

        response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "新东方实例",
                "tenant_name": "新东方",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job = GenerationJob.objects.get(job_key=response.data["generation_job"]["job_key"])
        instance = SystemInstance.objects.get(pk=response.data["instance"]["id"])
        tenant = Tenant.objects.get(pk=response.data["tenant"]["id"])
        self.assertEqual(job.status, "SUCCEEDED")
        self.assertEqual(instance.tenant_id, tenant.id)
        self.assertEqual(instance.runtime_mode, "SAAS")
        self.assertTrue(tenant.code.startswith("tenant-"))
        self.assertEqual(job.config_snapshot_json["basic"]["name"], "stage3_erp")
        self.assertEqual(
            [entry["stage"] for entry in job.job_logs_json],
            ["VALIDATING", "PLANNING", "PROVISIONING", "CREATING_INSTANCE", "APPLYING_BLUEPRINT", "FINALIZING"],
        )

    def test_create_saas_job_allows_rebinding_existing_tenant_to_new_instance(self):
        self.version.config_json = build_config(mode="saas")
        self.version.save(update_fields=["config_json"])

        first_response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "原实例",
                "tenant_name": "可重绑租户",
            },
            format="json",
        )
        tenant = Tenant.objects.get(pk=first_response.data["tenant"]["id"])

        second_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_config(mode="saas"),
            created_by=self.user,
            is_published=True,
        )
        second_response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": second_version.id,
                "instance_name": "新实例",
                "tenant": tenant.id,
            },
            format="json",
        )

        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        tenant.refresh_from_db()
        self.assertEqual(tenant.instance_id, second_response.data["instance"]["id"])
        self.assertEqual(second_response.data["tenant"]["id"], tenant.id)
        self.assertEqual(second_response.data["instance"]["blueprint_version"], second_version.id)

    def test_retry_creates_new_job_with_incremented_retry_count(self):
        response = self.client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "Retry Export",
            },
            format="json",
        )
        source_job_id = response.data["generation_job"]["id"]

        retry_response = self.client.post(f"/api/generation/jobs/{source_job_id}/retry/", {}, format="json")

        self.assertEqual(retry_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(retry_response.data["generation_job"]["retry_count"], 1)
        self.assertEqual(retry_response.data["generation_job"]["job_type"], "EXPORT_CODE")

    def test_build_generation_plan_returns_export_targets(self):
        plan = build_generation_plan(self.version)

        self.assertIn("inventory", plan.enabled_modules)
        self.assertIn("inventory", plan.retained_frontend_modules)
        self.assertIn("frontend/package.json", plan.exported_config_files)
        self.assertIn("business_apps.purchase", plan.retained_backend_apps)
        self.assertIn("reports", plan.removed_modules)
        self.assertEqual(plan.export_manifest["blueprint"]["version"], "v1")
        self.assertIn("module_feature_contracts", plan.export_manifest)
        self.assertIn("module_dependency_graph", plan.export_manifest)
        self.assertIn("seed_data_requirements", plan.export_manifest)
        self.assertIn("support_dependencies", plan.export_manifest)
        self.assertIn("inventory", plan.module_feature_contracts)

    def test_generation_job_retrieve_returns_audit_payload(self):
        create_response = self.client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "Audit Export",
            },
            format="json",
        )

        response = self.client.get(f"/api/generation/jobs/{create_response.data['generation_job']['id']}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["job"]["status"], "SUCCEEDED")
        self.assertEqual(response.data["instance"]["runtime_mode"], "CODE_EXPORT")
        self.assertIn("enabled_modules", response.data["plan"])

    def test_instance_list_returns_generation_instances(self):
        create_response = self.client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "List Export",
            },
            format="json",
        )

        response = self.client.get("/api/generation/instances/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], create_response.data["instance"]["id"])
        self.assertEqual(response.data[0]["runtime_mode"], "CODE_EXPORT")

    def test_instance_retrieve_returns_lifecycle_payload(self):
        self.version.config_json = build_config(mode="saas")
        self.version.save(update_fields=["config_json"])
        create_response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "Lifecycle SaaS",
                "tenant_name": "Lifecycle Tenant",
            },
            format="json",
        )

        response = self.client.get(f"/api/generation/instances/{create_response.data['instance']['id']}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["instance"]["name"], "Lifecycle SaaS")
        self.assertEqual(response.data["tenant"]["code"], "lifecycle-tenant")
        self.assertIsNotNone(response.data["latest_job"])
        self.assertIn("recent_jobs", response.data)

    def test_instance_status_actions_update_instance_and_tenant(self):
        self.version.config_json = build_config(mode="saas")
        self.version.save(update_fields=["config_json"])
        create_response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "Status SaaS",
                "tenant_name": "Status Tenant",
            },
            format="json",
        )
        instance_id = create_response.data["instance"]["id"]

        deactivate_response = self.client.post(f"/api/generation/instances/{instance_id}/deactivate/", {}, format="json")
        self.assertEqual(deactivate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(deactivate_response.data["status"], "INACTIVE")

        reactivate_response = self.client.post(f"/api/generation/instances/{instance_id}/reactivate/", {}, format="json")
        self.assertEqual(reactivate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(reactivate_response.data["status"], "ACTIVE")

        archive_response = self.client.post(f"/api/generation/instances/{instance_id}/archive/", {}, format="json")
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertEqual(archive_response.data["status"], "ARCHIVED")

    def test_reapply_blueprint_version_updates_instance_binding(self):
        self.version.config_json = build_config(mode="saas")
        self.version.save(update_fields=["config_json"])
        create_response = self.client.post(
            "/api/generation/create-saas/",
            {
                "blueprint_version": self.version.id,
                "instance_name": "Reapply SaaS",
                "tenant_name": "Reapply Tenant",
            },
            format="json",
        )
        new_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_config(mode="saas"),
            created_by=self.user,
            is_published=True,
        )

        response = self.client.post(
            f"/api/generation/instances/{create_response.data['instance']['id']}/reapply-version/",
            {"blueprint_version": new_version.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = SystemInstance.objects.get(pk=create_response.data["instance"]["id"])
        self.assertEqual(instance.blueprint_version_id, new_version.id)
        self.assertEqual(response.data["generation_job"]["status"], "SUCCEEDED")

    def test_export_registry_embeds_feature_pruning_contract(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_prunable_config(),
            created_by=self.user,
            is_published=True,
        )

        response = self.client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": version.id,
                "instance_name": "Prunable Export",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job = GenerationJob.objects.get(job_key=response.data["generation_job"]["job_key"])
        with zipfile.ZipFile(job.artifact_path) as archive:
            registry_source = archive.read("export_bundle/frontend/src/core/modules/registry.ts").decode("utf-8")
            module_lock = json.loads(archive.read("export_bundle/module-lock.json").decode("utf-8"))
            purchase_frontend_module = archive.read("export_bundle/frontend/src/modules/purchase/module.tsx").decode("utf-8")
            purchase_backend_module = archive.read("export_bundle/backend/business_apps/purchase/module.py").decode("utf-8")
            readme_source = archive.read("export_bundle/README.generated.md").decode("utf-8")

        self.assertIn("const exportFeatureContracts =", registry_source)
        self.assertIn("applyExportContract", registry_source)
        self.assertIn("disabled_prunable_features", registry_source)
        self.assertIn("/inventory/stocktake", registry_source)
        self.assertIn("/purchase/receipts", registry_source)
        self.assertIn("purchase:order:approve", registry_source)
        self.assertIn("__EXPORT_PRUNED_ROUTE_PATHS", purchase_frontend_module)
        self.assertIn("module.routes = module.routes.filter(", purchase_frontend_module)
        self.assertIn("_EXPORT_PRUNED_PERMISSION_CODES", purchase_backend_module)
        self.assertIn('object.__setattr__(', purchase_backend_module)
        self.assertIn("## Feature Contracts", readme_source)
        self.assertIn("pruned_route_paths", readme_source)
        self.assertIn("Feature-level pruning in stage three removes registration entries", readme_source)
        self.assertIn("module_feature_contracts", module_lock["export_manifest"])
        self.assertIn("prunable_route_paths", module_lock["export_manifest"])
        self.assertEqual(
            module_lock["export_manifest"]["module_feature_contracts"]["purchase"]["disabled_prunable_features"],
            ["approval", "partial_receipt"],
        )


class GenerationValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="generation_validation", password="password")
        self.blueprint = SystemBlueprint.objects.create(key="bp_validation", name="Validation BP", created_by=self.user)

    def test_generation_requires_published_blueprint_version(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
            is_published=False,
        )

        token = RefreshToken.for_user(self.user).access_token
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": version.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("已发布", str(response.data))

    def test_generation_rejects_missing_module_dependency(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json={
                "basic": {"name": "invalid", "industry": "trade", "mode": "code_export"},
                "enabled_modules": ["purchase"],
                "module_configs": {
                    "purchase": {
                        "features": {},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_currency": "CNY"},
                    }
                },
            },
            created_by=self.user,
            is_published=True,
        )

        token = RefreshToken.for_user(self.user).access_token
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": version.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("module_dependencies", str(response.data))

    def test_generation_rejects_manual_approval_when_approval_disabled(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v3",
            config_json={
                "basic": {"name": "invalid-approval", "industry": "trade", "mode": "code_export"},
                "enabled_modules": ["inventory", "platform", "crm", "sales"],
                "module_configs": {
                    "inventory": {
                        "features": {"multi_warehouse": False, "warehouse_required_on_transaction": False},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_warehouse_code": "MAIN"},
                    },
                    "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "crm": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
                    "sales": {
                        "features": {"approval": False},
                        "workflows": {"sales_order_submit": "manual_approve"},
                        "field_rules": {"sales_order.approver": {"visible": True, "required": False, "readonly": False}},
                        "defaults": {"default_currency": "CNY"},
                    },
                },
            },
            created_by=self.user,
            is_published=True,
        )

        token = RefreshToken.for_user(self.user).access_token
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.post(
            "/api/generation/export-code/",
            {
                "blueprint_version": version.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("approval_rules", str(response.data))
