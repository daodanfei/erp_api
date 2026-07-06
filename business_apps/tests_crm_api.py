from django.test import TestCase
from rest_framework.test import APIClient

from business_apps.crm.models import Customer
from business_apps.ar_receivable.models import Receivable
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.platform.services import CodeRuleService
from business_apps.sales.models import SalesOrder, SalesOrderItem
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.authentication.models import Permission, Role, User
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser


def build_crm_config(*, code_auto_generate=True, follow_record_enabled=True, transfer_enabled=True):
    return {
        "basic": {"name": "crm_policy", "industry": "trade", "mode": "saas"},
        "enabled_modules": ["crm"],
        "module_configs": {
            "crm": {
                "features": {
                    "customer_approval": False,
                    "customer_code_auto_generate": code_auto_generate,
                    "credit_limit_enabled": True,
                    "follow_record_enabled": follow_record_enabled,
                    "customer_transfer_enabled": transfer_enabled,
                    "customer_attachment_enabled": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            }
        },
    }


class CustomerApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="customer_admin",
            password="pass",
            email="customer_admin@example.com",
        )
        cls.role = Role.objects.create(name="客户管理员", code="customer_admin_role")
        cls.role.permissions.add(
            Permission.objects.create(name="查看客户", code="crm:customer:view", type="BUTTON"),
            Permission.objects.create(name="创建客户", code="crm:customer:create", type="BUTTON"),
            Permission.objects.create(name="更新客户", code="crm:customer:update", type="BUTTON"),
            Permission.objects.create(name="销售报表", code="reports:sales:view", type="BUTTON"),
        )
        cls.user.roles.add(cls.role)
        CodeRuleService.init_default_rules(created_by=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _apply_runtime_config(self, config):
        blueprint = SystemBlueprint.objects.create(key=f"crm-bp-{Tenant.objects.count()}", name="CRM Policy", created_by=self.user)
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=self.user,
        )
        tenant = Tenant.objects.create(code=f"crm-tenant-{Tenant.objects.count()}", name="CRM Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=self.user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(tenant=tenant, blueprint_version=version, config_json=config)
        return tenant

    def test_customer_can_be_updated_with_its_own_unique_fields(self):
        create_response = self.client.post(
            "/api/crm/customers/",
            {
                "customer_name": "上海测试客户",
                "short_name": "测试客户",
                "customer_type": "COMPANY",
                "customer_level": "B",
                "status": "ACTIVE",
                "phone": "13900139000",
                "email": "customer@example.com",
                "payment_term": "NET_30",
                "default_payment_method": "BANK_TRANSFER",
                "credit_control_mode": "BLOCK",
                "credit_limit": "1000.00",
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        customer_id = create_response.data["id"]

        update_response = self.client.put(
            f"/api/crm/customers/{customer_id}/",
            {
                "customer_name": "上海测试客户",
                "short_name": "测试客户-已编辑",
                "customer_type": "COMPANY",
                "customer_level": "A",
                "status": "INACTIVE",
                "phone": "13900139000",
                "email": "customer@example.com",
                "payment_term": "NET_60",
                "default_payment_method": "ALIPAY",
                "credit_control_mode": "WARN",
                "credit_limit": "2000.00",
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data["short_name"], "测试客户-已编辑")
        self.assertEqual(update_response.data["customer_level"], "A")
        self.assertEqual(update_response.data["status"], "INACTIVE")
        self.assertEqual(update_response.data["payment_term"], "NET_60")
        self.assertEqual(update_response.data["default_payment_method"], "ALIPAY")
        self.assertEqual(update_response.data["credit_control_mode"], "WARN")

    def test_customer_credit_overview_returns_credit_fields(self):
        customer = Customer.objects.create(
            customer_code="CUS-CREDIT-001",
            customer_name="信用客户",
            status="ACTIVE",
            payment_term="NET_60",
            default_payment_method="WECHAT",
            credit_control_mode="BLOCK",
            credit_limit="1000.00",
            current_balance="800.00",
            created_by=self.user,
        )
        Receivable.objects.create(
            receivable_no="AR-CREDIT-001",
            customer=customer,
            amount="500.00",
            written_off_amount="100.00",
            due_date="2026-06-01",
            status="PARTIAL_PAID",
        )

        response = self.client.get(f"/api/crm/customers/{customer.id}/credit-overview/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["payment_term"], "NET_60")
        self.assertEqual(data["default_payment_method"], "WECHAT")
        self.assertEqual(data["credit_control_mode"], "BLOCK")
        self.assertEqual(data["credit_limit"], "1000.00")
        self.assertEqual(data["current_balance"], "800.00")
        self.assertEqual(data["available_credit"], "200.00")
        self.assertEqual(data["overdue_amount"], "400.00")

    def test_sales_statistics_returns_customer_aggregates(self):
        customer = Customer.objects.create(
            customer_code="CUS-STAT-001",
            customer_name="统计客户",
            status="ACTIVE",
            credit_limit=100000,
            created_by=self.user,
        )
        other_customer = Customer.objects.create(
            customer_code="CUS-STAT-002",
            customer_name="其他客户",
            status="ACTIVE",
            credit_limit=100000,
            created_by=self.user,
        )
        category = ProductCategory.objects.create(name="客户统计分类")
        unit = Unit.objects.create(name="件", code="UNIT-CRM-STAT-001")
        warehouse = Warehouse.objects.create(warehouse_code="WH-CRM-STAT-001", warehouse_name="客户统计仓")
        product = Product.objects.create(
            product_code="PRO-CRM-STAT-001",
            name="客户统计商品",
            category=category,
            unit=unit,
            status="ACTIVE",
            created_by=self.user,
        )

        order1 = SalesOrder.objects.create(
            order_no="SO-STAT-001",
            customer=customer,
            customer_name_snapshot=customer.customer_name,
            status="SHIPPED",
            total_quantity="10.000",
            total_amount="1000.00",
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            order=order1,
            product=product,
            product_name_snapshot=product.name,
            warehouse=warehouse,
            quantity="10.000",
            shipped_quantity="10.000",
            unit_price="100.00",
            amount="1000.00",
        )

        order2 = SalesOrder.objects.create(
            order_no="SO-STAT-002",
            customer=customer,
            customer_name_snapshot=customer.customer_name,
            status="APPROVED",
            total_quantity="5.000",
            total_amount="500.00",
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            order=order2,
            product=product,
            product_name_snapshot=product.name,
            warehouse=warehouse,
            quantity="5.000",
            shipped_quantity="0.000",
            unit_price="100.00",
            amount="500.00",
        )

        SalesOrder.objects.create(
            order_no="SO-STAT-003",
            customer=other_customer,
            customer_name_snapshot=other_customer.customer_name,
            status="SHIPPED",
            total_quantity="99.000",
            total_amount="9900.00",
            created_by=self.user,
        )

        response = self.client.get(f"/api/crm/customers/{customer.id}/sales-statistics/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total_orders"], 2)
        self.assertEqual(data["summary"]["completed_orders"], 1)
        self.assertEqual(data["summary"]["pending_orders"], 1)
        self.assertEqual(float(data["summary"]["total_amount"]), 1500.0)
        self.assertEqual(float(data["summary"]["total_quantity"]), 15.0)
        self.assertEqual(data["summary"]["completion_rate"], 50.0)
        self.assertEqual(data["by_status"]["SHIPPED"], 1)
        self.assertEqual(data["by_status"]["APPROVED"], 1)
        self.assertEqual(len(data["recent_orders"]), 2)
        self.assertEqual(data["top_products"][0]["product_name_snapshot"], "客户统计商品")

    def test_sales_product_ranking_uses_sales_order_item_order_relation(self):
        customer = Customer.objects.create(
            customer_code="CUS-RPT-001",
            customer_name="报表客户",
            status="ACTIVE",
            credit_limit=100000,
            created_by=self.user,
        )
        category = ProductCategory.objects.create(name="报表分类")
        unit = Unit.objects.create(name="件", code="UNIT-RPT-001")
        warehouse = Warehouse.objects.create(warehouse_code="WH-RPT-001", warehouse_name="报表仓")
        product = Product.objects.create(
            product_code="PRO-RPT-001",
            name="报表商品",
            category=category,
            unit=unit,
            status="ACTIVE",
            created_by=self.user,
        )

        order = SalesOrder.objects.create(
            order_no="SO-RPT-001",
            customer=customer,
            customer_name_snapshot=customer.customer_name,
            status="APPROVED",
            total_quantity="3.000",
            total_amount="300.00",
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            warehouse=warehouse,
            quantity="3.000",
            shipped_quantity="0.000",
            unit_price="100.00",
            amount="300.00",
        )

        response = self.client.get("/api/reports/sales/products?period=month")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "报表商品")
        self.assertEqual(data[0]["code"], "PRO-RPT-001")

    def test_customer_create_uses_manual_code_when_auto_generate_disabled(self):
        self._apply_runtime_config(build_crm_config(code_auto_generate=False))

        response = self.client.post(
            "/api/crm/customers/",
            {
                "customer_code": "MANUAL-CUS-001",
                "customer_name": "手工编码客户",
                "status": "ACTIVE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["customer_code"], "MANUAL-CUS-001")

    def test_customer_follow_record_is_blocked_when_policy_disabled(self):
        self._apply_runtime_config(build_crm_config(follow_record_enabled=False))
        customer = Customer.objects.create(
            customer_code="CUS-POL-001",
            customer_name="策略客户",
            status="ACTIVE",
            created_by=self.user,
        )

        response = self.client.post(
            "/api/crm/follow-records/",
            {
                "customer": customer.id,
                "follow_type": "PHONE",
                "content": "测试跟进",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
