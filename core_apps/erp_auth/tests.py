from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase
from unittest.mock import patch

from business_apps.ap_payable.models import APAccount, APAllocation, APPayment
from business_apps.ap_payable.services import APService
from business_apps.ar_receivable.models import Receivable, Receipt, WriteOff
from business_apps.ar_receivable.services import ARService
from business_apps.accounting.models import BusinessPostingLog, Voucher
from business_apps.accounting.models import AccountSubject
from business_apps.accounting.services import SubjectInitService
from business_apps.crm.models import Customer, CustomerAttachment, FollowRecord
from business_apps.finance.models import CashAccount
from business_apps.inventory.models import InventoryTransaction, Product, ProductCategory, Unit, Warehouse
from business_apps.platform.models import DictItem, DictType, File
from business_apps.inventory.services import InventoryService
from business_apps.purchase.services import PurchaseOrderService
from business_apps.sales.models import OrderApprovalLog, SalesExecutionLog, SalesOrder
from business_apps.sales.services import SalesOrderService
from business_apps.supply_chain.services import OutboundService
from business_apps.supplier.models import Supplier, SupplierAttachment, SupplierEvaluation, SupplierFollowRecord
from core_apps.authentication.models import Permission, User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion, SystemInstance
from core_apps.tenant.models import Tenant
from core_apps.tenant.services import TenantService

from .models import ERPDepartment, ERPPermission, ERPRole, ERPUser
from .services import ERPUserProvisionService


def build_system_module_config(**feature_overrides):
    return {
        "features": {
            "user_management": True,
            "department_management": True,
            "role_management": True,
            "operation_log": True,
            "permission_management": False,
            **feature_overrides,
        },
        "workflows": {},
        "field_rules": {},
        "defaults": {},
    }


def build_config():
    return {
        "basic": {
            "name": "erp_auth_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "inventory"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
        },
    }


def build_purchase_config():
    return {
        "basic": {
            "name": "erp_purchase_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "inventory", "purchase"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "purchase": {
                "features": {
                    "approval": False,
                    "partial_receipt": True,
                    "purchase_return": False,
                    "receipt_auto_ap": False,
                    "expected_arrival_required": False,
                    "supplier_blacklist_block": True,
                },
                "workflows": {
                    "purchase_order_submit": "auto_approve",
                },
                "field_rules": {},
                "defaults": {"default_currency": "CNY"},
            },
        },
    }


def build_purchase_single_warehouse_config():
    config = build_purchase_config()
    config["module_configs"]["inventory"] = {
        "features": {
            "multi_warehouse": False,
            "warehouse_required_on_transaction": False,
        },
        "workflows": {},
        "field_rules": {},
        "defaults": {
            "default_warehouse_code": "MAIN",
        },
    }
    return config


