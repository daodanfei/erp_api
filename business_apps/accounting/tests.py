from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from business_apps.accounting.models import AccountSubject, AccountingPeriod, BusinessPostingLog, Voucher
from business_apps.accounting.services import PeriodService, PostingService, SubjectInitService
from business_apps.ap_payable.models import APPayment
from business_apps.ar_receivable.models import Receipt
from business_apps.crm.models import Customer
from business_apps.finance.models import CashAccount
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.platform.models import CodeRule
from business_apps.purchase.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from business_apps.sales.models import SalesOrder, SalesOrderItem
from business_apps.supplier.models import Supplier
from business_apps.supply_chain.models import OutboundOrder, OutboundOrderItem
from core_apps.authentication.models import Permission, Role, User


class AccountingPostingServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="acc_user", password="password")
        SubjectInitService.init_subjects(created_by=self.user)
        for rule_code, prefix in [
            ("ACCOUNTING_VOUCHER", "V"),
            ("PURCHASE_ORDER", "PO"),
            ("PURCHASE_RECEIPT", "PR"),
            ("OUTBOUND_ORDER", "OB"),
            ("AR_RECEIPT", "RC"),
            ("AP_PAYMENT", "PAY"),
        ]:
            CodeRule.objects.get_or_create(
                rule_code=rule_code,
                defaults={
                    "rule_name": rule_code,
                    "prefix": prefix,
                    "date_format": "%Y%m%d",
                    "sequence_length": 4,
                    "reset_type": "DAY",
                    "status": "ACTIVE",
                },
            )

        self.category = ProductCategory.objects.create(name="测试分类")
        self.unit = Unit.objects.create(name="件", code="PCS-ACT")
        self.product = Product.objects.create(
            product_code="PRO-ACT-001",
            name="测试商品",
            category=self.category,
            unit=self.unit,
            cost_price=Decimal("80.00"),
            sale_price=Decimal("120.00"),
            status="ACTIVE",
        )
        self.warehouse = Warehouse.objects.create(warehouse_code="WH-ACT-001", warehouse_name="总仓")
        self.customer = Customer.objects.create(
            customer_code="CUS-ACT-001",
            customer_name="测试客户",
            status="ACTIVE",
            payment_term="NET_30",
        )
        self.supplier = Supplier.objects.create(
            supplier_code="SUP-ACT-001",
            supplier_name="测试供应商",
            status="ACTIVE",
            payment_term="NET_30",
        )
        self.cash_account = CashAccount.objects.create(
            name="测试银行",
            type="BANK",
            account_type="BANK",
            current_balance=Decimal("1000.00"),
        )

    def _build_purchase_receipt(self):
        order = PurchaseOrder.objects.create(
            purchase_order_no="PO-ACT-001",
            supplier=self.supplier,
            status="APPROVED",
            created_by=self.user,
        )
        po_item = PurchaseOrderItem.objects.create(
            purchase_order=order,
            product=self.product,
            quantity=Decimal("10.000"),
            unit_price=Decimal("80.00"),
            amount=Decimal("800.00"),
        )
        receipt = PurchaseReceipt.objects.create(
            receipt_no="PR-ACT-001",
            purchase_order=order,
            warehouse=self.warehouse,
            status="COMPLETED",
            received_at=timezone.now(),
            created_by=self.user,
            executed_by=self.user,
        )
        PurchaseReceiptItem.objects.create(
            receipt=receipt,
            purchase_order_item=po_item,
            product=self.product,
            received_quantity=Decimal("10.000"),
        )
        return receipt

    def _build_outbound_order(self):
        order = SalesOrder.objects.create(
            order_no="SO-ACT-001",
            customer=self.customer,
            status="SHIPPED",
            total_amount=Decimal("240.00"),
            created_by=self.user,
        )
        sales_item = SalesOrderItem.objects.create(
            order=order,
            product=self.product,
            warehouse=self.warehouse,
            quantity=Decimal("2.000"),
            unit_price=Decimal("120.00"),
            amount=Decimal("240.00"),
        )
        outbound = OutboundOrder.objects.create(
            outbound_no="OB-ACT-001",
            sales_order=order,
            warehouse=self.warehouse,
            status="COMPLETED",
            completed_at=timezone.now(),
            created_by=self.user,
        )
        OutboundOrderItem.objects.create(
            outbound_order=outbound,
            sales_order_item=sales_item,
            product=self.product,
            quantity=Decimal("2.000"),
            unit_price=Decimal("120.00"),
            amount=Decimal("240.00"),
        )
        return outbound

    def test_purchase_receipt_posting_generates_balanced_voucher(self):
        receipt = self._build_purchase_receipt()

        voucher = PostingService.post_purchase_receipt(receipt, self.user)

        self.assertEqual(voucher.source_type, "PURCHASE_RECEIPT")
        self.assertEqual(voucher.source_id, receipt.id)
        self.assertEqual(voucher.total_debit, Decimal("800.00"))
        self.assertEqual(voucher.total_credit, Decimal("800.00"))
        self.assertEqual(voucher.lines.count(), 2)
        self.assertSetEqual(set(voucher.lines.values_list("subject__code", flat=True)), {"1405", "2202"})

    def test_duplicate_posting_is_idempotent(self):
        outbound = self._build_outbound_order()

        first_voucher = PostingService.post_sales_outbound(outbound, self.user)
        second_voucher = PostingService.post_sales_outbound(outbound, self.user)

        self.assertEqual(first_voucher.id, second_voucher.id)
        self.assertEqual(
            BusinessPostingLog.objects.filter(
                event_type=PostingService.EVENT_SALES_OUTBOUND,
                business_type="OUTBOUND_ORDER",
                business_id=outbound.id,
            ).count(),
            1,
        )
        self.assertEqual(Voucher.objects.filter(source_type="OUTBOUND_ORDER", source_id=outbound.id).count(), 1)

    def test_closed_period_blocks_posting(self):
        receipt = Receipt.objects.create(
            receipt_no="RC-ACT-001",
            customer=self.customer,
            amount=Decimal("300.00"),
            unwritten_amount=Decimal("300.00"),
            receipt_date=timezone.localdate(),
            payment_method="BANK_TRANSFER",
            cash_account=self.cash_account,
            status="UNWRITTEN",
            executed_at=timezone.now(),
            created_by=self.user,
        )
        period = PeriodService.get_or_create_period(receipt.receipt_date)
        PeriodService.close_period(period, self.user)

        with self.assertRaisesMessage(ValueError, "已关闭"):
            PostingService.post_receipt_execution(receipt, self.user)

    def test_business_document_maps_back_to_voucher(self):
        payment = APPayment.objects.create(
            payment_no="PAY-ACT-001",
            supplier=self.supplier,
            payment_date=timezone.localdate(),
            payment_method="BANK_TRANSFER",
            cash_account=self.cash_account,
            payment_amount=Decimal("500.00"),
            allocated_amount=Decimal("0.00"),
            status="APPROVED",
            executed_at=timezone.now(),
            created_by=self.user,
        )

        voucher = PostingService.post_payment_execution(payment, self.user)
        log = BusinessPostingLog.objects.get(
            event_type=PostingService.EVENT_PAYMENT_EXECUTED,
            business_type="AP_PAYMENT",
            business_id=payment.id,
        )

        self.assertEqual(log.voucher_id, voucher.id)
        self.assertEqual(voucher.source_document_no, payment.payment_no)
        self.assertEqual(voucher.lines.filter(business_type="AP_PAYMENT", business_id=payment.id).count(), 2)
        self.assertEqual(str(voucher.period), f"{payment.payment_date.year}-{payment.payment_date.month:02d}")


