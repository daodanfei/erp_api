from decimal import Decimal

from django.test import TestCase

from business_apps.crm.models import Customer
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.inventory.policies import InventoryPolicy
from business_apps.inventory.services import InventoryService
from business_apps.purchase.models import PurchaseApprovalLog
from business_apps.purchase.policies import PurchasePolicy
from business_apps.purchase.services import PurchaseOrderService
from business_apps.sales.policies import SalesPolicy
from business_apps.sales.services import SalesOrderService
from business_apps.supplier.models import Supplier
from core_apps.authentication.models import User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser
from core_apps.tenant.services import build_runtime_config


def build_config(*, inventory_multi_warehouse=False, purchase_approval=False, sales_approval=False, credit_control=False):
    return {
        "basic": {
            "name": "policy_test",
            "industry": "trade",
            "mode": "saas",
        },
        "enabled_modules": ["inventory", "purchase", "sales"],
        "module_configs": {
            "inventory": {
                "features": {
                    "multi_warehouse": inventory_multi_warehouse,
                },
                "workflows": {},
                "field_rules": {
                    "inventory_transaction.warehouse": {
                        "visible": inventory_multi_warehouse,
                        "required": inventory_multi_warehouse,
                        "readonly": not inventory_multi_warehouse,
                    },
                    "purchase_order_item.warehouse": {
                        "visible": inventory_multi_warehouse,
                        "required": inventory_multi_warehouse,
                        "readonly": not inventory_multi_warehouse,
                    },
                    "sales_order_item.warehouse": {
                        "visible": inventory_multi_warehouse,
                        "required": inventory_multi_warehouse,
                        "readonly": not inventory_multi_warehouse,
                    },
                },
                "defaults": {
                    "default_warehouse_code": "MAIN",
                },
            },
            "purchase": {
                "features": {
                    "approval": purchase_approval,
                    "partial_receipt": True,
                },
                "workflows": {
                    "purchase_order_submit": "manual_approve" if purchase_approval else "auto_approve",
                },
                "field_rules": {},
                "defaults": {},
            },
            "sales": {
                "features": {
                    "approval": sales_approval,
                    "credit_control": credit_control,
                },
                "workflows": {
                    "sales_order_submit": "manual_approve" if sales_approval else "auto_approve",
                },
                "field_rules": {},
                "defaults": {},
            },
        },
    }


class PolicyExecutionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="policy_user", password="password")
        self.approver = User.objects.create_user(username="policy_approver", password="password")
        self.tenant = Tenant.objects.create(code="policy-tenant", name="Policy Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=self.tenant, user=self.user, is_default=True, is_owner=True)
        TenantUser.objects.create(tenant=self.tenant, user=self.approver)
        self.blueprint = SystemBlueprint.objects.create(key="policy_bp", name="Policy BP", created_by=self.user)
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v1",
            config_json=build_config(),
            created_by=self.user,
            is_published=True,
        )
        TenantConfigSnapshot.objects.create(
            tenant=self.tenant,
            blueprint_version=self.version,
            config_json=self.version.config_json,
        )

        self.category = ProductCategory.objects.create(name="Policy Category")
        self.unit = Unit.objects.create(name="件", code="POLICY-PCS")
        self.product = Product.objects.create(
            product_code="POLICY-P001",
            name="Policy Product",
            category=self.category,
            unit=self.unit,
            cost_price=Decimal("10.00"),
            sale_price=Decimal("20.00"),
            status="ACTIVE",
            created_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="MAIN",
            warehouse_name="Main Warehouse",
            status=True,
        )
        self.supplier = Supplier.objects.create(
            supplier_code="POLICY-SUP-001",
            supplier_name="Policy Supplier",
            status="ACTIVE",
        )
        self.customer = Customer.objects.create(
            customer_code="POLICY-CUS-001",
            customer_name="Policy Customer",
            status="ACTIVE",
            credit_limit=Decimal("100.00"),
            current_balance=Decimal("90.00"),
            credit_control_mode="BLOCK",
            created_by=self.user,
            owner=self.user,
            dept=self.user.dept,
        )

    def test_purchase_submit_auto_approves_when_policy_disables_approval(self):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": None,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("10.00"),
                }
            ],
            user=self.user,
        )

        PurchaseOrderService.submit_order(order, self.user)

        order.refresh_from_db()
        self.assertEqual(order.status, "APPROVED")
        self.assertEqual(order.items.get().warehouse_id, self.warehouse.id)
        self.assertTrue(
            PurchaseApprovalLog.objects.filter(
                purchase_order=order,
                action="AUTO_APPROVE",
                approved_by=self.user,
            ).exists()
        )

    def test_sales_submit_auto_approves_and_skips_credit_control_when_disabled(self):
        order = SalesOrderService.create_order(
            self.customer,
            [
                {
                    "product": self.product,
                    "warehouse": None,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("20.00"),
                }
            ],
            self.user,
        )

        SalesOrderService.submit_order(order, self.user)

        order.refresh_from_db()
        self.assertEqual(order.status, "APPROVED")
        self.assertEqual(order.items.get().warehouse_id, self.warehouse.id)

    def test_sales_allocate_uses_default_warehouse_when_single_warehouse_mode(self):
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("5.000"),
            transaction_type="PURCHASE_IN",
            operator=self.user,
            remark="policy stock seed",
        )
        order = SalesOrderService.create_order(
            self.customer,
            [
                {
                    "product": self.product,
                    "warehouse": None,
                    "quantity": Decimal("1.000"),
                    "unit_price": Decimal("20.00"),
                }
            ],
            self.user,
        )
        SalesOrderService.submit_order(order, self.user)
        SalesOrderService.allocate_stock(order, self.user)

        order.refresh_from_db()
        self.assertEqual(order.status, "ALLOCATED")
        self.assertEqual(order.items.get().warehouse_id, self.warehouse.id)

    def test_inventory_policy_requires_explicit_warehouse_in_multi_warehouse_mode(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v2",
            config_json=build_config(
                inventory_multi_warehouse=True,
                purchase_approval=False,
                sales_approval=False,
                credit_control=False,
            ),
            created_by=self.user,
        )
        multi_tenant = Tenant.objects.create(code="multi-tenant", name="Multi Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=multi_tenant, user=self.user)
        TenantConfigSnapshot.objects.create(
            tenant=multi_tenant,
            blueprint_version=version,
            config_json=version.config_json,
        )

        policy = InventoryPolicy(build_runtime_config(multi_tenant))

        with self.assertRaisesMessage(ValueError, "请选择仓库"):
            policy.resolve_warehouse(None)

    def test_purchase_policy_requires_manual_approval_when_enabled(self):
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v3",
            config_json=build_config(
                inventory_multi_warehouse=False,
                purchase_approval=True,
                sales_approval=False,
                credit_control=False,
            ),
            created_by=self.user,
        )
        approval_tenant = Tenant.objects.create(code="approval-tenant", name="Approval Tenant", status="ACTIVE")
        TenantConfigSnapshot.objects.create(
            tenant=approval_tenant,
            blueprint_version=version,
            config_json=version.config_json,
        )

        policy = PurchasePolicy(build_runtime_config(approval_tenant))

        self.assertTrue(policy.approval_enabled())
        self.assertTrue(policy.partial_receipt_enabled())
        self.assertTrue(policy.purchase_return_enabled())
        self.assertEqual(policy.next_submit_status(), "PENDING_APPROVAL")

    def test_sales_submit_blocks_when_credit_control_enabled(self):
        credit_user = User.objects.create_user(username="credit_user", password="password")
        version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v4",
            config_json=build_config(
                inventory_multi_warehouse=False,
                purchase_approval=False,
                sales_approval=False,
                credit_control=True,
            ),
            created_by=self.user,
        )
        credit_tenant = Tenant.objects.create(code="credit-tenant", name="Credit Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=credit_tenant, user=credit_user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(
            tenant=credit_tenant,
            blueprint_version=version,
            config_json=version.config_json,
        )
        credit_customer = Customer.objects.create(
            customer_code="POLICY-CUS-002",
            customer_name="Credit Policy Customer",
            status="ACTIVE",
            credit_limit=Decimal("100.00"),
            current_balance=Decimal("90.00"),
            credit_control_mode="BLOCK",
            created_by=credit_user,
            owner=credit_user,
            dept=credit_user.dept,
        )

        order = SalesOrderService.create_order(
            credit_customer,
            [
                {
                    "product": self.product,
                    "warehouse": None,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("20.00"),
                }
            ],
            credit_user,
        )

        with self.assertRaisesMessage(ValueError, "超过信用额度"):
            SalesOrderService.submit_order(order, credit_user)

    def test_different_tenants_apply_different_purchase_and_sales_policies(self):
        version_auto = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v5",
            config_json=build_config(
                inventory_multi_warehouse=False,
                purchase_approval=False,
                sales_approval=False,
                credit_control=False,
            ),
            created_by=self.user,
        )
        version_manual = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version="v6",
            config_json=build_config(
                inventory_multi_warehouse=True,
                purchase_approval=True,
                sales_approval=True,
                credit_control=True,
            ),
            created_by=self.user,
        )
        tenant_auto = Tenant.objects.create(code="tenant-auto", name="Tenant Auto", status="ACTIVE")
        tenant_manual = Tenant.objects.create(code="tenant-manual", name="Tenant Manual", status="ACTIVE")
        TenantConfigSnapshot.objects.create(
            tenant=tenant_auto,
            blueprint_version=version_auto,
            config_json=version_auto.config_json,
        )
        TenantConfigSnapshot.objects.create(
            tenant=tenant_manual,
            blueprint_version=version_manual,
            config_json=version_manual.config_json,
        )

        auto_runtime = build_runtime_config(tenant_auto)
        manual_runtime = build_runtime_config(tenant_manual)

        self.assertEqual(PurchasePolicy(auto_runtime).next_submit_status(), "APPROVED")
        self.assertEqual(PurchasePolicy(manual_runtime).next_submit_status(), "PENDING_APPROVAL")
        self.assertFalse(SalesPolicy(auto_runtime).credit_control_enabled())
        self.assertTrue(SalesPolicy(manual_runtime).credit_control_enabled())
        self.assertFalse(InventoryPolicy(auto_runtime).batch_tracking_enabled())
        self.assertTrue(SalesPolicy(manual_runtime).outbound_auto_ar_enabled())
