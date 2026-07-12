from decimal import Decimal

from django.test import TestCase

from business_apps.crm.models import Customer
from business_apps.sales.models import SalesOrder
from business_apps.sales.services import SalesOrderService
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant


class SalesStatisticsTenantIsolationTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            code="sales-stats-tenant-a",
            name="Sales Stats Tenant A",
            status="ACTIVE",
        )
        self.other_tenant = Tenant.objects.create(
            code="sales-stats-tenant-b",
            name="Sales Stats Tenant B",
            status="ACTIVE",
        )
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="sales_stats_user",
            password="password",
            must_change_password=False,
        )
        self.other_user = ERPUser.objects.create_user(
            tenant=self.other_tenant,
            username="sales_stats_other_user",
            password="password",
            must_change_password=False,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="CUS-STATS-A",
            customer_name="Tenant A Customer",
            status="ACTIVE",
        )
        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant,
            customer_code="CUS-STATS-B",
            customer_name="Tenant B Customer",
            status="ACTIVE",
        )
        SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-STATS-A-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_APPROVED,
            total_quantity=Decimal("2.000"),
            total_amount=Decimal("100.00"),
            created_by=self.user,
        )
        SalesOrder.objects.create(
            tenant=self.other_tenant,
            order_no="SO-STATS-B-001",
            customer=self.other_customer,
            customer_name_snapshot=self.other_customer.customer_name,
            status=SalesOrder.STATUS_APPROVED,
            total_quantity=Decimal("3.000"),
            total_amount=Decimal("999.00"),
            created_by=self.other_user,
        )

    def test_get_statistics_filters_customer_ranking_by_erp_tenant(self):
        stats = SalesOrderService.get_statistics(self.user)

        customer_names = [item["customer__customer_name"] for item in stats["by_customer"]]

        self.assertEqual(customer_names, ["Tenant A Customer"])
        self.assertEqual(stats["today"]["count"], 1)
        self.assertEqual(stats["month"]["count"], 1)
