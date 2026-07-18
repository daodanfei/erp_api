from decimal import Decimal
from datetime import date

from django.test import TestCase

from business_apps.inventory.models import Product, ProductCategory, Unit
from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem
from business_apps.purchase.services import PurchaseOrderService
from business_apps.supplier.models import Supplier
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant


class PurchaseStatisticsTenantIsolationTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            code="purchase-stats-tenant-a",
            name="Purchase Stats Tenant A",
            status="ACTIVE",
        )
        self.other_tenant = Tenant.objects.create(
            code="purchase-stats-tenant-b",
            name="Purchase Stats Tenant B",
            status="ACTIVE",
        )
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="purchase_stats_user",
            password="password",
            must_change_password=False,
        )
        self.other_user = ERPUser.objects.create_user(
            tenant=self.other_tenant,
            username="purchase_stats_other_user",
            password="password",
            must_change_password=False,
        )
        self.category = ProductCategory.objects.create(
            tenant=self.tenant,
            name="采购统计分类",
            status=True,
        )
        self.unit = Unit.objects.create(
            tenant=self.tenant,
            name="件",
            code="PURCHASE-STATS-UNIT-001",
            status=True,
        )
        self.other_category = ProductCategory.objects.create(
            tenant=self.other_tenant,
            name="采购统计分类B",
            status=True,
        )
        self.other_unit = Unit.objects.create(
            tenant=self.other_tenant,
            name="箱",
            code="PURCHASE-STATS-UNIT-002",
            status=True,
        )
        self.product = Product.objects.create(
            tenant=self.tenant,
            product_code="PURCHASE-STATS-PROD-A",
            name="Tenant A Product",
            category=self.category,
            unit=self.unit,
            status="ACTIVE",
            created_by=self.user,
        )
        self.other_product = Product.objects.create(
            tenant=self.other_tenant,
            product_code="PURCHASE-STATS-PROD-B",
            name="Tenant B Product",
            category=self.other_category,
            unit=self.other_unit,
            status="ACTIVE",
            created_by=self.other_user,
        )
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code="SUP-STATS-A",
            supplier_name="Tenant A Supplier",
            status="ACTIVE",
        )
        self.other_supplier = Supplier.objects.create(
            tenant=self.other_tenant,
            supplier_code="SUP-STATS-B",
            supplier_name="Tenant B Supplier",
            status="ACTIVE",
        )
        order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO-STATS-A-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            status=PurchaseOrder.STATUS_APPROVED,
            total_quantity=Decimal("2.000"),
            total_amount=Decimal("100.00"),
            created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            tenant=self.tenant,
            purchase_order=order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("2.000"),
            unit_price=Decimal("50.00"),
            amount=Decimal("100.00"),
        )

        other_order = PurchaseOrder.objects.create(
            tenant=self.other_tenant,
            purchase_order_no="PO-STATS-B-001",
            supplier=self.other_supplier,
            supplier_name_snapshot=self.other_supplier.supplier_name,
            status=PurchaseOrder.STATUS_APPROVED,
            total_quantity=Decimal("3.000"),
            total_amount=Decimal("999.00"),
            created_by=self.other_user,
        )
        PurchaseOrderItem.objects.create(
            tenant=self.other_tenant,
            purchase_order=other_order,
            product=self.other_product,
            product_name_snapshot=self.other_product.name,
            product_code_snapshot=self.other_product.product_code,
            quantity=Decimal("3.000"),
            unit_price=Decimal("333.00"),
            amount=Decimal("999.00"),
        )

    def test_get_statistics_filters_supplier_and_product_rankings_by_erp_tenant(self):
        stats = PurchaseOrderService.get_statistics(self.user)

        supplier_names = [item["supplier_name_snapshot"] for item in stats["by_supplier"]]
        product_names = [item["product_name_snapshot"] for item in stats["by_product"]]

        self.assertEqual(supplier_names, ["Tenant A Supplier"])
        self.assertEqual(product_names, ["Tenant A Product"])
        self.assertEqual(stats["total_orders"], 1)
        self.assertEqual(stats["total_amount"], Decimal("100.00"))

    def test_get_statistics_applies_date_range_to_all_aggregations(self):
        order = PurchaseOrder.objects.get(purchase_order_no="PO-STATS-A-001")
        PurchaseOrder.objects.filter(pk=order.pk).update(order_date=date(2026, 1, 15))

        included = PurchaseOrderService.get_statistics(
            self.user,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        excluded = PurchaseOrderService.get_statistics(
            self.user,
            start_date="2026-02-01",
            end_date="2026-02-28",
        )

        self.assertEqual(included["total_orders"], 1)
        self.assertEqual(included["by_status"], {PurchaseOrder.STATUS_APPROVED: 1})
        self.assertEqual([item["product_name_snapshot"] for item in included["by_product"]], ["Tenant A Product"])
        self.assertEqual(excluded["total_orders"], 0)
        self.assertEqual(excluded["total_amount"], Decimal("0"))
        self.assertEqual(excluded["by_status"], {})
        self.assertEqual(excluded["by_supplier"], [])
        self.assertEqual(excluded["by_product"], [])
        self.assertEqual(excluded["by_month"], [])