class AccountingPermissionApiTest(APITestCase):
    def setUp(self):
        self.subject_view_permission = Permission.objects.create(name="查看会计科目", code="accounting:subject:view", type="BUTTON")
        self.subject_update_permission = Permission.objects.create(name="维护会计科目", code="accounting:subject:update", type="BUTTON")
        self.period_update_permission = Permission.objects.create(name="维护会计期间", code="accounting:period:update", type="BUTTON")
        self.voucher_view_permission = Permission.objects.create(name="查看会计凭证", code="accounting:voucher:view", type="BUTTON")

        self.role = Role.objects.create(name="财务会计", code="finance_accountant", data_scope="ALL")
        self.user = User.objects.create_user(username="finance_accountant", password="password")
        self.user.roles.add(self.role)
        self.no_permission_user = User.objects.create_user(username="accounting_guest", password="password")

        self.creator = User.objects.create_user(username="accounting_seed_user", password="password")
        SubjectInitService.init_subjects(created_by=self.creator)
        self.subject = AccountSubject.objects.order_by("code").first()
        self.period = PeriodService.get_or_create_period(timezone.localdate())
        self.voucher = Voucher.objects.create(
            voucher_no="V-API-001",
            voucher_date=timezone.localdate(),
            period=self.period,
            voucher_type="MANUAL",
            abstract="权限测试凭证",
            source_type="MANUAL",
            source_id=1,
            source_document_no="MANUAL-001",
            total_debit=Decimal("100.00"),
            total_credit=Decimal("100.00"),
            posted_by=self.creator,
        )

    def test_accounting_finance_role_permissions_are_granular(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.get("/api/accounting/subjects/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get("/api/accounting/vouchers/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.patch(
                f"/api/accounting/periods/{self.period.id}/",
                {"status": AccountingPeriod.STATUS_CLOSED},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.role.permissions.add(self.subject_view_permission, self.voucher_view_permission)
        self.assertEqual(self.client.get("/api/accounting/subjects/").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get("/api/accounting/vouchers/").status_code, status.HTTP_200_OK)

        self.role.permissions.add(self.period_update_permission)
        period_update = self.client.patch(
            f"/api/accounting/periods/{self.period.id}/",
            {"status": AccountingPeriod.STATUS_CLOSED},
            format="json",
        )
        self.assertEqual(period_update.status_code, status.HTTP_200_OK)

        subject_update = self.client.patch(
            f"/api/accounting/subjects/{self.subject.id}/",
            {"remark": "still forbidden"},
            format="json",
        )
        self.assertEqual(subject_update.status_code, status.HTTP_403_FORBIDDEN)

        self.role.permissions.add(self.subject_update_permission)
        subject_update = self.client.patch(
            f"/api/accounting/subjects/{self.subject.id}/",
            {"remark": "allowed update"},
            format="json",
        )
        self.assertEqual(subject_update.status_code, status.HTTP_200_OK)

    def test_user_without_accounting_permissions_cannot_view_vouchers(self):
        self.client.force_authenticate(self.no_permission_user)

        response = self.client.get("/api/accounting/vouchers/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