def build_finance_cash_config():
    return {
        "basic": {
            "name": "erp_finance_cash_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "finance"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "finance": {
                "features": {
                    "multi_cash_account": True,
                    "reconciliation_enabled": True,
                    "cash_flow_analysis_enabled": True,
                    "opening_balance_editable": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


def build_platform_file_config(*, dict_center=False):
    return {
        "basic": {
            "name": "erp_platform_file_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {
                "features": {
                    "file_center": True,
                    "dict_center": dict_center,
                    "code_rule_center": False,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


def build_purchase_ap_config():
    return {
        "basic": {
            "name": "erp_purchase_ap_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "inventory", "purchase", "ap_payable"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "inventory": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "purchase": {
                "features": {
                    "approval": False,
                    "partial_receipt": True,
                    "purchase_return": False,
                    "receipt_auto_ap": True,
                    "expected_arrival_required": False,
                    "supplier_blacklist_block": True,
                },
                "workflows": {
                    "purchase_order_submit": "auto_approve",
                },
                "field_rules": {},
                "defaults": {"default_currency": "CNY"},
            },
            "ap_payable": {
                "features": {
                    "auto_create_payable": True,
                    "payment_approval": True,
                    "allow_partial_payment": True,
                    "supplier_reconciliation_enabled": True,
                    "allocation_enabled": True,
                    "writeoff_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


def build_sales_supply_chain_config():
    return {
        "basic": {
            "name": "erp_sales_supply_chain_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "inventory", "sales", "supply_chain"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "inventory": {
                "features": {
                    "multi_warehouse": True,
                    "warehouse_required_on_transaction": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "sales": {
                "features": {
                    "approval": False,
                    "credit_control": False,
                    "partial_shipment": True,
                    "outbound_auto_ar": False,
                    "customer_blacklist_block": True,
                    "price_editable": True,
                },
                "workflows": {
                    "sales_order_submit": "auto_approve",
                },
                "field_rules": {},
                "defaults": {},
            },
            "supply_chain": {
                "features": {
                    "outbound_requires_allocation": True,
                    "transfer_enabled": True,
                    "transfer_approval": True,
                    "sales_return_enabled": False,
                    "purchase_return_enabled": False,
                    "return_approval": False,
                    "inventory_alert_enabled": False,
                    "trace_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


def build_crm_supplier_config():
    return {
        "basic": {
            "name": "erp_crm_supplier_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "crm", "supplier"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "crm": {
                "features": {
                    "customer_approval": False,
                    "customer_code_auto_generate": True,
                    "credit_limit_enabled": True,
                    "follow_record_enabled": True,
                    "customer_transfer_enabled": True,
                    "customer_attachment_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "supplier": {
                "features": {
                    "supplier_approval": False,
                    "supplier_code_auto_generate": True,
                    "supplier_credit_management": False,
                    "supplier_rating_enabled": True,
                    "supplier_attachment_enabled": True,
                    "supplier_owner_transfer_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


def build_ar_finance_accounting_config():
    return {
        "basic": {
            "name": "erp_ar_finance_accounting_config",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["system", "platform", "crm", "ar_receivable", "ap_payable", "finance", "accounting"],
        "module_configs": {
            "system": build_system_module_config(),
            "platform": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            "crm": {
                "features": {
                    "customer_approval": False,
                    "customer_code_auto_generate": True,
                    "credit_limit_enabled": True,
                    "follow_record_enabled": True,
                    "customer_transfer_enabled": True,
                    "customer_attachment_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "ar_receivable": {
                "features": {
                    "auto_create_receivable": True,
                    "receipt_approval": True,
                    "allow_partial_receipt": True,
                    "overdue_tracking": True,
                    "customer_reconciliation_enabled": True,
                    "writeoff_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "ap_payable": {
                "features": {
                    "auto_create_payable": True,
                    "payment_approval": True,
                    "allow_partial_payment": True,
                    "supplier_reconciliation_enabled": True,
                    "allocation_enabled": True,
                    "writeoff_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "finance": {
                "features": {
                    "multi_cash_account": True,
                    "reconciliation_enabled": True,
                    "opening_balance_editable": False,
                    "cash_flow_analysis_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
            "accounting": {
                "features": {
                    "voucher_auto_posting": True,
                    "period_close_enabled": True,
                    "subject_editable_after_init": True,
                    "ar_ap_posting_enabled": True,
                    "inventory_posting_enabled": False,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            },
        },
    }


class ERPUserProvisionServiceTest(TestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_auth_owner", password="password")
        self.inventory_view = Permission.objects.create(name="查看商品", code="inventory:product:view", type="BUTTON")
        self.inventory_menu = Permission.objects.create(name="库存管理", code="inventory", type="MENU")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_auth_bp",
            name="ERP Auth BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Auth SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(code="erp-auth-tenant", name="ERP Auth Tenant", status="ACTIVE")

    def test_ensure_tenant_super_admin_creates_admin_once(self):
        first = ERPUserProvisionService.ensure_tenant_super_admin(tenant=self.tenant)
        second = ERPUserProvisionService.ensure_tenant_super_admin(tenant=self.tenant)

        self.assertTrue(first.created)
        self.assertTrue(first.initial_password)
        self.assertFalse(second.created)
        self.assertEqual(ERPUser.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(ERPRole.objects.filter(tenant=self.tenant).count(), 1)
        self.assertTrue(first.user.check_password(first.initial_password))
        self.assertTrue(first.user.roles.filter(is_system=True, data_scope="ALL", status=True).exists())
        self.assertTrue(first.user.must_change_password)
        granted_codes = set(first.role.permissions.values_list("code", flat=True))
        self.assertTrue({"system", "system:user", "user:create", "inventory", "inventory:product:view"}.issubset(granted_codes))

    def test_bind_instance_to_tenant_provisions_initial_admin_and_applies_snapshot(self):
        result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.instance_id, self.instance.id)
        self.assertIsNotNone(result.snapshot)
        self.assertTrue(result.initial_admin.created)
        self.assertEqual(result.initial_admin.user.tenant_id, self.tenant.id)
        self.assertTrue(self.tenant.active_config_snapshot is not None)

    def test_ensure_tenant_super_admin_respects_user_limit(self):
        self.tenant.user_limit = 0
        self.tenant.save(update_fields=["user_limit"])

        with self.assertRaises(ValidationError):
            ERPUserProvisionService.ensure_tenant_super_admin(tenant=self.tenant)


class ERPAuthApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_login_owner", password="password")
        self.inventory_view = Permission.objects.create(name="查看商品", code="inventory:product:view", type="BUTTON")
        self.inventory_menu = Permission.objects.create(name="库存管理", code="inventory", type="MENU")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_login_bp",
            name="ERP Login BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Login SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="login-tenant",
            name="Login Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.initial_password = bind_result.initial_admin.initial_password

    def test_login_returns_erp_tokens_and_tenant_context(self):
        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["tenant"]["code"], self.tenant.code)
        self.assertTrue(response.data["must_change_password"])

    def test_login_rejects_cross_tenant_user(self):
        other_tenant = Tenant.objects.create(
            code="other-tenant",
            name="Other Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        ERPUserProvisionService.ensure_tenant_super_admin(tenant=other_tenant)

        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": other_tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_returns_current_erp_user(self):
        login_response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}")

        response = self.client.get("/api/erp-auth/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], self.erp_user.username)
        self.assertEqual(response.data["tenant"]["code"], self.tenant.code)
        self.assertTrue(response.data["must_change_password"])
        granted_codes = set(response.data["permissions"])
        self.assertTrue({"system", "system:user", "user:create", "inventory", "inventory:product:view"}.issubset(granted_codes))

    def test_change_password_clears_must_change_password_and_allows_relogin(self):
        login_response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}")

        response = self.client.post(
            "/api/erp-auth/change-password/",
            {
                "current_password": self.initial_password,
                "new_password": "new-password-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.erp_user.refresh_from_db()
        self.assertFalse(self.erp_user.must_change_password)
        self.assertTrue(self.erp_user.check_password("new-password-123"))

        relogin_response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": "new-password-123",
            },
            format="json",
        )
        self.assertEqual(relogin_response.status_code, status.HTTP_200_OK)

    def test_refresh_returns_new_access_token(self):
        login_response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )

        response = self.client.post(
            "/api/erp-auth/refresh/",
            {"refresh": login_response.data["refresh"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertNotEqual(response.data["refresh"], login_response.data["refresh"])

        second_response = self.client.post(
            "/api/erp-auth/refresh/",
            {"refresh": response.data["refresh"]},
            format="json",
        )

        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", second_response.data)

    def test_runtime_config_accepts_erp_token(self):
        login_response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}")

        response = self.client.get("/api/tenant/runtime-config/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["tenant"]["code"], self.tenant.code)
        self.assertIsNone(response.data["instance"])


class ERPUserManagementApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_user_owner", password="password")
        for name, code, permission_type in (
            ("用户管理", "system:user", "MENU"),
            ("新增用户", "user:create", "BUTTON"),
            ("编辑用户", "user:update", "BUTTON"),
            ("角色管理", "system:role", "MENU"),
        ):
            Permission.objects.create(name=name, code=code, type=permission_type)
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_user_manage_bp",
            name="ERP User Manage BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP User Manage SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-user-tenant",
            name="ERP User Tenant",
            status="ACTIVE",
            instance=self.instance,
            user_limit=2,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.initial_password = bind_result.initial_admin.initial_password
        self.staff_role = ERPRole.objects.create(
            tenant=self.tenant,
            name="员工",
            code="staff",
            data_scope="SELF",
            status=True,
        )
        self.active_department = ERPDepartment.objects.create(
            tenant=self.tenant,
            name="销售部",
            status=True,
        )
        self.disabled_department = ERPDepartment.objects.create(
            tenant=self.tenant,
            name="停用部门",
            status=False,
        )

    def login(self):
        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_list_users_is_scoped_to_current_tenant(self):
        other_tenant = Tenant.objects.create(
            code="erp-other-tenant",
            name="ERP Other Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        ERPUserProvisionService.ensure_tenant_super_admin(tenant=other_tenant)
        self.login()

        response = self.client.get("/api/erp-auth/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        usernames = {item["username"] for item in response.data}
        self.assertEqual(usernames, {self.erp_user.username})

    def test_role_list_is_scoped_to_current_tenant(self):
        other_tenant = Tenant.objects.create(
            code="erp-role-other",
            name="ERP Role Other",
            status="ACTIVE",
            instance=self.instance,
        )
        ERPUserProvisionService.ensure_tenant_super_admin(tenant=other_tenant)
        ERPRole.objects.create(
            tenant=other_tenant,
            name="Other Role",
            code="other-role",
            data_scope="SELF",
            status=True,
        )
        self.login()

        response = self.client.get("/api/erp-auth/roles/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tenant_ids = {item["tenant"] for item in response.data}
        self.assertEqual(tenant_ids, {self.tenant.id})

    def test_role_crud_supports_permission_binding(self):
        self.login()
        menu_permission = ERPPermission.objects.get(code="system:user")
        button_permission = ERPPermission.objects.get(code="user:create")

        create_response = self.client.post(
            "/api/erp-auth/roles/",
            {
                "name": "审批员",
                "data_scope": "DEPARTMENT",
                "status": True,
                "permission_ids": [button_permission.id, menu_permission.id],
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        created_role = ERPRole.objects.get(tenant=self.tenant, name="审批员")
        self.assertTrue(created_role.code.startswith(f"{self.tenant.code}-"))
        self.assertEqual(
            set(created_role.permissions.values_list("id", flat=True)),
            {menu_permission.id, button_permission.id},
        )

        update_response = self.client.put(
            f"/api/erp-auth/roles/{created_role.id}/",
            {
                "name": "审批主管",
                "data_scope": "SELF",
                "status": False,
                "permission_ids": [menu_permission.id],
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        created_role.refresh_from_db()
        self.assertEqual(created_role.name, "审批主管")
        self.assertFalse(created_role.status)
        self.assertEqual(set(created_role.permissions.values_list("id", flat=True)), {menu_permission.id})

        delete_response = self.client.delete(f"/api/erp-auth/roles/{created_role.id}/")

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ERPRole.objects.filter(id=created_role.id).exists())

    def test_permission_list_hides_doc_marked_pages_for_erp(self):
        self.login()

        response = self.client.get("/api/erp-auth/permissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        permission_codes = {item["code"] for item in response.data}
        self.assertNotIn("system:perm", permission_codes)
        self.assertFalse(any(code.startswith("platform:dict") for code in permission_codes))
        self.assertFalse(any(code.startswith("platform:coderule") for code in permission_codes))

    def test_system_feature_flags_filter_permissions_and_api_access(self):
        limited_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v-system-limited",
            config_json={
                **build_config(),
                "module_configs": {
                    **build_config()["module_configs"],
                    "system": build_system_module_config(
                        role_management=False,
                        operation_log=False,
                    ),
                },
            },
            created_by=self.platform_user,
            is_published=False,
        )
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=limited_version)
        self.login()

        me_response = self.client.get("/api/erp-auth/me/")

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        permission_codes = set(me_response.data["permissions"])
        self.assertIn("system:user", permission_codes)
        self.assertNotIn("system:role", permission_codes)
        self.assertNotIn("system:log", permission_codes)

        role_response = self.client.get("/api/erp-auth/roles/")
        log_response = self.client.get("/api/system/logs/")

        self.assertEqual(role_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(log_response.status_code, status.HTTP_403_FORBIDDEN)


    def test_create_user_respects_tenant_limit(self):
        self.login()

        ok_response = self.client.post(
            "/api/erp-auth/users/",
            {
                "username": "operator",
                "name": "操作员",
                "password": "operator-123",
                "status": True,
                "role_ids": [self.staff_role.id],
            },
            format="json",
        )

        self.assertEqual(ok_response.status_code, status.HTTP_201_CREATED)
        created_user = ERPUser.objects.get(tenant=self.tenant, username="operator")
        self.assertTrue(created_user.must_change_password)
        self.assertEqual(set(created_user.roles.values_list("id", flat=True)), {self.staff_role.id})

        limit_response = self.client.post(
            "/api/erp-auth/users/",
            {
                "username": "operator2",
                "name": "操作员2",
                "password": "operator2-123",
                "status": True,
            },
            format="json",
        )

        self.assertEqual(limit_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("租户用户数已达上限", str(limit_response.data))

    def test_create_user_can_assign_super_admin_role(self):
        self.tenant.user_limit = 3
        self.tenant.save(update_fields=["user_limit"])
        self.login()

        super_admin_role = self.erp_user.roles.get(is_system=True, data_scope="ALL")
        response = self.client.post(
            "/api/erp-auth/users/",
            {
                "username": "tenant_admin_2",
                "name": "租户管理员2",
                "password": "tenant-admin-123",
                "status": True,
                "role_ids": [super_admin_role.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_user = ERPUser.objects.prefetch_related("roles__permissions").get(
            tenant=self.tenant,
            username="tenant_admin_2",
        )
        self.assertTrue(created_user.roles.exists())
        role = created_user.roles.first()
        self.assertEqual(role.name, "租户超级管理员")
        self.assertTrue(role.is_system)
        self.assertEqual(role.data_scope, "ALL")
        self.assertIn("system:user", set(role.permissions.values_list("code", flat=True)))

    def test_create_user_rejects_disabled_department(self):
        self.login()

        response = self.client.post(
            "/api/erp-auth/users/",
            {
                "username": "disabled_dept_user",
                "name": "停用部门用户",
                "password": "operator-123",
                "status": True,
                "dept": self.disabled_department.id,
                "role_ids": [self.staff_role.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("禁用部门不能绑定用户", str(response.data))

    def test_create_user_rejects_disabled_role(self):
        self.login()
        self.staff_role.status = False
        self.staff_role.save(update_fields=["status"])

        response = self.client.post(
            "/api/erp-auth/users/",
            {
                "username": "disabled_role_user",
                "name": "禁用角色用户",
                "password": "operator-123",
                "status": True,
                "role_ids": [self.staff_role.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("禁用角色不能分配给用户", str(response.data))

    def test_delete_department_is_blocked_when_users_or_children_exist(self):
        self.login()
        ERPUser.objects.create_user(
            tenant=self.tenant,
            username="dept_user",
            password="password-123",
            dept=self.active_department,
        )
        child_department = ERPDepartment.objects.create(
            tenant=self.tenant,
            name="销售一组",
            parent=self.active_department,
            status=True,
        )

        user_bound_response = self.client.delete(f"/api/erp-auth/departments/{self.active_department.id}/")
        self.assertEqual(user_bound_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("子部门", str(user_bound_response.data))

        child_department.delete()
        user_bound_response = self.client.delete(f"/api/erp-auth/departments/{self.active_department.id}/")
        self.assertEqual(user_bound_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("用户绑定", str(user_bound_response.data))

    def test_delete_role_is_blocked_when_assigned_to_user(self):
        self.login()
        target_role = ERPRole.objects.create(
            tenant=self.tenant,
            name="绑定角色",
            code="bound-role",
            data_scope="SELF",
            status=True,
        )
        target_user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="bound_role_user",
            password="password-123",
        )
        target_user.roles.add(target_role)

        response = self.client.delete(f"/api/erp-auth/roles/{target_role.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("已分配给用户", str(response.data))


class ERPUserPurchaseFlowTest(TestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_purchase_owner", password="password")
        Permission.objects.create(name="查看采购订单", code="purchase:order:view", type="BUTTON")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_purchase_bp",
            name="ERP Purchase BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_purchase_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Purchase SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-purchase-tenant",
            name="ERP Purchase Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.supplier = Supplier.objects.create(
            supplier_code="SUP-ERP-001",
            supplier_name="ERP Supplier",
            status="ACTIVE",
        )
        self.category = ProductCategory.objects.create(name="ERP Category")
        self.unit = Unit.objects.create(name="ERP Unit", code="ERP-UNIT")
        self.product = Product.objects.create(
            product_code="ERP-P001",
            name="ERP Product",
            category=self.category,
            unit=self.unit,
            cost_price="10.00",
            sale_price="15.00",
            status="ACTIVE",
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="ERP-W001",
            warehouse_name="ERP Warehouse",
        )

    @patch("business_apps.accounting.services.PostingService.post_purchase_receipt")
    @patch("business_apps.ap_payable.services.APService.generate_ap_from_receipt")
    def test_erp_user_can_create_and_execute_purchase_receipt_without_platform_user_fk(
        self,
        mock_generate_ap,
        mock_post_purchase_receipt,
    ):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": "5.000",
                    "unit_price": "10.00",
                }
            ],
            user=self.erp_user,
        )
        PurchaseOrderService.submit_order(order, self.erp_user)
        order.refresh_from_db()

        receipt = PurchaseOrderService.create_receipt(
            order=order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "purchase_order_item": order.items.get(),
                    "received_quantity": "5.000",
                }
            ],
            user=self.erp_user,
        )
        completed_receipt = PurchaseOrderService.complete_receipt(receipt, self.erp_user)

        order.refresh_from_db()
        completed_receipt.refresh_from_db()
        transaction = InventoryTransaction.objects.get(reference_type="PURCHASE_RECEIPT", reference_id=completed_receipt.id)

        self.assertIsNone(order.created_by)
        self.assertIsNone(order.submitted_by)
        self.assertIsNone(completed_receipt.created_by)
        self.assertIsNone(completed_receipt.executed_by)
        self.assertIsNone(transaction.operator)
        self.assertEqual(order.status, "RECEIVED")
        self.assertEqual(completed_receipt.status, "COMPLETED")
        mock_generate_ap.assert_not_called()
        mock_post_purchase_receipt.assert_called_once()

    def test_purchase_receipt_api_uses_default_warehouse_in_single_warehouse_mode(self):
        single_version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_purchase_single_warehouse_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        TenantService.apply_blueprint_version(tenant=self.tenant, blueprint_version=single_version)
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": None,
                    "quantity": "5.000",
                    "unit_price": "10.00",
                }
            ],
            user=self.erp_user,
        )
        PurchaseOrderService.submit_order(order, self.erp_user)
        order.refresh_from_db()

        client = APIClient()
        client.force_authenticate(self.erp_user)
        response = client.post(
            "/api/purchase/receipts/",
            {
                "purchase_order": order.id,
                "items": [
                    {
                        "purchase_order_item": order.items.get().id,
                        "received_quantity": "5.000",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["warehouse_name"], "默认仓库")

    def test_purchase_receipt_rejects_when_other_draft_receipt_already_occupies_quantity(self):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": "12.000",
                    "unit_price": "10.00",
                }
            ],
            user=self.erp_user,
        )
        PurchaseOrderService.submit_order(order, self.erp_user)
        order.refresh_from_db()
        po_item = order.items.get()

        PurchaseOrderService.create_receipt(
            order=order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "purchase_order_item": po_item,
                    "received_quantity": "12.000",
                }
            ],
            user=self.erp_user,
        )

        with self.assertRaisesMessage(ValueError, "待入库数量已被其他草稿入库单占用"):
            PurchaseOrderService.create_receipt(
                order=order,
                warehouse=self.warehouse,
                items_data=[
                    {
                        "purchase_order_item": po_item,
                        "received_quantity": "12.000",
                    }
                ],
                user=self.erp_user,
            )


class ERPUserSalesOutboundFlowTest(TestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_sales_owner", password="password")
        Permission.objects.create(name="查看销售订单", code="sales:order:view", type="BUTTON")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_sales_bp",
            name="ERP Sales BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_sales_supply_chain_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Sales SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-sales-tenant",
            name="ERP Sales Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.customer = Customer.objects.create(
            customer_code="CUS-ERP-001",
            customer_name="ERP Customer",
            status="ACTIVE",
            credit_limit="100000.00",
        )
        self.category = ProductCategory.objects.create(name="ERP Sales Category")
        self.unit = Unit.objects.create(name="ERP Sales Unit", code="ERP-SALES-UNIT")
        self.product = Product.objects.create(
            product_code="ERP-S001",
            name="ERP Sales Product",
            category=self.category,
            unit=self.unit,
            cost_price="10.00",
            sale_price="15.00",
            status="ACTIVE",
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="ERP-S-W001",
            warehouse_name="ERP Sales Warehouse",
        )
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity="20.000",
            transaction_type="MANUAL_ADJUST",
            operator=self.erp_user,
            remark="seed sales stock",
        )

    @patch("business_apps.accounting.services.PostingService.post_sales_outbound")
    @patch("business_apps.ar_receivable.services.ARService.generate_ar_from_outbound")
    def test_erp_user_can_complete_sales_outbound_without_platform_user_fk(
        self,
        mock_generate_ar,
        mock_post_sales_outbound,
    ):
        order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": "5.000",
                    "unit_price": "15.00",
                }
            ],
            user=self.erp_user,
        )
        SalesOrderService.submit_order(order, self.erp_user)
        order.refresh_from_db()

        allocated_order = SalesOrderService.allocate_stock(order, self.erp_user)
        self.assertIsInstance(allocated_order, SalesOrder)
        outbound_requests = SalesOrderService.create_outbound_request(
            order,
            shipment_items_data=[
                {
                    "order_item": order.items.get(),
                    "quantity": "5.000",
                }
            ],
            user=self.erp_user,
        )
        outbound = outbound_requests[0]
        OutboundService.submit_order(outbound, self.erp_user)
        OutboundService.approve_order(outbound, self.erp_user)
        OutboundService.complete_order(outbound, self.erp_user)

        order.refresh_from_db()
        outbound.refresh_from_db()
        shipping_tx = InventoryTransaction.objects.get(
            reference_type="OUTBOUND_ORDER",
            reference_id=outbound.id,
            transaction_type="SALE_OUT",
        )
        auto_approve_log = OrderApprovalLog.objects.get(order=order, action="AUTO_APPROVE")
        execution_actions = list(
            order.execution_logs.order_by("created_at").values_list("action", flat=True)
        )

        self.assertIsNone(order.created_by)
        self.assertIsNone(order.submitted_by)
        self.assertIsNone(auto_approve_log.approved_by)
        self.assertEqual(order.status, "SHIPPED")
        self.assertEqual(order.items.get().allocated_quantity, 0)
        self.assertEqual(order.items.get().shipped_quantity, 5)
        self.assertEqual(execution_actions, [
            SalesExecutionLog.ACTION_SUBMIT,
            SalesExecutionLog.ACTION_ALLOCATE,
            SalesExecutionLog.ACTION_CREATE_OUTBOUND,
        ])
        self.assertEqual(order.execution_logs.filter(operator__isnull=True).count(), 3)

        self.assertIsNone(outbound.created_by)
        self.assertIsNone(outbound.submitted_by)
        self.assertIsNone(outbound.approved_by)
        self.assertEqual(outbound.status, "COMPLETED")

        self.assertIsNone(shipping_tx.operator)
        mock_generate_ar.assert_not_called()
        mock_post_sales_outbound.assert_called_once()

    def test_sales_order_rejects_quantity_exceeding_other_open_order_commitment(self):
        SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": "12.000",
                    "unit_price": "15.00",
                }
            ],
            user=self.erp_user,
        )

        with self.assertRaisesMessage(ValueError, "其他未完成销售单已占用12.000"):
            SalesOrderService.create_order(
                customer=self.customer,
                items_data=[
                    {
                        "product": self.product,
                        "warehouse": self.warehouse,
                        "quantity": "9.000",
                        "unit_price": "15.00",
                    }
                ],
                user=self.erp_user,
            )

class ERPFinanceCashAccountApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_finance_owner", password="password")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_finance_bp",
            name="ERP Finance BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_finance_cash_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Finance SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-finance-tenant",
            name="ERP Finance Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.initial_password = bind_result.initial_admin.initial_password

    def login(self):
        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_create_cash_account_assigns_tenant_and_is_visible_in_list(self):
        self.login()

        create_response = self.client.post(
            "/api/finance/cash-accounts/",
            {
                "name": "主资金账户",
                "type": "BANK",
                "account_type": "BANK",
                "account_no": "62220001",
                "bank_name": "测试银行",
                "currency": "CNY",
                "current_balance": "1000.00",
                "status": True,
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        account = CashAccount.objects.get(id=create_response.data["id"])
        self.assertEqual(account.tenant_id, self.tenant.id)

        list_response = self.client.get("/api/finance/cash-accounts/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in list_response.data], [account.id])


class ERPPlatformIsolationApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_platform_owner", password="password")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_platform_bp",
            name="ERP Platform BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_platform_file_config(dict_center=True),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Platform SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-platform-tenant-a",
            name="ERP Platform Tenant A",
            status="ACTIVE",
            instance=self.instance,
        )
        self.other_tenant = Tenant.objects.create(
            code="erp-platform-tenant-b",
            name="ERP Platform Tenant B",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        other_bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.other_tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.initial_password = bind_result.initial_admin.initial_password
        self.other_erp_user = other_bind_result.initial_admin.user
        self.dict_type = DictType.objects.create(
            dict_code="PRIVATE_LEVELS",
            dict_name="私有等级",
            created_by=self.other_erp_user,
        )
        DictItem.objects.create(
            dict_type=self.dict_type,
            item_code="L1",
            item_name="一级",
            status="ACTIVE",
        )

    def login(self):
        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_business_files_is_scoped_to_current_tenant(self):
        File.objects.create(
            file_name="tenant-a.txt",
            file_ext=".txt",
            mime_type="text/plain",
            file_size=10,
            storage_type="LOCAL",
            bucket="",
            object_key="uploads/a.txt",
            file_url="/media/uploads/a.txt",
            md5="a" * 32,
            module="customer",
            business_type="customer",
            business_id=101,
            access_level="BUSINESS",
            uploaded_by=self.erp_user,
        )
        File.objects.create(
            file_name="tenant-b.txt",
            file_ext=".txt",
            mime_type="text/plain",
            file_size=10,
            storage_type="LOCAL",
            bucket="",
            object_key="uploads/b.txt",
            file_url="/media/uploads/b.txt",
            md5="b" * 32,
            module="customer",
            business_type="customer",
            business_id=101,
            access_level="BUSINESS",
            uploaded_by=self.other_erp_user,
        )
        self.login()

        response = self.client.get(
            "/api/platform/files/business/",
            {
                "module": "customer",
                "business_type": "customer",
                "business_id": 101,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["file_name"] for item in response.data], ["tenant-a.txt"])

    def test_dict_items_by_code_requires_explicit_permission(self):
        self.login()

        response = self.client.get(f"/api/platform/dict/items/{self.dict_type.dict_code}")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ERPSupplyChainTraceIsolationApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_trace_owner", password="password")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_trace_bp",
            name="ERP Trace BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_sales_supply_chain_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Trace SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-trace-tenant-a",
            name="ERP Trace Tenant A",
            status="ACTIVE",
            instance=self.instance,
        )
        self.other_tenant = Tenant.objects.create(
            code="erp-trace-tenant-b",
            name="ERP Trace Tenant B",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        other_bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.other_tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.initial_password = bind_result.initial_admin.initial_password
        self.other_erp_user = other_bind_result.initial_admin.user
        self.category = ProductCategory.objects.create(name="Trace Category A", tenant=self.tenant, status=True)
        self.unit = Unit.objects.create(name="箱", code="TRACE-UNIT-A", tenant=self.tenant, status=True)
        self.product = Product.objects.create(
            tenant=self.tenant,
            product_code="TRACE-PROD-A",
            name="Trace Product A",
            category=self.category,
            unit=self.unit,
            status="ACTIVE",
        )
        self.warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="TRACE-WH-A",
            warehouse_name="Trace Warehouse A",
            status=True,
        )
        self.other_category = ProductCategory.objects.create(name="Trace Category B", tenant=self.other_tenant, status=True)
        self.other_unit = Unit.objects.create(name="袋", code="TRACE-UNIT-B", tenant=self.other_tenant, status=True)
        self.other_product = Product.objects.create(
            tenant=self.other_tenant,
            product_code="TRACE-PROD-B",
            name="Trace Product B",
            category=self.other_category,
            unit=self.other_unit,
            status="ACTIVE",
        )
        self.other_warehouse = Warehouse.objects.create(
            tenant=self.other_tenant,
            warehouse_code="TRACE-WH-B",
            warehouse_name="Trace Warehouse B",
            status=True,
        )
        self.transaction = InventoryTransaction.objects.create(
            tenant=self.tenant,
            transaction_no="TRACE-TX-A",
            warehouse=self.warehouse,
            product=self.product,
            transaction_type="MANUAL_ADJUST",
            direction="IN",
            quantity="5.000",
            before_qty="0.000",
            after_qty="5.000",
            operator=self.erp_user,
        )
        InventoryTransaction.objects.create(
            tenant=self.other_tenant,
            transaction_no="TRACE-TX-B",
            warehouse=self.other_warehouse,
            product=self.other_product,
            transaction_type="MANUAL_ADJUST",
            direction="IN",
            quantity="9.000",
            before_qty="0.000",
            after_qty="9.000",
            operator=self.other_erp_user,
        )

    def login(self):
        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_inventory_trace_is_scoped_to_current_tenant(self):
        self.login()

        own_response = self.client.get("/api/supply-chain/trace/", {"product_id": self.product.id})
        other_response = self.client.get("/api/supply-chain/trace/", {"product_id": self.other_product.id})

        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in own_response.data], [self.transaction.id])
        self.assertEqual(other_response.status_code, status.HTTP_200_OK)
        self.assertEqual(other_response.data, [])


class ERPAccountingIsolationApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_accounting_owner", password="password")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_accounting_bp",
            name="ERP Accounting BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_ar_finance_accounting_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Accounting SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-accounting-tenant-a",
            name="ERP Accounting Tenant A",
            status="ACTIVE",
            instance=self.instance,
        )
        self.other_tenant = Tenant.objects.create(
            code="erp-accounting-tenant-b",
            name="ERP Accounting Tenant B",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        TenantService.bind_instance_to_tenant(
            tenant=self.other_tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.initial_password = bind_result.initial_admin.initial_password
        self.subject = AccountSubject.objects.create(
            tenant=self.tenant,
            code="1101-A",
            name="Tenant A 科目",
            category="ASSET",
            balance_direction="DEBIT",
            level=1,
            is_leaf=True,
            enabled=True,
            created_by=self.erp_user,
        )
        self.other_subject = AccountSubject.objects.create(
            tenant=self.other_tenant,
            code="1101-B",
            name="Tenant B 科目",
            category="ASSET",
            balance_direction="DEBIT",
            level=1,
            is_leaf=True,
            enabled=True,
        )

    def login(self):
        response = self.client.post(
            "/api/erp-auth/login/",
            {
                "tenant_code": self.tenant.code,
                "username": self.erp_user.username,
                "password": self.initial_password,
            },
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_account_subject_update_rejects_cross_tenant_parent(self):
        self.login()

        response = self.client.patch(
            f"/api/accounting/subjects/{self.subject.id}/",
            {"parent": self.other_subject.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.subject.refresh_from_db()
        self.assertIsNone(self.subject.parent_id)


class ERPUserMasterDataApiTest(APITestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_masterdata_owner", password="password")
        Permission.objects.bulk_create(
            [
                Permission(name="创建客户", code="crm:customer:create", type="BUTTON"),
                Permission(name="查看客户", code="crm:customer:view", type="BUTTON"),
                Permission(name="转移客户", code="crm:customer:transfer", type="BUTTON"),
                Permission(name="创建供应商", code="supplier:supplier:create", type="BUTTON"),
                Permission(name="查看供应商", code="supplier:supplier:view", type="BUTTON"),
                Permission(name="转移供应商", code="supplier:supplier:transfer", type="BUTTON"),
            ]
        )
        self.blueprint = SystemBlueprint.objects.create(
            key="erp-masterdata-bp",
            name="ERP MasterData BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_crm_supplier_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP MasterData SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-masterdata-tenant",
            name="ERP MasterData Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.other_tenant = Tenant.objects.create(
            code="erp-masterdata-tenant-2",
            name="ERP MasterData Tenant 2",
            status="ACTIVE",
            instance=self.instance,
        )
        other_bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.other_tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.other_erp_user = other_bind_result.initial_admin.user
        self.client.force_authenticate(self.erp_user)

    def test_erp_user_can_create_customer_follow_record_and_attachment_with_erp_owner(self):
        customer_response = self.client.post(
            "/api/crm/customers/",
            {
                "customer_name": "ERP 客户",
                "customer_type": "COMPANY",
                "customer_level": "B",
                "status": "ACTIVE",
                "phone": "13900000001",
                "email": "erp-customer@example.com",
                "payment_term": "NET_30",
                "default_payment_method": "BANK_TRANSFER",
                "credit_control_mode": "BLOCK",
                "credit_limit": "1000.00",
            },
            format="json",
        )
        self.assertEqual(customer_response.status_code, status.HTTP_201_CREATED)
        customer = Customer.objects.get(id=customer_response.data["id"])

        follow_response = self.client.post(
            "/api/crm/follow-records/",
            {
                "customer": customer.id,
                "follow_type": "PHONE",
                "content": "ERP 跟进",
            },
            format="json",
        )
        attachment_response = self.client.post(
            "/api/crm/attachments/",
            {
                "customer": customer.id,
                "file_name": "customer.txt",
                "file_url": "https://example.com/customer.txt",
                "file_size": 12,
            },
            format="json",
        )

        self.assertEqual(follow_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(attachment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(customer.owner_id, self.erp_user.id)
        self.assertIsNone(customer.created_by)
        self.assertIsNone(FollowRecord.objects.get(id=follow_response.data["id"]).created_by)
        self.assertIsNone(CustomerAttachment.objects.get(id=attachment_response.data["id"]).uploaded_by)

    def test_erp_user_can_create_supplier_follow_record_evaluation_and_attachment_with_erp_owner(self):
        supplier_response = self.client.post(
            "/api/supplier/suppliers/",
            {
                "supplier_name": "ERP 供应商",
                "supplier_type": "MANUFACTURER",
                "supplier_level": "B",
                "status": "ACTIVE",
                "tax_number": "91310000ERP00001",
                "contact_phone": "13800000002",
                "email": "erp-supplier@example.com",
                "payment_term": "NET_30",
                "default_payment_method": "BANK_TRANSFER",
                "settlement_cycle": "PER_RECEIPT",
                "currency": "CNY",
                "tax_rate": "0.13",
            },
            format="json",
        )
        self.assertEqual(supplier_response.status_code, status.HTTP_201_CREATED)
        supplier = Supplier.objects.get(id=supplier_response.data["id"])

        follow_response = self.client.post(
            "/api/supplier/follow-records/",
            {
                "supplier": supplier.id,
                "follow_type": "PHONE",
                "content": "ERP 供应商跟进",
            },
            format="json",
        )
        evaluation_response = self.client.post(
            "/api/supplier/evaluations/",
            {
                "supplier": supplier.id,
                "quality_score": 5,
                "delivery_score": 4,
                "service_score": 4,
                "price_score": 4,
            },
            format="json",
        )
        attachment_response = self.client.post(
            "/api/supplier/attachments/",
            {
                "supplier": supplier.id,
                "file_name": "supplier.txt",
                "file_url": "https://example.com/supplier.txt",
                "file_size": 24,
            },
            format="json",
        )

        self.assertEqual(follow_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(evaluation_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(attachment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(supplier.owner_id, self.erp_user.id)
        self.assertIsNone(supplier.created_by)
        self.assertIsNone(SupplierFollowRecord.objects.get(id=follow_response.data["id"]).created_by)
        self.assertIsNone(SupplierEvaluation.objects.get(id=evaluation_response.data["id"]).evaluated_by)
        self.assertIsNone(SupplierAttachment.objects.get(id=attachment_response.data["id"]).uploaded_by)

    def test_erp_user_can_transfer_customer_and_supplier_to_same_tenant_erp_user(self):
        target_role = ERPRole.objects.create(
            tenant=self.tenant,
            name="业务员",
            code="sales",
            data_scope="SELF",
            status=True,
        )
        target_user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="target-owner",
            password="password-123",
            name="Target Owner",
            status=True,
            must_change_password=False,
        )
        target_user.roles.add(target_role)

        customer = Customer.objects.create(
            customer_code="CUS-ERP-TR-001",
            customer_name="待转移客户",
            status="ACTIVE",
            owner=self.erp_user,
        )
        supplier = Supplier.objects.create(
            supplier_code="SUP-ERP-TR-001",
            supplier_name="待转移供应商",
            status="ACTIVE",
            owner=self.erp_user,
        )

        customer_response = self.client.post(
            f"/api/crm/customers/{customer.id}/transfer/",
            {"new_owner_id": target_user.id, "remark": "customer transfer"},
            format="json",
        )
        supplier_response = self.client.post(
            f"/api/supplier/suppliers/{supplier.id}/transfer/",
            {"new_owner_id": target_user.id, "remark": "supplier transfer"},
            format="json",
        )

        self.assertEqual(customer_response.status_code, status.HTTP_200_OK)
        self.assertEqual(supplier_response.status_code, status.HTTP_200_OK)
        customer.refresh_from_db()
        supplier.refresh_from_db()
        self.assertEqual(customer.owner_id, target_user.id)
        self.assertEqual(supplier.owner_id, target_user.id)

    def test_erp_user_cannot_access_or_create_other_tenant_master_data(self):
        other_customer = Customer.objects.create(
            tenant=self.other_tenant,
            customer_code="CUS-OTHER-001",
            customer_name="其他租户客户",
            status="ACTIVE",
            owner=self.other_erp_user,
        )
        other_supplier = Supplier.objects.create(
            tenant=self.other_tenant,
            supplier_code="SUP-OTHER-001",
            supplier_name="其他租户供应商",
            status="ACTIVE",
            owner=self.other_erp_user,
        )

        customer_detail = self.client.get(f"/api/crm/customers/{other_customer.id}/")
        supplier_detail = self.client.get(f"/api/supplier/suppliers/{other_supplier.id}/")
        self.assertEqual(customer_detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(supplier_detail.status_code, status.HTTP_404_NOT_FOUND)

        customer_follow = self.client.post(
            "/api/crm/follow-records/",
            {
                "customer": other_customer.id,
                "follow_type": "PHONE",
                "content": "越权跟进",
            },
            format="json",
        )
        customer_attachment = self.client.post(
            "/api/crm/attachments/",
            {
                "customer": other_customer.id,
                "file_name": "cross-tenant.txt",
                "file_url": "https://example.com/cross-tenant.txt",
                "file_size": 1,
            },
            format="json",
        )
        supplier_follow = self.client.post(
            "/api/supplier/follow-records/",
            {
                "supplier": other_supplier.id,
                "follow_type": "PHONE",
                "content": "越权跟进",
            },
            format="json",
        )
        supplier_evaluation = self.client.post(
            "/api/supplier/evaluations/",
            {
                "supplier": other_supplier.id,
                "quality_score": 5,
                "delivery_score": 5,
                "service_score": 5,
                "price_score": 5,
            },
            format="json",
        )
        supplier_attachment = self.client.post(
            "/api/supplier/attachments/",
            {
                "supplier": other_supplier.id,
                "file_name": "cross-tenant.txt",
                "file_url": "https://example.com/cross-tenant.txt",
                "file_size": 1,
            },
            format="json",
        )

        self.assertEqual(customer_follow.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(customer_attachment.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(supplier_follow.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(supplier_evaluation.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(supplier_attachment.status_code, status.HTTP_400_BAD_REQUEST)


class ERPUserPurchaseAPFlowTest(TestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_purchase_ap_owner", password="password")
        Permission.objects.bulk_create(
            [
                Permission(name="查看采购订单", code="purchase:order:view", type="BUTTON"),
                Permission(name="查看仓库", code="inventory:warehouse:view", type="BUTTON"),
                Permission(name="创建仓库", code="inventory:warehouse:create", type="BUTTON"),
            ]
        )
        self.blueprint = SystemBlueprint.objects.create(
            key="erp_purchase_ap_bp",
            name="ERP Purchase AP BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_purchase_ap_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP Purchase AP SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-purchase-ap-tenant",
            name="ERP Purchase AP Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.supplier = Supplier.objects.create(
            supplier_code="SUP-ERP-AP-001",
            supplier_name="ERP AP Supplier",
            status="ACTIVE",
        )
        self.category = ProductCategory.objects.create(name="ERP AP Category")
        self.unit = Unit.objects.create(name="ERP AP Unit", code="ERP-AP-UNIT")
        self.product = Product.objects.create(
            product_code="ERP-AP-P001",
            name="ERP AP Product",
            category=self.category,
            unit=self.unit,
            cost_price="10.00",
            sale_price="15.00",
            status="ACTIVE",
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="ERP-AP-W001",
            warehouse_name="ERP AP Warehouse",
        )
        self.cash_account = CashAccount.objects.create(
            name="ERP AP Cash",
            type="BANK",
            account_type="BANK",
            current_balance=Decimal("1000.00"),
        )

    @patch("business_apps.accounting.services.PostingService.post_purchase_receipt")
    @patch("business_apps.accounting.services.PostingService.post_payment_execution")
    def test_erp_user_can_generate_ap_and_complete_payment_without_platform_user_fk(
        self,
        mock_post_payment_execution,
        mock_post_purchase_receipt,
    ):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": "5.000",
                    "unit_price": "10.00",
                }
            ],
            user=self.erp_user,
        )
        PurchaseOrderService.submit_order(order, self.erp_user)
        receipt = PurchaseOrderService.create_receipt(
            order=order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "purchase_order_item": order.items.get(),
                    "received_quantity": "5.000",
                }
            ],
            user=self.erp_user,
        )
        completed_receipt = PurchaseOrderService.complete_receipt(receipt, self.erp_user)
        ap_account = APAccount.objects.get(purchase_receipt=completed_receipt)

        payment = APService.create_payment(
            supplier=self.supplier,
            amount=Decimal("50.00"),
            payment_date=completed_receipt.received_at.date(),
            payment_method="BANK_TRANSFER",
            operator=self.erp_user,
            cash_account=self.cash_account,
            remark="ERP AP payment",
        )
        APService.submit_payment(payment, self.erp_user)
        APService.approve_payment(payment, self.erp_user)
        APService.execute_payment(payment, self.erp_user)
        APService.allocate_payment(
            payment,
            [{"ap_id": ap_account.id, "amount": Decimal("50.00")}],
            self.erp_user,
        )

        ap_account.refresh_from_db()
        payment.refresh_from_db()
        allocation = APAllocation.objects.get(payment=payment, ap_account=ap_account)

        self.assertIsNone(ap_account.created_by)
        self.assertIsNone(payment.created_by)
        self.assertIsNone(payment.submitted_by)
        self.assertIsNone(payment.approved_by)
        self.assertIsNone(allocation.created_by)
        self.assertEqual(ap_account.status, "PAID")
        self.assertEqual(ap_account.paid_amount, Decimal("50.00"))
        self.assertEqual(payment.status, "COMPLETED")
        self.assertIsNotNone(payment.executed_at)
        self.assertEqual(payment.allocated_amount, Decimal("50.00"))
        mock_post_purchase_receipt.assert_called_once()
        mock_post_payment_execution.assert_called_once()

    def test_erp_user_can_create_warehouse_with_erp_manager(self):
        target_role = ERPRole.objects.create(
            tenant=self.tenant,
            name="仓管",
            code="warehouse-clerk",
            data_scope="SELF",
            status=True,
        )
        target_user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="warehouse-manager",
            password="password-123",
            name="Warehouse Manager",
            status=True,
            must_change_password=False,
        )
        target_user.roles.add(target_role)

        client = APIClient()
        client.force_authenticate(self.erp_user)
        response = client.post(
            "/api/inventory/warehouses/",
            {
                "warehouse_name": "ERP 仓库",
                "type": "MAIN",
                "manager": target_user.id,
                "status": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        warehouse = Warehouse.objects.get(id=response.data["id"])
        self.assertEqual(warehouse.manager_id, target_user.id)

    def test_ap_account_list_supports_csv_status_filter(self):
        pending_account = APAccount.objects.create(
            tenant=self.tenant,
            ap_no="AP-FILTER-001",
            supplier=self.supplier,
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            due_date="2026-07-31",
            status="PENDING",
        )
        partial_account = APAccount.objects.create(
            tenant=self.tenant,
            ap_no="AP-FILTER-002",
            supplier=self.supplier,
            total_amount=Decimal("200.00"),
            paid_amount=Decimal("50.00"),
            due_date="2026-07-31",
            status="PARTIAL",
        )
        APAccount.objects.create(
            tenant=self.tenant,
            ap_no="AP-FILTER-003",
            supplier=self.supplier,
            total_amount=Decimal("300.00"),
            paid_amount=Decimal("300.00"),
            due_date="2026-07-31",
            status="PAID",
        )

        client = APIClient()
        client.force_authenticate(self.erp_user)
        response = client.get(
            f"/api/ap-payable/accounts/?supplier={self.supplier.id}&status=PENDING,PARTIAL"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item["id"] for item in response.data}
        self.assertEqual(returned_ids, {pending_account.id, partial_account.id})


class ERPUserARFinanceAccountingFlowTest(TestCase):
    def setUp(self):
        self.platform_user = User.objects.create_user(username="erp_ar_owner", password="password")
        Permission.objects.create(name="查看客户", code="crm:customer:view", type="BUTTON")
        self.blueprint = SystemBlueprint.objects.create(
            key="erp-ar-bp",
            name="ERP AR BP",
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_ar_finance_accounting_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name="ERP AR SaaS",
            mode="SAAS",
            runtime_mode="SAAS",
            status="ACTIVE",
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code="erp-ar-tenant",
            name="ERP AR Tenant",
            status="ACTIVE",
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user
        self.customer = Customer.objects.create(
            customer_code="CUS-ERP-AR-001",
            customer_name="ERP AR Customer",
            status="ACTIVE",
            credit_limit="100000.00",
            current_balance="120.00",
            credit_control_mode="BLOCK",
        )
        self.cash_account = CashAccount.objects.create(
            name="ERP AR Cash",
            type="BANK",
            account_type="BANK",
            current_balance=Decimal("500.00"),
        )
        SubjectInitService.init_subjects(created_by=self.platform_user)

    def test_erp_user_can_receipt_writeoff_and_post_voucher_without_platform_user_fk(self):
        receivable = Receivable.objects.create(
            receivable_no="AR-ERP-0001",
            customer=self.customer,
            source_type="MANUAL",
            amount=Decimal("120.00"),
            written_off_amount=Decimal("0.00"),
            due_date=self.version.created_at.date(),
            status="UNPAID",
        )

        receipt = ARService.create_receipt(
            customer=self.customer,
            amount=Decimal("120.00"),
            receipt_date=self.version.created_at.date(),
            payment_method="BANK_TRANSFER",
            operator=self.erp_user,
            cash_account=self.cash_account,
            reference_no="ERP-AR-REF",
            remark="ERP AR receipt",
        )
        ARService.approve_receipt(receipt, self.erp_user)
        ARService.execute_receipt(receipt, self.erp_user)
        ARService.write_off(receivable.id, receipt.id, Decimal("120.00"), self.erp_user)

        receivable.refresh_from_db()
        receipt.refresh_from_db()
        self.cash_account.refresh_from_db()
        write_off = WriteOff.objects.get(receivable=receivable, receipt=receipt)
        voucher = Voucher.objects.get(source_type="AR_RECEIPT", source_id=receipt.id)
        posting_log = BusinessPostingLog.objects.get(
            event_type="RECEIPT_EXECUTED",
            business_type="AR_RECEIPT",
            business_id=receipt.id,
        )

        self.assertIsNone(receivable.created_by)
        self.assertIsNone(receipt.created_by)
        self.assertIsNone(receipt.approved_by)
        self.assertIsNone(write_off.operator)
        self.assertIsNone(voucher.posted_by)
        self.assertIsNone(posting_log.created_by)
        self.assertEqual(receivable.status, "PAID")
        self.assertEqual(receivable.written_off_amount, Decimal("120.00"))
        self.assertEqual(receipt.status, "WRITTEN")
        self.assertIsNotNone(receipt.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal("620.00"))
