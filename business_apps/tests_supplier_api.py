from django.test import TestCase
from rest_framework.test import APIClient

from business_apps.platform.services import CodeRuleService
from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem
from business_apps.supplier.models import Supplier, SupplierEvaluation
from business_apps.inventory.models import ProductCategory, Product, Unit, Warehouse
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.authentication.models import Permission, Role, User
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser


def build_supplier_config(*, code_auto_generate=True, owner_transfer_enabled=True):
    return {
        "basic": {"name": "supplier_policy", "industry": "trade", "mode": "saas"},
        "enabled_modules": ["supplier"],
        "module_configs": {
            "supplier": {
                "features": {
                    "supplier_approval": False,
                    "supplier_code_auto_generate": code_auto_generate,
                    "supplier_credit_management": False,
                    "supplier_rating_enabled": True,
                    "supplier_attachment_enabled": True,
                    "supplier_owner_transfer_enabled": owner_transfer_enabled,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            }
        },
    }


class SupplierApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="supplier_admin",
            password="pass",
            email="supplier_admin@example.com",
        )
        cls.role = Role.objects.create(name="供应商管理员", code="supplier_admin_role")
        cls.role.permissions.add(
            Permission.objects.create(name="查看供应商", code="supplier:supplier:view", type="BUTTON"),
            Permission.objects.create(name="创建供应商", code="supplier:supplier:create", type="BUTTON"),
            Permission.objects.create(name="更新供应商", code="supplier:supplier:update", type="BUTTON"),
            Permission.objects.create(name="转移供应商", code="supplier:supplier:transfer", type="BUTTON"),
            Permission.objects.create(name="供应商报表", code="reports:supplier:view", type="BUTTON"),
        )
        cls.user.roles.add(cls.role)
        CodeRuleService.init_default_rules(created_by=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _apply_runtime_config(self, config):
        blueprint = SystemBlueprint.objects.create(key=f"supplier-bp-{Tenant.objects.count()}", name="Supplier Policy", created_by=self.user)
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=self.user,
        )
        tenant = Tenant.objects.create(code=f"supplier-tenant-{Tenant.objects.count()}", name="Supplier Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=self.user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(tenant=tenant, blueprint_version=version, config_json=config)
        return tenant

    def test_purchase_statistics_returns_supplier_aggregates(self):
        supplier = Supplier.objects.create(
            supplier_code="SUP-STAT-001",
            supplier_name="统计供应商",
            status="ACTIVE",
            created_by=self.user,
        )
        other_supplier = Supplier.objects.create(
            supplier_code="SUP-STAT-002",
            supplier_name="其他供应商",
            status="ACTIVE",
            created_by=self.user,
        )
        category = ProductCategory.objects.create(name="统计分类")
        unit = Unit.objects.create(name="件", code="UNIT-STAT-001")
        warehouse = Warehouse.objects.create(warehouse_code="WH-STAT-001", warehouse_name="统计仓")
        product = Product.objects.create(
            product_code="PRO-STAT-001",
            name="统计商品",
            category=category,
            unit=unit,
            status="ACTIVE",
            created_by=self.user,
        )

        order1 = PurchaseOrder.objects.create(
            purchase_order_no="PO-STAT-001",
            supplier=supplier,
            supplier_name_snapshot=supplier.supplier_name,
            supplier_code_snapshot=supplier.supplier_code,
            status="RECEIVED",
            total_quantity="10.000",
            total_amount="1000.00",
            created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            purchase_order=order1,
            product=product,
            product_name_snapshot=product.name,
            product_code_snapshot=product.product_code,
            warehouse=warehouse,
            quantity="10.000",
            received_quantity="10.000",
            unit_price="100.00",
            amount="1000.00",
        )

        order2 = PurchaseOrder.objects.create(
            purchase_order_no="PO-STAT-002",
            supplier=supplier,
            supplier_name_snapshot=supplier.supplier_name,
            supplier_code_snapshot=supplier.supplier_code,
            status="APPROVED",
            total_quantity="5.000",
            total_amount="500.00",
            created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            purchase_order=order2,
            product=product,
            product_name_snapshot=product.name,
            product_code_snapshot=product.product_code,
            warehouse=warehouse,
            quantity="5.000",
            received_quantity="0.000",
            unit_price="100.00",
            amount="500.00",
        )

        PurchaseOrder.objects.create(
            purchase_order_no="PO-STAT-003",
            supplier=other_supplier,
            supplier_name_snapshot=other_supplier.supplier_name,
            supplier_code_snapshot=other_supplier.supplier_code,
            status="RECEIVED",
            total_quantity="99.000",
            total_amount="9900.00",
            created_by=self.user,
        )

        response = self.client.get(f"/api/supplier/suppliers/{supplier.id}/purchase-statistics/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total_orders"], 2)
        self.assertEqual(data["summary"]["completed_orders"], 1)
        self.assertEqual(data["summary"]["pending_orders"], 1)
        self.assertEqual(float(data["summary"]["total_amount"]), 1500.0)
        self.assertEqual(float(data["summary"]["total_quantity"]), 15.0)
        self.assertEqual(data["summary"]["completion_rate"], 50.0)
        self.assertEqual(data["by_status"]["RECEIVED"], 1)
        self.assertEqual(data["by_status"]["APPROVED"], 1)
        self.assertEqual(len(data["recent_orders"]), 2)
        self.assertEqual(data["top_products"][0]["product_code_snapshot"], "PRO-STAT-001")

    def test_supplier_can_be_updated_with_its_own_unique_fields(self):
        create_response = self.client.post(
            "/api/supplier/suppliers/",
            {
                "supplier_name": "上海测试供应商",
                "short_name": "测试供应商",
                "supplier_type": "MANUFACTURER",
                "supplier_level": "B",
                "status": "ACTIVE",
                "tax_number": "91310000TEST0001",
                "contact_phone": "13800138000",
                "email": "supplier@example.com",
                "payment_term": "NET_30",
                "default_payment_method": "BANK_TRANSFER",
                "settlement_cycle": "PER_RECEIPT",
                "currency": "CNY",
                "tax_rate": "0.13",
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        supplier_id = create_response.data["id"]

        update_response = self.client.put(
            f"/api/supplier/suppliers/{supplier_id}/",
            {
                "supplier_name": "上海测试供应商",
                "short_name": "测试供应商-已编辑",
                "supplier_type": "MANUFACTURER",
                "supplier_level": "A",
                "status": "ACTIVE",
                "tax_number": "91310000TEST0001",
                "contact_phone": "13800138000",
                "email": "supplier@example.com",
                "payment_term": "NET_60",
                "default_payment_method": "ALIPAY",
                "settlement_cycle": "MONTHLY",
                "currency": "CNY",
                "tax_rate": "0.13",
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data["short_name"], "测试供应商-已编辑")
        self.assertEqual(update_response.data["supplier_level"], "A")
        self.assertEqual(update_response.data["payment_term"], "NET_60")
        self.assertEqual(update_response.data["default_payment_method"], "ALIPAY")
        self.assertEqual(update_response.data["settlement_cycle"], "MONTHLY")

        supplier = Supplier.objects.get(id=supplier_id)
        self.assertEqual(supplier.short_name, "测试供应商-已编辑")
        self.assertEqual(supplier.supplier_level, "A")

    def test_supplier_detail_returns_default_settlement_rules(self):
        supplier = Supplier.objects.create(
            supplier_code="SUP-SETTLE-001",
            supplier_name="结算供应商",
            status="ACTIVE",
            payment_term="NET_90",
            default_payment_method="CHECK",
            settlement_cycle="MONTHLY",
            created_by=self.user,
        )

        response = self.client.get(f"/api/supplier/suppliers/{supplier.id}/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["payment_term"], "NET_90")
        self.assertEqual(data["default_payment_method"], "CHECK")
        self.assertEqual(data["settlement_cycle"], "MONTHLY")

    def test_supplier_evaluation_ranking_returns_average_scores(self):
        supplier = Supplier.objects.create(
            supplier_code="SUP-EVAL-001",
            supplier_name="评分供应商",
            status="ACTIVE",
            created_by=self.user,
        )
        SupplierEvaluation.objects.create(
            supplier=supplier,
            quality_score=5,
            delivery_score=4,
            service_score=3,
            price_score=2,
            evaluated_by=self.user,
        )

        response = self.client.get("/api/reports/suppliers/evaluation")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]["supplier_name"], "评分供应商")
        self.assertEqual(data[0]["score"], "3.5")

    def test_supplier_create_uses_manual_code_when_auto_generate_disabled(self):
        self._apply_runtime_config(build_supplier_config(code_auto_generate=False))

        response = self.client.post(
            "/api/supplier/suppliers/",
            {
                "supplier_code": "MANUAL-SUP-001",
                "supplier_name": "手工编码供应商",
                "status": "ACTIVE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["supplier_code"], "MANUAL-SUP-001")

    def test_supplier_transfer_is_blocked_when_policy_disabled(self):
        self._apply_runtime_config(build_supplier_config(owner_transfer_enabled=False))
        target_user = User.objects.create_user(username="supplier_target", password="pass")
        supplier = Supplier.objects.create(
            supplier_code="SUP-POL-001",
            supplier_name="策略供应商",
            status="ACTIVE",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/supplier/suppliers/{supplier.id}/transfer/",
            {"new_owner_id": target_user.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        supplier.refresh_from_db()
        self.assertIsNone(supplier.owner_id)
