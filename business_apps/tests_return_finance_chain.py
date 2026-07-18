from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from business_apps.accounting.models import AccountSubject, AccountingPeriod, BusinessPostingLog, Voucher
from business_apps.accounting.services import PeriodService, SubjectInitService
from business_apps.ap_payable.models import APAccount, SupplierCreditNote, SupplierRefund
from business_apps.ap_payable.services import APService
from business_apps.ar_receivable.models import CustomerRefund, Receipt, Receivable, WriteOff
from business_apps.ar_receivable.serializers import CustomerRefundSerializer, ReceiptSerializer
from business_apps.ar_receivable.services import ARService
from business_apps.crm.models import Customer
from business_apps.finance.models import CashAccount
from business_apps.inventory.models import Inventory, Product, ProductCategory, Unit, Warehouse
from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem
from business_apps.supplier.models import Supplier
from business_apps.supply_chain.models import (
    PurchaseReturnOrder,
    PurchaseReturnOrderItem,
    SalesReturnOrder,
    SalesReturnOrderItem,
)
from business_apps.supply_chain.services import PurchaseReturnService, SalesReturnService
from business_apps.sales.models import SalesOrder, SalesOrderItem
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant


def build_code_rule_generator():
    counters = defaultdict(int)

    def _generate(rule_name):
        counters[rule_name] += 1
        return f"{rule_name}-{counters[rule_name]:04d}"

    return _generate


class ReturnFinanceChainTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="return-finance-tenant", name="Return Finance Tenant", status="ACTIVE")
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="return_finance_user",
            password="password",
            must_change_password=False,
        )
        self.approver = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="return_finance_approver",
            password="password",
            must_change_password=False,
        )
        self.category = ProductCategory.objects.create(tenant=self.tenant, name="退货分类", status=True)
        self.unit = Unit.objects.create(tenant=self.tenant, name="件", code="RETURN-UNIT-001", status=True)
        self.product = Product.objects.create(
            tenant=self.tenant,
            product_code="RETURN-PROD-001",
            name="退货商品",
            category=self.category,
            unit=self.unit,
            cost_price=Decimal("8.00"),
            sale_price=Decimal("10.00"),
            status="ACTIVE",
            created_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(
            tenant=self.tenant,
            warehouse_code="RETURN-WH-001",
            warehouse_name="退货仓库",
            status=True,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="RETURN-CUS-001",
            customer_name="退货客户",
            status="ACTIVE",
            credit_control_mode="BLOCK",
        )
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code="RETURN-SUP-001",
            supplier_name="退货供应商",
            status="ACTIVE",
        )
        SubjectInitService.init_subjects(created_by=self.user)
        self.api_client = APIClient()
        self.api_client.force_authenticate(self.user)

    def _supply_chain_policy(self):
        return SimpleNamespace(
            sales_return_enabled=lambda: True,
            purchase_return_enabled=lambda: True,
            return_approval_enabled=lambda: False,
        )

    def _supply_chain_policy_with_return_approval(self):
        return SimpleNamespace(
            sales_return_enabled=lambda: True,
            purchase_return_enabled=lambda: True,
            return_approval_enabled=lambda: True,
        )

    def _inventory_policy(self):
        return SimpleNamespace(resolve_warehouse=lambda warehouse: warehouse)

    def _accounting_policy(self):
        return SimpleNamespace(
            voucher_auto_posting_enabled=lambda: True,
            inventory_posting_enabled=lambda: True,
            ar_ap_posting_enabled=lambda: True,
            period_close_enabled=lambda: True,
        )

    def _ap_policy(self):
        return SimpleNamespace(auto_create_payable_enabled=lambda: True)

    def _patch_all_policies(self):
        return patch.multiple(
            "business_apps.platform.services.CodeRuleService",
            generate=build_code_rule_generator(),
        )

    def test_accounting_period_is_scoped_per_tenant_for_same_month(self):
        other_tenant = Tenant.objects.create(code="return-finance-tenant-b", name="Return Finance Tenant B", status="ACTIVE")

        first_period = PeriodService.get_or_create_period(date(2026, 7, 14), tenant=self.tenant)
        second_period = PeriodService.get_or_create_period(date(2026, 7, 14), tenant=other_tenant)

        self.assertNotEqual(first_period.id, second_period.id)
        self.assertEqual(
            AccountingPeriod.objects.filter(year=2026, month=7).count(),
            2,
        )
        self.assertCountEqual(
            AccountingPeriod.objects.filter(year=2026, month=7).values_list("tenant_id", flat=True),
            [self.tenant.id, other_tenant.id],
        )

    def test_account_subject_codes_can_repeat_across_tenants(self):
        other_tenant = Tenant.objects.create(code="return-finance-tenant-c", name="Return Finance Tenant C", status="ACTIVE")
        other_user = ERPUser.objects.create_user(
            tenant=other_tenant,
            username="return_finance_user_b",
            password="password",
            must_change_password=False,
        )

        SubjectInitService.init_subjects(created_by=other_user)

        self.assertEqual(
            AccountSubject.objects.filter(tenant=self.tenant, code="1001").count(),
            1,
        )
        self.assertEqual(
            AccountSubject.objects.filter(tenant=other_tenant, code="1001").count(),
            1,
        )

    def test_business_posting_log_unique_scope_is_per_tenant(self):
        other_tenant = Tenant.objects.create(code="return-finance-tenant-d", name="Return Finance Tenant D", status="ACTIVE")

        first = BusinessPostingLog.objects.create(
            tenant=self.tenant,
            event_type="PURCHASE_RECEIPT_CONFIRMED",
            business_type="PURCHASE_RECEIPT",
            business_id=99,
            business_document_no="RC-LOG-001",
        )
        second = BusinessPostingLog.objects.create(
            tenant=other_tenant,
            event_type="PURCHASE_RECEIPT_CONFIRMED",
            business_type="PURCHASE_RECEIPT",
            business_id=99,
            business_document_no="RC-LOG-001",
        )

        self.assertNotEqual(first.id, second.id)

    @patch("business_apps.ar_receivable.serializers.has_erp_role_permission", return_value=True)
    def test_receipt_and_refund_serializer_use_their_own_permission_codes(self, mocked_has_permission):
        receivable = Receivable.objects.create(
            tenant=self.tenant,
            receivable_no="AR-PERMISSION-REFUND-001",
            customer=self.customer,
            source_type="SALES_RETURN",
            amount=Decimal("-10.00"),
            due_date="2026-07-13",
            status="REFUND_PENDING",
        )
        receipt = Receipt.objects.create(
            tenant=self.tenant,
            receipt_no="RC-PERMISSION-001",
            customer=self.customer,
            amount=Decimal("10.00"),
            unwritten_amount=Decimal("10.00"),
            receipt_date="2026-07-13",
            status="DRAFT",
        )
        refund = CustomerRefund.objects.create(
            tenant=self.tenant,
            refund_no="RF-PERMISSION-001",
            customer=self.customer,
            receivable=receivable,
            refund_amount=Decimal("10.00"),
            refund_date="2026-07-13",
            status="PENDING_APPROVAL",
        )
        request = SimpleNamespace(user=self.user)

        self.assertTrue(ReceiptSerializer(context={"request": request}).get_can_approve(receipt))
        self.assertTrue(CustomerRefundSerializer(context={"request": request}).get_can_approve(refund))
        self.assertEqual(
            [call.args[1] for call in mocked_has_permission.call_args_list],
            ["ar:receipt:approve", "ar:refund:approve"],
        )

    @patch("business_apps.inventory.services.get_policy")
    @patch("business_apps.accounting.services.get_policy")
    @patch("business_apps.supply_chain.services.get_policy")
    @patch("business_apps.platform.services.CodeRuleService.generate")
    def test_sales_return_completion_adjusts_ar_and_posts_voucher(
        self,
        mocked_generate,
        mocked_supply_chain_policy,
        mocked_accounting_policy,
        mocked_inventory_policy,
    ):
        mocked_generate.side_effect = build_code_rule_generator()
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()
        mocked_accounting_policy.return_value = self._accounting_policy()
        mocked_inventory_policy.return_value = self._inventory_policy()

        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-RETURN-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_SHIPPED,
            total_quantity=Decimal("5.000"),
            total_amount=Decimal("50.00"),
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            tenant=self.tenant,
            order=sales_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("5.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("50.00"),
            shipped_quantity=Decimal("5.000"),
        )
        Receivable.objects.create(
            tenant=self.tenant,
            receivable_no="AR-RETURN-001",
            customer=self.customer,
            sales_order=sales_order,
            source_type="OUTBOUND_ORDER",
            amount=Decimal("30.00"),
            written_off_amount=Decimal("0.00"),
            due_date=sales_order.order_date,
            status="UNPAID",
        )
        return_order = SalesReturnOrder.objects.create(
            tenant=self.tenant,
            return_no="SR-RETURN-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            sales_order=sales_order,
            warehouse=self.warehouse,
            status="APPROVED",
            created_by=self.user,
        )
        SalesReturnOrderItem.objects.create(
            tenant=self.tenant,
            return_order=return_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("5.000"),
        )

        SalesReturnService.complete_order(return_order, self.user)

        return_order.refresh_from_db()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        adjusted_receivable = Receivable.objects.get(receivable_no="AR-RETURN-001")
        return_credit = Receivable.objects.get(source_type="SALES_RETURN", sales_order=sales_order)
        return_offset = WriteOff.objects.get(write_off_type="RETURN_OFFSET", receivable=adjusted_receivable)
        voucher = Voucher.objects.get(source_type="SALES_RETURN_ORDER", source_id=return_order.id)
        posting_log = BusinessPostingLog.objects.get(
            event_type="SALES_RETURN_COMPLETED",
            business_type="SALES_RETURN_ORDER",
            business_id=return_order.id,
        )

        self.assertEqual(return_order.status, "COMPLETED")
        self.assertEqual(return_order.finance_status, "ADJUSTED")
        self.assertEqual(inventory.current_qty, Decimal("5.000"))
        self.assertEqual(adjusted_receivable.amount, Decimal("0.00"))
        self.assertEqual(adjusted_receivable.status, "PAID")
        self.assertEqual(return_credit.amount, Decimal("-20.00"))
        self.assertEqual(return_credit.status, "REFUND_PENDING")
        self.assertIsNone(return_offset.receipt)
        self.assertEqual(return_offset.amount, Decimal("30.00"))
        refund = CustomerRefund.objects.get(receivable=return_credit)
        self.assertEqual(refund.refund_amount, Decimal("20.00"))
        self.assertEqual(refund.status, "DRAFT")
        self.assertEqual(voucher.total_debit, Decimal("50.00"))
        self.assertEqual(voucher.total_credit, Decimal("50.00"))
        self.assertEqual(posting_log.voucher_id, voucher.id)

    @patch("business_apps.supply_chain.services.get_policy")
    def test_sales_return_create_requires_sales_order(self, mocked_supply_chain_policy):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()

        with self.assertRaisesMessage(ValueError, "销售退货单必须关联销售订单"):
            SalesReturnService.create_order(
                self.customer,
                None,
                self.warehouse,
                [{"product": self.product, "quantity": Decimal("1.000")}],
                self.user,
            )

    @patch("business_apps.supply_chain.services.get_policy")
    def test_sales_return_create_rejects_quantity_exceeding_shipped_minus_existing_returns(self, mocked_supply_chain_policy):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()

        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-RETURN-VALIDATE-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_SHIPPED,
            total_quantity=Decimal("5.000"),
            total_amount=Decimal("50.00"),
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            tenant=self.tenant,
            order=sales_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("5.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("50.00"),
            shipped_quantity=Decimal("5.000"),
        )
        occupied_return = SalesReturnOrder.objects.create(
            tenant=self.tenant,
            return_no="SR-OCCUPIED-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            sales_order=sales_order,
            warehouse=self.warehouse,
            status="APPROVED",
            created_by=self.user,
        )
        SalesReturnOrderItem.objects.create(
            tenant=self.tenant,
            return_order=occupied_return,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("4.000"),
        )

        with self.assertRaisesMessage(ValueError, "销售退货数量超出可退范围：退货商品，已发货5.000，其他退货已占用4.000，本次申请2.000"):
            SalesReturnService.create_order(
                self.customer,
                sales_order,
                self.warehouse,
                [{"product": self.product, "quantity": Decimal("2.000")}],
                self.user,
            )

    @patch("business_apps.supply_chain.services.get_policy")
    def test_sales_return_requires_submit_and_different_approver(self, mocked_supply_chain_policy):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy_with_return_approval()

        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-RETURN-SUBMIT-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_SHIPPED,
            total_quantity=Decimal("3.000"),
            total_amount=Decimal("30.00"),
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            tenant=self.tenant,
            order=sales_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("3.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("30.00"),
            shipped_quantity=Decimal("3.000"),
        )
        return_order = SalesReturnService.create_order(
            self.customer,
            sales_order,
            self.warehouse,
            [{"product": self.product, "quantity": Decimal("1.000")}],
            self.user,
        )

        with self.assertRaisesMessage(ValueError, "只有待审核状态的销售退货单可以审核"):
            SalesReturnService.approve_order(return_order, self.approver)

        SalesReturnService.submit_order(return_order, self.user)
        return_order.refresh_from_db()
        self.assertEqual(return_order.status, "PENDING_APPROVAL")
        self.assertEqual(return_order.submitted_by_id, self.user.id)
        self.assertIsNotNone(return_order.submitted_at)

        with self.assertRaisesMessage(ValueError, "审核人不能是单据创建人"):
            SalesReturnService.approve_order(return_order, self.user)

        SalesReturnService.approve_order(return_order, self.approver)
        return_order.refresh_from_db()
        self.assertEqual(return_order.status, "APPROVED")
        self.assertEqual(return_order.approved_by_id, self.approver.id)
        self.assertIsNotNone(return_order.approved_at)

    @patch("core_apps.common.permissions.has_erp_role_permission", return_value=True)
    @patch("business_apps.supply_chain.services.get_policy")
    def test_sales_return_api_rejects_missing_sales_order(self, mocked_supply_chain_policy, _mocked_has_permission):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()

        response = self.api_client.post(
            "/api/supply-chain/sales-returns/",
            {
                "customer": self.customer.id,
                "warehouse": self.warehouse.id,
                "reason": "missing order",
                "items": [{"product": self.product.id, "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "销售退货单必须关联销售订单")

    @patch("core_apps.common.permissions.has_erp_role_permission", return_value=True)
    @patch("business_apps.supply_chain.services.get_policy")
    def test_sales_return_api_rejects_quantity_exceeding_shipped_amount(self, mocked_supply_chain_policy, _mocked_has_permission):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()

        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-RETURN-API-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_SHIPPED,
            total_quantity=Decimal("5.000"),
            total_amount=Decimal("50.00"),
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            tenant=self.tenant,
            order=sales_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("5.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("50.00"),
            shipped_quantity=Decimal("5.000"),
        )

        response = self.api_client.post(
            "/api/supply-chain/sales-returns/",
            {
                "customer": self.customer.id,
                "sales_order": sales_order.id,
                "warehouse": self.warehouse.id,
                "reason": "too much",
                "items": [{"product": self.product.id, "quantity": "6.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "销售退货数量超出可退范围：退货商品，已发货5.000，其他退货已占用0.000，本次申请6.000",
        )

    @patch("core_apps.common.permissions.has_erp_role_permission", return_value=True)
    @patch("business_apps.supply_chain.services.get_policy")
    @patch("business_apps.supply_chain.services.CodeRuleService.generate", return_value="SR-REF-SUBMIT-001")
    def test_sales_return_submit_accepts_order_visible_through_reference_scope(
        self,
        _mocked_generate,
        mocked_supply_chain_policy,
        _mocked_has_permission,
    ):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()
        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-RETURN-REF-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_SHIPPED,
            total_quantity=Decimal("2.000"),
            total_amount=Decimal("20.00"),
            created_by=self.approver,
        )
        SalesOrderItem.objects.create(
            tenant=self.tenant,
            order=sales_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("2.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("20.00"),
            shipped_quantity=Decimal("2.000"),
        )

        response = self.api_client.post(
            "/api/supply-chain/sales-returns/",
            {
                "customer": self.customer.id,
                "sales_order": sales_order.id,
                "warehouse": self.warehouse.id,
                "reason": "引用权限提交",
                "items": [{"product": self.product.id, "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["sales_order"], sales_order.id)

    @patch("core_apps.common.permissions.has_erp_role_permission", return_value=True)
    @patch("core_apps.common.permissions.TenantService.get_runtime_config")
    @patch("business_apps.ar_receivable.services.get_policy")
    @patch("business_apps.ar_receivable.services.ARService.generate_no", return_value="RC-REF-SUBMIT-001")
    def test_receipt_submit_accepts_customer_and_cash_account_from_reference_scope(
        self,
        _mocked_generate_no,
        mocked_ar_policy,
        mocked_runtime_config,
        _mocked_has_permission,
    ):
        mocked_ar_policy.return_value = SimpleNamespace(receipt_approval_enabled=lambda: True)
        mocked_runtime_config.return_value = SimpleNamespace(
            is_enabled=lambda module_key: module_key in {"ar_receivable", "crm", "finance"}
        )
        referenced_customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="RETURN-CUS-REF-002",
            customer_name="其他负责人客户",
            owner=self.approver,
            created_by=self.approver,
            status="ACTIVE",
        )
        cash_account = CashAccount.objects.create(
            tenant=self.tenant,
            name="引用资金账户",
            type="BANK",
            account_type="BANK",
            status=True,
        )

        response = self.api_client.post(
            "/api/ar-receivable/receipts/",
            {
                "customer": referenced_customer.id,
                "cash_account": cash_account.id,
                "amount": "100.00",
                "receipt_date": "2026-07-18",
                "payment_method": "BANK_TRANSFER",
                "reference_no": "REF-SUBMIT",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["customer"], referenced_customer.id)
        self.assertEqual(response.data["cash_account"], cash_account.id)

    @patch("business_apps.ap_payable.services.get_policy")
    @patch("business_apps.inventory.services.get_policy")
    @patch("business_apps.accounting.services.get_policy")
    @patch("business_apps.supply_chain.services.get_policy")
    @patch("business_apps.platform.services.CodeRuleService.generate")
    def test_purchase_return_completion_creates_credit_note_and_credit_note_can_offset_future_ap(
        self,
        mocked_generate,
        mocked_supply_chain_policy,
        mocked_accounting_policy,
        mocked_inventory_policy,
        mocked_ap_policy,
    ):
        mocked_generate.side_effect = build_code_rule_generator()
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()
        mocked_accounting_policy.return_value = self._accounting_policy()
        mocked_inventory_policy.return_value = self._inventory_policy()
        mocked_ap_policy.return_value = self._ap_policy()

        purchase_order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO-RETURN-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            status=PurchaseOrder.STATUS_RECEIVED,
            total_quantity=Decimal("5.000"),
            total_amount=Decimal("50.00"),
            created_by=self.user,
        )
        purchase_order_item = PurchaseOrderItem.objects.create(
            tenant=self.tenant,
            purchase_order=purchase_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            warehouse=self.warehouse,
            quantity=Decimal("5.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("50.00"),
            received_quantity=Decimal("5.000"),
        )
        Inventory.objects.create(
            tenant=self.tenant,
            warehouse=self.warehouse,
            product=self.product,
            current_qty=Decimal("5.000"),
            locked_qty=Decimal("0.000"),
        )
        APAccount.objects.create(
            tenant=self.tenant,
            ap_no="AP-RETURN-001",
            supplier=self.supplier,
            source_type="MANUAL",
            total_amount=Decimal("30.00"),
            paid_amount=Decimal("0.00"),
            due_date=purchase_order.order_date,
            status="PENDING",
        )
        return_order = PurchaseReturnOrder.objects.create(
            tenant=self.tenant,
            return_no="PR-RETURN-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            purchase_order=purchase_order,
            warehouse=self.warehouse,
            status="APPROVED",
            created_by=self.user,
        )
        PurchaseReturnOrderItem.objects.create(
            tenant=self.tenant,
            return_order=return_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("5.000"),
        )

        PurchaseReturnService.complete_order(return_order, self.user)

        return_order.refresh_from_db()
        purchase_order_item.refresh_from_db()
        adjusted_ap = APAccount.objects.get(ap_no="AP-RETURN-001")
        credit_note = SupplierCreditNote.objects.get(source_id=return_order.id)
        supplier_refund = SupplierRefund.objects.get(credit_note=credit_note)
        voucher = Voucher.objects.get(source_type="PURCHASE_RETURN_ORDER", source_id=return_order.id)
        posting_log = BusinessPostingLog.objects.get(
            event_type="PURCHASE_RETURN_COMPLETED",
            business_type="PURCHASE_RETURN_ORDER",
            business_id=return_order.id,
        )

        self.assertEqual(return_order.status, "COMPLETED")
        self.assertEqual(return_order.finance_status, "ADJUSTED")
        self.assertEqual(purchase_order_item.returned_quantity, Decimal("5.000"))
        self.assertEqual(adjusted_ap.total_amount, Decimal("0.00"))
        self.assertEqual(adjusted_ap.status, "PAID")
        self.assertEqual(credit_note.amount, Decimal("20.00"))
        self.assertEqual(credit_note.used_amount, Decimal("0.00"))
        self.assertEqual(credit_note.status, "OPEN")
        self.assertEqual(supplier_refund.refund_amount, Decimal("20.00"))
        self.assertEqual(supplier_refund.status, "DRAFT")
        self.assertEqual(voucher.total_debit, Decimal("50.00"))
        self.assertEqual(voucher.total_credit, Decimal("50.00"))
        self.assertEqual(posting_log.voucher_id, voucher.id)

        receipt = PurchaseReceipt.objects.create(
            tenant=self.tenant,
            receipt_no="RC-RETURN-001",
            purchase_order=purchase_order,
            warehouse=self.warehouse,
            status="COMPLETED",
            created_by=self.user,
        )
        PurchaseReceiptItem.objects.create(
            tenant=self.tenant,
            receipt=receipt,
            purchase_order_item=purchase_order_item,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            received_quantity=Decimal("1.000"),
        )

        offset_ap = APService.generate_ap_from_receipt(receipt, self.user)

        credit_note.refresh_from_db()
        offset_ap.refresh_from_db()
        self.assertEqual(offset_ap.total_amount, Decimal("0.00"))
        self.assertEqual(offset_ap.status, "PAID")
        self.assertEqual(credit_note.used_amount, Decimal("10.00"))
        self.assertEqual(credit_note.status, "PARTIAL_USED")

    @patch("business_apps.supply_chain.services.get_policy")
    def test_purchase_return_create_requires_purchase_order(self, mocked_supply_chain_policy):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()

        with self.assertRaisesMessage(ValueError, "采购退货单必须关联采购订单"):
            PurchaseReturnService.create_order(
                self.supplier,
                None,
                self.warehouse,
                [{"product": self.product, "quantity": Decimal("1.000")}],
                self.user,
            )

    @patch("business_apps.supply_chain.services.get_policy")
    def test_purchase_return_create_rejects_quantity_exceeding_received_minus_existing_returns(self, mocked_supply_chain_policy):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()

        purchase_order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO-RETURN-VALIDATE-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            status=PurchaseOrder.STATUS_RECEIVED,
            total_quantity=Decimal("5.000"),
            total_amount=Decimal("50.00"),
            created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            tenant=self.tenant,
            purchase_order=purchase_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            warehouse=self.warehouse,
            quantity=Decimal("5.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("50.00"),
            received_quantity=Decimal("5.000"),
        )
        occupied_return = PurchaseReturnOrder.objects.create(
            tenant=self.tenant,
            return_no="PR-OCCUPIED-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            purchase_order=purchase_order,
            warehouse=self.warehouse,
            status="APPROVED",
            created_by=self.user,
        )
        PurchaseReturnOrderItem.objects.create(
            tenant=self.tenant,
            return_order=occupied_return,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("4.000"),
        )

        with self.assertRaisesMessage(ValueError, "采购退货数量超出可退范围：退货商品，已收货5.000，其他退货已占用4.000，本次申请2.000"):
            PurchaseReturnService.create_order(
                self.supplier,
                purchase_order,
                self.warehouse,
                [{"product": self.product, "quantity": Decimal("2.000")}],
                self.user,
            )

    @patch("business_apps.supply_chain.services.get_policy")
    def test_purchase_return_requires_submit_and_different_approver(self, mocked_supply_chain_policy):
        mocked_supply_chain_policy.return_value = self._supply_chain_policy_with_return_approval()

        purchase_order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO-RETURN-SUBMIT-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            status=PurchaseOrder.STATUS_RECEIVED,
            total_quantity=Decimal("3.000"),
            total_amount=Decimal("24.00"),
            created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            tenant=self.tenant,
            purchase_order=purchase_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("3.000"),
            unit_price=Decimal("8.00"),
            amount=Decimal("24.00"),
            received_quantity=Decimal("3.000"),
        )
        return_order = PurchaseReturnService.create_order(
            self.supplier,
            purchase_order,
            self.warehouse,
            [{"product": self.product, "quantity": Decimal("1.000")}],
            self.user,
        )

        with self.assertRaisesMessage(ValueError, "只有待审核状态的采购退货单可以审核"):
            PurchaseReturnService.approve_order(return_order, self.approver)

        PurchaseReturnService.submit_order(return_order, self.user)
        return_order.refresh_from_db()
        self.assertEqual(return_order.status, "PENDING_APPROVAL")
        self.assertEqual(return_order.submitted_by_id, self.user.id)
        self.assertIsNotNone(return_order.submitted_at)

        with self.assertRaisesMessage(ValueError, "审核人不能是单据创建人"):
            PurchaseReturnService.approve_order(return_order, self.user)

        PurchaseReturnService.approve_order(return_order, self.approver)
        return_order.refresh_from_db()
        self.assertEqual(return_order.status, "APPROVED")
        self.assertEqual(return_order.approved_by_id, self.approver.id)
        self.assertIsNotNone(return_order.approved_at)

    @patch("business_apps.inventory.services.get_policy")
    @patch("business_apps.accounting.services.get_policy")
    @patch("business_apps.supply_chain.services.get_policy")
    @patch("business_apps.platform.services.CodeRuleService.generate")
    def test_customer_refund_execution_marks_negative_receivable_refunded_and_posts_voucher(
        self,
        mocked_generate,
        mocked_supply_chain_policy,
        mocked_accounting_policy,
        mocked_inventory_policy,
    ):
        mocked_generate.side_effect = build_code_rule_generator()
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()
        mocked_accounting_policy.return_value = self._accounting_policy()
        mocked_inventory_policy.return_value = self._inventory_policy()

        sales_order = SalesOrder.objects.create(
            tenant=self.tenant,
            order_no="SO-RETURN-REFUND-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            status=SalesOrder.STATUS_SHIPPED,
            total_quantity=Decimal("5.000"),
            total_amount=Decimal("50.00"),
            created_by=self.user,
        )
        SalesOrderItem.objects.create(
            tenant=self.tenant,
            order=sales_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            warehouse=self.warehouse,
            quantity=Decimal("5.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("50.00"),
            shipped_quantity=Decimal("5.000"),
        )
        Receivable.objects.create(
            tenant=self.tenant,
            receivable_no="AR-RETURN-REFUND-001",
            customer=self.customer,
            sales_order=sales_order,
            source_type="OUTBOUND_ORDER",
            amount=Decimal("30.00"),
            written_off_amount=Decimal("30.00"),
            due_date=sales_order.order_date,
            status="PAID",
        )
        return_order = SalesReturnOrder.objects.create(
            tenant=self.tenant,
            return_no="SR-RETURN-REFUND-001",
            customer=self.customer,
            customer_name_snapshot=self.customer.customer_name,
            sales_order=sales_order,
            warehouse=self.warehouse,
            status="APPROVED",
            created_by=self.user,
        )
        SalesReturnOrderItem.objects.create(
            tenant=self.tenant,
            return_order=return_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("2.000"),
        )

        SalesReturnService.complete_order(return_order, self.user)
        refund = CustomerRefund.objects.get(customer=self.customer)
        cash_account = CashAccount.objects.create(
            tenant=self.tenant,
            name="退款银行账户",
            type="BANK",
            account_type="BANK",
            account_no="6222000000000001",
            current_balance=Decimal("100.00"),
            status=True,
        )
        ARService.submit_customer_refund(refund, self.user)
        ARService.approve_customer_refund(refund, self.approver)
        ARService.execute_customer_refund(
            refund,
            self.user,
            payment_method="BANK_TRANSFER",
            cash_account=cash_account,
            bank_account="6222000000009999",
            reference_no="AR-REFUND-TRACE-001",
            remark="客户退款执行",
        )

        refund.refresh_from_db()
        refund_receivable = Receivable.objects.get(id=refund.receivable_id)
        voucher = Voucher.objects.get(source_type="AR_REFUND", source_id=refund.id)

        self.assertEqual(refund.status, "COMPLETED")
        self.assertEqual(refund.submitted_by_id, self.user.id)
        self.assertEqual(refund.approved_by_id, self.approver.id)
        self.assertEqual(refund.cash_account_id, cash_account.id)
        self.assertEqual(refund.bank_account, "6222000000009999")
        self.assertEqual(refund_receivable.status, "REFUNDED")
        self.assertEqual(refund_receivable.written_off_amount, Decimal("20.00"))
        self.assertEqual(voucher.total_debit, Decimal("20.00"))
        self.assertEqual(voucher.total_credit, Decimal("20.00"))

    def test_customer_refund_requires_submit_and_different_approver(self):
        receivable = Receivable.objects.create(
            tenant=self.tenant,
            receivable_no="AR-REFUND-SUBMIT-001",
            customer=self.customer,
            source_type="SALES_RETURN",
            amount=Decimal("-10.00"),
            written_off_amount=Decimal("0.00"),
            due_date="2026-07-13",
            status="REFUND_PENDING",
        )
        refund = CustomerRefund.objects.create(
            tenant=self.tenant,
            refund_no="RF-SUBMIT-001",
            customer=self.customer,
            receivable=receivable,
            refund_amount=Decimal("10.00"),
            refund_date="2026-07-13",
            status="DRAFT",
            created_by=self.user,
        )

        with self.assertRaisesMessage(ValueError, "只有待审核状态的退款单可以审核"):
            ARService.approve_customer_refund(refund, self.approver)

        ARService.submit_customer_refund(refund, self.user)
        with self.assertRaisesMessage(ValueError, "审核人不能是退款单创建人或提交人"):
            ARService.approve_customer_refund(refund, self.user)

    @patch("business_apps.ap_payable.services.get_policy")
    @patch("business_apps.inventory.services.get_policy")
    @patch("business_apps.accounting.services.get_policy")
    @patch("business_apps.supply_chain.services.get_policy")
    @patch("business_apps.platform.services.CodeRuleService.generate")
    def test_supplier_refund_execution_marks_credit_note_used_and_posts_voucher(
        self,
        mocked_generate,
        mocked_supply_chain_policy,
        mocked_accounting_policy,
        mocked_inventory_policy,
        mocked_ap_policy,
    ):
        mocked_generate.side_effect = build_code_rule_generator()
        mocked_supply_chain_policy.return_value = self._supply_chain_policy()
        mocked_accounting_policy.return_value = self._accounting_policy()
        mocked_inventory_policy.return_value = self._inventory_policy()
        mocked_ap_policy.return_value = self._ap_policy()

        purchase_order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO-RETURN-REFUND-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            status=PurchaseOrder.STATUS_RECEIVED,
            total_quantity=Decimal("3.000"),
            total_amount=Decimal("30.00"),
            created_by=self.user,
        )
        purchase_order_item = PurchaseOrderItem.objects.create(
            tenant=self.tenant,
            purchase_order=purchase_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            warehouse=self.warehouse,
            quantity=Decimal("3.000"),
            unit_price=Decimal("10.00"),
            amount=Decimal("30.00"),
            received_quantity=Decimal("3.000"),
        )
        Inventory.objects.create(
            tenant=self.tenant,
            warehouse=self.warehouse,
            product=self.product,
            current_qty=Decimal("10.000"),
            locked_qty=Decimal("0.000"),
        )
        APAccount.objects.create(
            tenant=self.tenant,
            ap_no="AP-RETURN-REFUND-001",
            supplier=self.supplier,
            source_type="MANUAL",
            total_amount=Decimal("10.00"),
            paid_amount=Decimal("10.00"),
            due_date=purchase_order.order_date,
            status="PAID",
        )
        return_order = PurchaseReturnOrder.objects.create(
            tenant=self.tenant,
            return_no="PR-RETURN-REFUND-001",
            supplier=self.supplier,
            supplier_name_snapshot=self.supplier.supplier_name,
            purchase_order=purchase_order,
            warehouse=self.warehouse,
            status="APPROVED",
            created_by=self.user,
        )
        PurchaseReturnOrderItem.objects.create(
            tenant=self.tenant,
            return_order=return_order,
            product=self.product,
            product_name_snapshot=self.product.name,
            product_code_snapshot=self.product.product_code,
            quantity=Decimal("3.000"),
        )

        PurchaseReturnService.complete_order(return_order, self.user)
        refund = SupplierRefund.objects.get(supplier=self.supplier)
        cash_account = CashAccount.objects.create(
            tenant=self.tenant,
            name="供应商退款收款账户",
            type="BANK",
            account_type="BANK",
            account_no="6222000000000002",
            current_balance=Decimal("0.00"),
            status=True,
        )
        APService.submit_supplier_refund(refund, self.user)
        APService.approve_supplier_refund(refund, self.approver)
        APService.execute_supplier_refund(
            refund,
            self.user,
            payment_method="BANK_TRANSFER",
            cash_account=cash_account,
            bank_account="6222000000008888",
            reference_no="AP-REFUND-TRACE-001",
            remark="供应商退款收款",
        )

        refund.refresh_from_db()
        purchase_order_item.refresh_from_db()
        credit_note = SupplierCreditNote.objects.get(id=refund.credit_note_id)
        voucher = Voucher.objects.get(source_type="AP_SUPPLIER_REFUND", source_id=refund.id)

        self.assertEqual(refund.status, "COMPLETED")
        self.assertEqual(refund.submitted_by_id, self.user.id)
        self.assertEqual(refund.approved_by_id, self.approver.id)
        self.assertEqual(refund.cash_account_id, cash_account.id)
        self.assertEqual(refund.bank_account, "6222000000008888")
        self.assertEqual(credit_note.status, "USED")
        self.assertEqual(credit_note.used_amount, Decimal("30.00"))
        self.assertEqual(purchase_order_item.returned_quantity, Decimal("3.000"))
        self.assertEqual(voucher.total_debit, Decimal("30.00"))
        self.assertEqual(voucher.total_credit, Decimal("30.00"))

    def test_supplier_refund_requires_submit_and_different_approver(self):
        credit_note = SupplierCreditNote.objects.create(
            tenant=self.tenant,
            credit_note_no="CN-SUBMIT-001",
            supplier=self.supplier,
            source_document_no_snapshot="PR-SUBMIT-001",
            source_id=1,
            amount=Decimal("10.00"),
            used_amount=Decimal("0.00"),
            note_date="2026-07-13",
            status="OPEN",
            created_by=self.user,
        )
        refund = SupplierRefund.objects.create(
            tenant=self.tenant,
            refund_no="SRF-SUBMIT-001",
            supplier=self.supplier,
            credit_note=credit_note,
            refund_amount=Decimal("10.00"),
            refund_date="2026-07-13",
            status="DRAFT",
            created_by=self.user,
        )

        with self.assertRaisesMessage(ValueError, "只有待审核状态的供应商退款单可以审核"):
            APService.approve_supplier_refund(refund, self.approver)

        APService.submit_supplier_refund(refund, self.user)
        with self.assertRaisesMessage(ValueError, "审核人不能是退款单创建人或提交人"):
            APService.approve_supplier_refund(refund, self.user)
