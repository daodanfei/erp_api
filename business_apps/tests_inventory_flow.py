from decimal import Decimal
import unittest

from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from business_apps.accounting.models import BusinessPostingLog, Voucher
from business_apps.accounting.services import PostingService, SubjectInitService
from business_apps.ap_payable.models import APAccount
from business_apps.ap_payable.services import APService
from business_apps.ar_receivable.models import Receivable
from business_apps.ar_receivable.services import ARService
from business_apps.crm.models import Customer
from business_apps.finance.models import CashAccount, CashAccountTransaction
from business_apps.inventory.models import (
    Inventory,
    InventoryTransaction,
    Product,
    ProductCategory,
    Unit,
    Warehouse,
)
from business_apps.inventory.services import InventoryService
from business_apps.inventory.services import COMMON_UNIT_NAMES, UnitService
from business_apps.platform.services import CodeRuleService
from business_apps.purchase.models import PurchaseOrderItem
from business_apps.purchase.services import PurchaseOrderService
from business_apps.sales.services import SalesOrderService
from business_apps.supply_chain.models import OutboundOrder
from business_apps.supply_chain.services import (
    OutboundService,
    PurchaseReturnService,
    SalesReturnService,
    TransferService,
)
from business_apps.supplier.models import Supplier
from core_apps.authentication.models import User


class InventoryFlowE2ETest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(username="flow_creator", password="pass")
        cls.approver = User.objects.create_user(username="flow_approver", password="pass")
        cls.executor = User.objects.create_user(username="flow_executor", password="pass")
        CodeRuleService.init_default_rules(created_by=cls.creator)
        SubjectInitService.init_subjects(created_by=cls.creator)

        cls.supplier = Supplier.objects.create(
            supplier_code="SUP-E2E-001",
            supplier_name="E2E Supplier",
            status="ACTIVE",
        )
        cls.customer = Customer.objects.create(
            customer_code="CUS-E2E-001",
            customer_name="E2E Customer",
            status="ACTIVE",
            credit_limit=Decimal("100000.00"),
        )
        cls.category = ProductCategory.objects.create(name="E2E Category")
        cls.unit = Unit.objects.create(name="Piece", code="E2E-PCS")
        cls.product = Product.objects.create(
            product_code="E2E-P001",
            name="E2E Product",
            category=cls.category,
            unit=cls.unit,
            cost_price=Decimal("25.50"),
            sale_price=Decimal("40.00"),
            status="ACTIVE",
            created_by=cls.creator,
        )
        cls.warehouse = Warehouse.objects.create(
            warehouse_code="E2E-W001",
            warehouse_name="E2E Main Warehouse",
        )
        cls.cash_account = CashAccount.objects.create(
            name="E2E Bank",
            type="BANK",
            account_type="BANK",
            current_balance=Decimal("1000.00"),
        )

    def create_approved_purchase_order(self, quantity=Decimal("10.000")):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": quantity,
                    "unit_price": Decimal("25.50"),
                }
            ],
            user=self.creator,
        )
        PurchaseOrderService.submit_order(order, self.creator)
        PurchaseOrderService.approve_order(order, self.approver)
        order.refresh_from_db()
        return order

    def complete_purchase_receipt(self, order, quantity):
        po_item = PurchaseOrderItem.objects.get(purchase_order=order, product=self.product)
        receipt = PurchaseOrderService.create_receipt(
            order=order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "purchase_order_item": po_item,
                    "received_quantity": quantity,
                }
            ],
            user=self.creator,
        )
        PurchaseOrderService.complete_receipt(receipt, self.creator)
        receipt.refresh_from_db()
        order.refresh_from_db()
        return receipt

    def approve_and_complete_outbound(self, outbound_order):
        OutboundService.submit_order(outbound_order, self.creator)
        OutboundService.approve_order(outbound_order, self.approver)
        OutboundService.complete_order(outbound_order, self.creator)
        outbound_order.refresh_from_db()
        return outbound_order

    def test_purchase_receipts_update_inventory_and_create_ap(self):
        order = self.create_approved_purchase_order()

        first_receipt = self.complete_purchase_receipt(order, Decimal("6.000"))

        order.refresh_from_db()
        po_item = order.items.get()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        self.product.refresh_from_db()

        self.assertEqual(first_receipt.status, "COMPLETED")
        self.assertEqual(first_receipt.executed_by, self.creator)
        self.assertIsNotNone(first_receipt.received_at)
        self.assertEqual(order.status, "PARTIALLY_RECEIVED")
        self.assertEqual(po_item.received_quantity, Decimal("6.000"))
        self.assertEqual(inventory.current_qty, Decimal("6.000"))
        self.assertEqual(inventory.locked_qty, Decimal("0.000"))
        self.assertEqual(self.product.current_stock, Decimal("6.000"))

        purchase_in = InventoryTransaction.objects.get(
            reference_type="PURCHASE_RECEIPT",
            reference_id=first_receipt.id,
            transaction_type="PURCHASE_IN",
        )
        self.assertEqual(purchase_in.business_date, timezone.localdate())
        self.assertEqual(purchase_in.direction, InventoryTransaction.DIRECTION_IN)
        self.assertEqual(purchase_in.quantity, Decimal("6.000"))
        self.assertEqual(purchase_in.before_qty, Decimal("0.000"))
        self.assertEqual(purchase_in.after_qty, Decimal("6.000"))

        first_ap = APAccount.objects.get(purchase_receipt=first_receipt)
        self.assertEqual(first_ap.supplier, self.supplier)
        self.assertEqual(first_ap.source_type, "PURCHASE_RECEIPT")
        self.assertEqual(first_ap.source_id, first_receipt.id)
        self.assertEqual(first_ap.total_amount, Decimal("153.00"))
        self.assertEqual(first_ap.status, "PENDING")

        second_receipt = self.complete_purchase_receipt(order, Decimal("4.000"))

        order.refresh_from_db()
        inventory.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(second_receipt.status, "COMPLETED")
        self.assertEqual(order.status, "RECEIVED")
        self.assertEqual(order.items.get().received_quantity, Decimal("10.000"))
        self.assertEqual(inventory.current_qty, Decimal("10.000"))
        self.assertEqual(self.product.current_stock, Decimal("10.000"))
        self.assertEqual(APAccount.objects.filter(supplier=self.supplier).count(), 2)
        self.assertIsNone(order.closed_at)

        PurchaseOrderService.close_order(order, self.approver)
        order.refresh_from_db()
        self.assertEqual(order.status, "CLOSED")
        self.assertIsNotNone(order.closed_at)

    def test_purchase_receipt_rejects_over_receipt_without_changing_stock(self):
        order = self.create_approved_purchase_order(quantity=Decimal("5.000"))
        po_item = order.items.get()

        with self.assertRaises(ValueError):
            PurchaseOrderService.create_receipt(
                order=order,
                warehouse=self.warehouse,
                items_data=[
                    {
                        "purchase_order_item": po_item,
                        "received_quantity": Decimal("6.000"),
                    }
                ],
                user=self.creator,
            )

        self.assertFalse(Inventory.objects.filter(product=self.product).exists())
        self.assertFalse(APAccount.objects.exists())

    def test_draft_purchase_receipt_can_cancel_but_completed_receipt_cannot(self):
        order = self.create_approved_purchase_order(quantity=Decimal("5.000"))
        po_item = order.items.get()
        receipt = PurchaseOrderService.create_receipt(
            order=order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "purchase_order_item": po_item,
                    "received_quantity": Decimal("2.000"),
                }
            ],
            user=self.creator,
        )

        PurchaseOrderService.cancel_receipt(receipt, self.creator)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "CANCELLED")
        self.assertIsNotNone(receipt.cancelled_at)

        completed_receipt = self.complete_purchase_receipt(order, Decimal("2.000"))
        with self.assertRaises(ValueError):
            PurchaseOrderService.cancel_receipt(completed_receipt, self.creator)

    @unittest.skip("待采购退货流程落地后补充 returned_quantity 回写测试")
    def test_purchase_return_updates_returned_quantity_placeholder(self):
        order = self.create_approved_purchase_order(quantity=Decimal("5.000"))
        self.assertEqual(order.items.get().returned_quantity, Decimal("0.000"))

    def test_sales_fulfillment_close_inventory_and_ar_flow(self):
        purchase_order = self.create_approved_purchase_order()
        self.complete_purchase_receipt(purchase_order, Decimal("10.000"))

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("4.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)

        sales_order.refresh_from_db()
        order_item = sales_order.items.get()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        self.assertEqual(sales_order.status, "ALLOCATED")
        self.assertEqual(order_item.allocated_quantity, Decimal("4.000"))
        self.assertEqual(inventory.current_qty, Decimal("10.000"))
        self.assertEqual(inventory.locked_qty, Decimal("4.000"))
        self.assertEqual(inventory.available_qty, Decimal("6.000"))

        outbound_orders = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )
        self.assertEqual(len(outbound_orders), 1)
        self.approve_and_complete_outbound(outbound_orders[0])
        sales_order.refresh_from_db()
        order_item.refresh_from_db()
        inventory.refresh_from_db()
        self.assertEqual(sales_order.status, "PARTIALLY_SHIPPED")
        self.assertEqual(order_item.shipped_quantity, Decimal("2.000"))
        self.assertEqual(order_item.allocated_quantity, Decimal("2.000"))
        self.assertEqual(inventory.current_qty, Decimal("8.000"))
        self.assertEqual(inventory.locked_qty, Decimal("2.000"))
        first_receivable = Receivable.objects.get(outbound_order=outbound_orders[0])
        self.assertEqual(first_receivable.sales_order, sales_order)
        self.assertEqual(first_receivable.amount, Decimal("80.00"))
        self.assertEqual(first_receivable.balance, Decimal("80.00"))

        outbound_orders = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )
        self.assertEqual(len(outbound_orders), 1)
        self.approve_and_complete_outbound(outbound_orders[0])
        sales_order.refresh_from_db()
        order_item.refresh_from_db()
        inventory.refresh_from_db()
        self.product.refresh_from_db()
        self.customer.refresh_from_db()

        self.assertEqual(sales_order.status, "SHIPPED")
        self.assertEqual(order_item.shipped_quantity, Decimal("4.000"))
        self.assertEqual(order_item.allocated_quantity, Decimal("0.000"))
        self.assertEqual(inventory.current_qty, Decimal("6.000"))
        self.assertEqual(inventory.locked_qty, Decimal("0.000"))
        self.assertEqual(self.product.current_stock, Decimal("6.000"))

        second_receivable = Receivable.objects.get(outbound_order=outbound_orders[0])
        self.assertEqual(second_receivable.amount, Decimal("80.00"))
        self.assertEqual(second_receivable.balance, Decimal("80.00"))
        self.assertEqual(Receivable.objects.filter(sales_order=sales_order).count(), 2)
        self.assertEqual(self.customer.current_balance, Decimal("160.00"))
        self.assertIsNone(sales_order.closed_at)

        SalesOrderService.close_order(sales_order, self.approver)
        sales_order.refresh_from_db()
        self.assertEqual(sales_order.status, "CLOSED")
        self.assertIsNotNone(sales_order.closed_at)

        sale_out_transactions = InventoryTransaction.objects.filter(
            reference_type="OUTBOUND_ORDER",
            transaction_type="SALE_OUT",
        ).order_by("id")
        self.assertEqual(sale_out_transactions.count(), 2)
        self.assertEqual(
            [item.quantity for item in sale_out_transactions],
            [Decimal("-2.000"), Decimal("-2.000")],
        )
        self.assertTrue(
            all(item.direction == InventoryTransaction.DIRECTION_OUT for item in sale_out_transactions)
        )
        self.assertEqual(OutboundOrder.objects.filter(sales_order=sales_order, status='COMPLETED').count(), 2)

    def test_inventory_transaction_records_business_date_cost_and_cache_consistently(self):
        business_date = timezone.localdate()
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("5.000"),
            transaction_type="PURCHASE_IN",
            operator=self.creator,
            reference_type="TEST",
            reference_id=1,
            remark="seed with cost",
            business_date=business_date,
            unit_cost=Decimal("12.3456"),
        )

        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        transaction = InventoryTransaction.objects.get(reference_type="TEST", reference_id=1)
        self.product.refresh_from_db()

        self.assertEqual(inventory.current_qty, Decimal("5.000"))
        self.assertEqual(transaction.business_date, business_date)
        self.assertEqual(transaction.direction, InventoryTransaction.DIRECTION_IN)
        self.assertEqual(transaction.unit_cost, Decimal("12.3456"))
        self.assertEqual(transaction.total_cost, Decimal("61.7280"))
        self.assertEqual(self.product.current_stock, Decimal("5.000"))

    def test_reserve_release_and_ship_keep_quantities_consistent(self):
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("10.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.creator,
            remark="seed for reserve flow",
        )

        InventoryService.reserve_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("4.000"),
            operator=self.creator,
            reference_type="TEST_ORDER",
            reference_id=10,
            remark="reserve",
        )
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        self.assertEqual(inventory.current_qty, Decimal("10.000"))
        self.assertEqual(inventory.locked_qty, Decimal("4.000"))
        self.assertEqual(inventory.available_qty, Decimal("6.000"))

        InventoryService.release_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("1.000"),
            operator=self.creator,
            reference_type="TEST_ORDER",
            reference_id=10,
            remark="release partial",
        )
        inventory.refresh_from_db()
        self.assertEqual(inventory.current_qty, Decimal("10.000"))
        self.assertEqual(inventory.locked_qty, Decimal("3.000"))
        self.assertEqual(inventory.available_qty, Decimal("7.000"))

        InventoryService.ship_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("3.000"),
            operator=self.creator,
            reference_type="TEST_ORDER",
            reference_id=10,
            remark="ship remaining locked",
        )
        inventory.refresh_from_db()
        self.product.refresh_from_db()
        ship_tx = InventoryTransaction.objects.get(
            reference_type="TEST_ORDER",
            reference_id=10,
            transaction_type="SALE_OUT",
        )

        self.assertEqual(inventory.current_qty, Decimal("7.000"))
        self.assertEqual(inventory.locked_qty, Decimal("0.000"))
        self.assertEqual(inventory.available_qty, Decimal("7.000"))
        self.assertEqual(self.product.current_stock, Decimal("7.000"))
        self.assertEqual(ship_tx.direction, InventoryTransaction.DIRECTION_OUT)
        self.assertEqual(ship_tx.quantity, Decimal("-3.000"))

    def test_sales_allocation_prevents_oversell(self):
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("3.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.creator,
            remark="Seed stock for oversell test",
        )
        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("4.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)

        with self.assertRaises(ValueError):
            SalesOrderService.allocate_stock(sales_order, self.creator)

        sales_order.refresh_from_db()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        self.assertEqual(sales_order.status, "APPROVED")
        self.assertEqual(inventory.current_qty, Decimal("3.000"))
        self.assertEqual(inventory.locked_qty, Decimal("0.000"))

    def test_partial_shipment_cannot_cancel_with_open_outbound_request(self):
        purchase_order = self.create_approved_purchase_order()
        self.complete_purchase_receipt(purchase_order, Decimal("10.000"))

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("4.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)

        order_item = sales_order.items.get()
        first_outbound = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )[0]
        self.approve_and_complete_outbound(first_outbound)
        SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )

        with self.assertRaises(ValueError):
            SalesOrderService.cancel_order(sales_order, self.creator)

        sales_order.refresh_from_db()
        self.assertEqual(sales_order.status, "PARTIALLY_SHIPPED")

    def test_sales_order_repeated_allocate_outbound_and_close_are_rejected(self):
        purchase_order = self.create_approved_purchase_order()
        self.complete_purchase_receipt(purchase_order, Decimal("10.000"))

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("3.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)

        with self.assertRaises(ValueError):
            SalesOrderService.allocate_stock(sales_order, self.creator)

        order_item = sales_order.items.get()
        SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )
        with self.assertRaises(ValueError):
            SalesOrderService.create_outbound_request(
                sales_order,
                [{"order_item": order_item, "quantity": Decimal("2.000")}],
                self.creator,
            )

        last_outbound = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("1.000")}],
            self.creator,
        )[0]
        OutboundService.cancel_order(order_item.outbound_items.exclude(outbound_order=last_outbound).first().outbound_order, self.creator)
        self.approve_and_complete_outbound(last_outbound)
        sales_order.refresh_from_db()
        self.assertEqual(sales_order.status, "PARTIALLY_SHIPPED")

        final_outbound = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )[0]
        self.approve_and_complete_outbound(final_outbound)
        sales_order.refresh_from_db()
        SalesOrderService.close_order(sales_order, self.approver)

        with self.assertRaises(ValueError):
            SalesOrderService.close_order(sales_order, self.approver)

    def test_sales_return_restock_and_reverse_ar(self):
        purchase_order = self.create_approved_purchase_order()
        self.complete_purchase_receipt(purchase_order, Decimal("10.000"))

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)
        order_item = sales_order.items.get()
        outbound_order = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": order_item, "quantity": Decimal("2.000")}],
            self.creator,
        )[0]
        self.approve_and_complete_outbound(outbound_order)

        receivable = Receivable.objects.get(outbound_order=outbound_order)
        self.assertEqual(receivable.amount, Decimal("80.00"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_balance, Decimal("80.00"))

        sales_return = SalesReturnService.create_order(
            customer=self.customer,
            sales_order=sales_order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "product": self.product,
                    "quantity": Decimal("2.000"),
                    "remark": "客户退货",
                }
            ],
            user=self.creator,
            reason="售后退回",
        )
        SalesReturnService.approve_order(sales_return, self.approver)
        SalesReturnService.complete_order(sales_return, self.creator)

        sales_return.refresh_from_db()
        receivable.refresh_from_db()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        return_tx = InventoryTransaction.objects.get(
            reference_type="SALES_RETURN_ORDER",
            reference_id=sales_return.id,
            transaction_type="RETURN_IN",
        )
        self.customer.refresh_from_db()

        self.assertEqual(sales_return.status, "COMPLETED")
        self.assertEqual(sales_return.finance_status, "ADJUSTED")
        self.assertEqual(inventory.current_qty, Decimal("10.000"))
        self.assertEqual(return_tx.quantity, Decimal("2.000"))
        self.assertEqual(receivable.amount, Decimal("0.00"))
        self.assertEqual(receivable.status, "PAID")
        self.assertEqual(self.customer.current_balance, Decimal("0.00"))

    def test_purchase_return_destock_and_reverse_ap(self):
        purchase_order = self.create_approved_purchase_order(quantity=Decimal("6.000"))
        receipt = self.complete_purchase_receipt(purchase_order, Decimal("6.000"))
        ap_account = APAccount.objects.get(purchase_receipt=receipt)
        self.assertEqual(ap_account.total_amount, Decimal("153.00"))

        purchase_return = PurchaseReturnService.create_order(
            supplier=self.supplier,
            purchase_order=purchase_order,
            warehouse=self.warehouse,
            items_data=[
                {
                    "product": self.product,
                    "quantity": Decimal("2.000"),
                    "remark": "采购退货",
                }
            ],
            user=self.creator,
            reason="来料问题",
        )
        PurchaseReturnService.approve_order(purchase_return, self.approver)
        PurchaseReturnService.complete_order(purchase_return, self.creator)

        purchase_return.refresh_from_db()
        ap_account.refresh_from_db()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        return_tx = InventoryTransaction.objects.get(
            reference_type="PURCHASE_RETURN_ORDER",
            reference_id=purchase_return.id,
            transaction_type="RETURN_OUT",
        )

        self.assertEqual(purchase_return.status, "COMPLETED")
        self.assertEqual(purchase_return.finance_status, "ADJUSTED")
        self.assertEqual(inventory.current_qty, Decimal("4.000"))
        self.assertEqual(return_tx.quantity, Decimal("-2.000"))
        self.assertEqual(ap_account.total_amount, Decimal("102.00"))
        self.assertEqual(ap_account.status, "PENDING")

    def test_receipt_and_payment_approval_execution_separation_flow(self):
        purchase_order = self.create_approved_purchase_order(quantity=Decimal("5.000"))
        purchase_receipt = self.complete_purchase_receipt(purchase_order, Decimal("5.000"))
        ap_account = APAccount.objects.get(purchase_receipt=purchase_receipt)

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)
        outbound_order = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": sales_order.items.get(), "quantity": Decimal("2.000")}],
            self.creator,
        )[0]
        self.approve_and_complete_outbound(outbound_order)
        receivable = Receivable.objects.get(outbound_order=outbound_order)

        receipt = ARService.create_receipt(
            self.customer,
            Decimal("80.00"),
            timezone.localdate(),
            "BANK_TRANSFER",
            self.creator,
            cash_account=self.cash_account,
        )
        with self.assertRaises(ValueError):
            ARService.approve_receipt(receipt, self.creator)
        approved_receipt = ARService.approve_receipt(receipt, self.approver)
        self.cash_account.refresh_from_db()
        self.assertEqual(approved_receipt.status, "UNWRITTEN")
        self.assertEqual(approved_receipt.approved_by, self.approver)
        self.assertIsNone(approved_receipt.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal("1000.00"))

        executed_receipt = ARService.execute_receipt(receipt, self.executor)
        ARService.write_off(receivable.id, receipt.id, Decimal("80.00"), self.executor)
        self.cash_account.refresh_from_db()
        receivable.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertIsNotNone(executed_receipt.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal("1080.00"))
        self.assertEqual(receivable.status, "PAID")
        self.assertEqual(self.customer.current_balance, Decimal("0.00"))

        payment = APService.create_payment(
            self.supplier,
            Decimal("127.50"),
            timezone.localdate(),
            "BANK_TRANSFER",
            self.creator,
            cash_account=self.cash_account,
        )
        APService.submit_payment(payment, self.creator)
        with self.assertRaises(ValueError):
            APService.approve_payment(payment, self.creator)
        approved_payment = APService.approve_payment(payment, self.approver)
        self.cash_account.refresh_from_db()
        self.assertEqual(approved_payment.status, "APPROVED")
        self.assertIsNone(approved_payment.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal("1080.00"))

        executed_payment = APService.execute_payment(payment, self.executor)
        APService.allocate_payment(
            payment,
            [{"ap_id": ap_account.id, "amount": Decimal("127.50")}],
            self.executor,
        )
        self.cash_account.refresh_from_db()
        ap_account.refresh_from_db()
        self.assertIsNotNone(executed_payment.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal("952.50"))
        self.assertEqual(ap_account.paid_amount, Decimal("127.50"))
        self.assertEqual(ap_account.status, "PAID")

    def test_auto_posting_and_return_reversal_create_vouchers(self):
        purchase_order = self.create_approved_purchase_order(quantity=Decimal("6.000"))
        purchase_receipt = self.complete_purchase_receipt(purchase_order, Decimal("6.000"))
        purchase_voucher = Voucher.objects.get(source_type="PURCHASE_RECEIPT", source_id=purchase_receipt.id)
        self.assertEqual(purchase_voucher.total_debit, Decimal("153.00"))
        self.assertEqual(purchase_voucher.total_credit, Decimal("153.00"))

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)
        outbound_order = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": sales_order.items.get(), "quantity": Decimal("2.000")}],
            self.creator,
        )[0]
        self.approve_and_complete_outbound(outbound_order)
        outbound_voucher = Voucher.objects.get(source_type="OUTBOUND_ORDER", source_id=outbound_order.id)
        self.assertEqual(outbound_voucher.total_debit, Decimal("80.00"))
        self.assertEqual(outbound_voucher.total_credit, Decimal("80.00"))

        receipt = ARService.create_receipt(
            self.customer,
            Decimal("80.00"),
            timezone.localdate(),
            "BANK_TRANSFER",
            self.creator,
            cash_account=self.cash_account,
        )
        ARService.approve_receipt(receipt, self.approver)
        ARService.execute_receipt(receipt, self.executor)
        receipt_voucher = Voucher.objects.get(source_type="AR_RECEIPT", source_id=receipt.id)
        self.assertEqual(receipt_voucher.total_debit, Decimal("80.00"))
        self.assertEqual(receipt_voucher.total_credit, Decimal("80.00"))

        payment = APService.create_payment(
            self.supplier,
            Decimal("100.00"),
            timezone.localdate(),
            "BANK_TRANSFER",
            self.creator,
            cash_account=self.cash_account,
        )
        APService.submit_payment(payment, self.creator)
        APService.approve_payment(payment, self.approver)
        APService.execute_payment(payment, self.executor)
        payment_voucher = Voucher.objects.get(source_type="AP_PAYMENT", source_id=payment.id)
        self.assertEqual(payment_voucher.total_debit, Decimal("100.00"))
        self.assertEqual(payment_voucher.total_credit, Decimal("100.00"))

        sales_return = SalesReturnService.create_order(
            customer=self.customer,
            sales_order=sales_order,
            warehouse=self.warehouse,
            items_data=[{"product": self.product, "quantity": Decimal("1.000")}],
            user=self.creator,
            reason="退货回冲",
        )
        SalesReturnService.approve_order(sales_return, self.approver)
        SalesReturnService.complete_order(sales_return, self.creator)
        sales_return_voucher = Voucher.objects.get(
            source_type="SALES_RETURN_ORDER",
            source_id=sales_return.id,
        )
        self.assertEqual(sales_return_voucher.total_debit, Decimal("40.00"))
        self.assertEqual(sales_return_voucher.total_credit, Decimal("40.00"))

        purchase_return = PurchaseReturnService.create_order(
            supplier=self.supplier,
            purchase_order=purchase_order,
            warehouse=self.warehouse,
            items_data=[{"product": self.product, "quantity": Decimal("1.000")}],
            user=self.creator,
            reason="退供应商",
        )
        PurchaseReturnService.approve_order(purchase_return, self.approver)
        PurchaseReturnService.complete_order(purchase_return, self.creator)
        purchase_return_voucher = Voucher.objects.get(
            source_type="PURCHASE_RETURN_ORDER",
            source_id=purchase_return.id,
        )
        self.assertEqual(purchase_return_voucher.total_debit, Decimal("25.50"))
        self.assertEqual(purchase_return_voucher.total_credit, Decimal("25.50"))

        event_types = set(
            BusinessPostingLog.objects.values_list("event_type", flat=True)
        )
        self.assertTrue(
            {
                PostingService.EVENT_PURCHASE_RECEIPT,
                PostingService.EVENT_SALES_OUTBOUND,
                PostingService.EVENT_RECEIPT_EXECUTED,
                PostingService.EVENT_PAYMENT_EXECUTED,
                PostingService.EVENT_SALES_RETURN,
                PostingService.EVENT_PURCHASE_RETURN,
            }.issubset(event_types)
        )

    def test_cross_module_consistency_baseline(self):
        purchase_order = self.create_approved_purchase_order(quantity=Decimal("8.000"))
        purchase_receipt = self.complete_purchase_receipt(purchase_order, Decimal("8.000"))
        ap_account = APAccount.objects.get(purchase_receipt=purchase_receipt)

        sales_order = SalesOrderService.create_order(
            customer=self.customer,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("3.000"),
                    "unit_price": Decimal("40.00"),
                }
            ],
            user=self.creator,
        )
        SalesOrderService.submit_order(sales_order, self.creator)
        SalesOrderService.approve_order(sales_order, self.approver)
        SalesOrderService.allocate_stock(sales_order, self.creator)
        outbound_order = SalesOrderService.create_outbound_request(
            sales_order,
            [{"order_item": sales_order.items.get(), "quantity": Decimal("3.000")}],
            self.creator,
        )[0]
        self.approve_and_complete_outbound(outbound_order)
        receivable = Receivable.objects.get(outbound_order=outbound_order)

        receipt = ARService.create_receipt(
            self.customer,
            Decimal("120.00"),
            timezone.localdate(),
            "BANK_TRANSFER",
            self.creator,
            cash_account=self.cash_account,
        )
        ARService.approve_receipt(receipt, self.approver)
        ARService.execute_receipt(receipt, self.executor)
        ARService.write_off(receivable.id, receipt.id, Decimal("120.00"), self.executor)

        payment = APService.create_payment(
            self.supplier,
            Decimal("204.00"),
            timezone.localdate(),
            "BANK_TRANSFER",
            self.creator,
            cash_account=self.cash_account,
        )
        APService.submit_payment(payment, self.creator)
        APService.approve_payment(payment, self.approver)
        APService.execute_payment(payment, self.executor)
        APService.allocate_payment(
            payment,
            [{"ap_id": ap_account.id, "amount": Decimal("204.00")}],
            self.executor,
        )

        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        inventory_total = (
            InventoryTransaction.objects.filter(warehouse=self.warehouse, product=self.product)
            .aggregate(total=Sum("quantity"))["total"]
            or Decimal("0.000")
        )
        self.assertEqual(inventory.current_qty, inventory_total)

        self.customer.refresh_from_db()
        open_receivable_total = sum(
            (
                document.balance
                for document in Receivable.objects.filter(customer=self.customer, is_deleted=False)
            ),
            Decimal("0.00"),
        )
        self.assertEqual(self.customer.current_balance, open_receivable_total)

        supplier_open_ap_total = sum(
            (account.balance_amount for account in APAccount.objects.filter(supplier=self.supplier, is_deleted=False)),
            Decimal("0.00"),
        )
        self.assertEqual(supplier_open_ap_total, Decimal("0.00"))
        supplier_summary = APService.get_supplier_summary()
        self.assertEqual(supplier_summary[0]["balance"], Decimal("0.00"))

        self.cash_account.refresh_from_db()
        cash_inflow = (
            CashAccountTransaction.objects.filter(cash_account=self.cash_account, direction="INFLOW")
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        cash_outflow = (
            CashAccountTransaction.objects.filter(cash_account=self.cash_account, direction="OUTFLOW")
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.assertEqual(self.cash_account.current_balance, Decimal("1000.00") + cash_inflow - cash_outflow)

        for source_type, source_id, document_no in [
            ("PURCHASE_RECEIPT", purchase_receipt.id, purchase_receipt.receipt_no),
            ("OUTBOUND_ORDER", outbound_order.id, outbound_order.outbound_no),
            ("AR_RECEIPT", receipt.id, receipt.receipt_no),
            ("AP_PAYMENT", payment.id, payment.payment_no),
        ]:
            voucher = Voucher.objects.get(source_type=source_type, source_id=source_id)
            self.assertEqual(voucher.source_document_no, document_no)
            self.assertTrue(
                BusinessPostingLog.objects.filter(voucher=voucher, business_id=source_id).exists()
            )

    def test_transfer_cancel_rollback_uses_transfer_in_transaction(self):
        other_warehouse = Warehouse.objects.create(
            warehouse_code="E2E-W002",
            warehouse_name="E2E Branch Warehouse",
        )
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("3.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.creator,
            remark="seed stock for transfer cancel",
        )
        transfer = TransferService.create_order(
            self.warehouse,
            other_warehouse,
            [{"product": self.product, "quantity": Decimal("3.000")}],
            self.creator,
        )
        TransferService.submit_order(transfer, self.creator)
        TransferService.approve_order(transfer, self.approver)
        TransferService.start_transfer(transfer, self.creator)
        TransferService.cancel_transfer(transfer, self.creator)

        transfer.refresh_from_db()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        inventory.refresh_from_db()
        txs = InventoryTransaction.objects.filter(
            reference_type="TRANSFER_ORDER",
            reference_id=transfer.id,
        ).order_by("id")

        self.assertEqual(transfer.status, "CANCELLED")
        self.assertIsNotNone(transfer.cancelled_at)
        self.assertEqual(inventory.current_qty, Decimal("3.000"))
        self.assertEqual([tx.transaction_type for tx in txs], ["TRANSFER_OUT", "TRANSFER_IN"])


class ProductCategoryTreeApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="category_tester", password="pass")
        cls.root = ProductCategory.objects.create(name="Root Category", sort=1)
        cls.child = ProductCategory.objects.create(name="Child Category", parent=cls.root, sort=1)
        cls.grandchild = ProductCategory.objects.create(
            name="Grandchild Category",
            parent=cls.child,
            sort=1,
        )
        cls.sibling_root = ProductCategory.objects.create(name="Sibling Root", sort=2)

    def test_tree_endpoint_returns_only_roots_and_no_duplicate_category_ids(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get("/api/inventory/categories/", {"tree": "true"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        root_ids = [item["id"] for item in data]
        all_ids = self._collect_ids(data)

        self.assertEqual(root_ids, [self.root.id, self.sibling_root.id])
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertIn(self.child.id, data[0]["children"][0].values())
        self.assertEqual(data[0]["children"][0]["children"][0]["id"], self.grandchild.id)

    def _collect_ids(self, nodes):
        ids = []
        for node in nodes:
            ids.append(node["id"])
            ids.extend(self._collect_ids(node.get("children", [])))
        return ids


class UnitCodeApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="unit_tester", password="pass")
        CodeRuleService.init_default_rules(created_by=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_unit_generates_code_without_user_input(self):
        response = self.client.post(
            "/api/inventory/units/",
            {"name": "箱", "status": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "箱")
        self.assertEqual(response.data["code"], "UNIT0001")

    def test_create_unit_ignores_user_supplied_code_and_keeps_unique_sequence(self):
        first = self.client.post(
            "/api/inventory/units/",
            {"name": "个", "code": "CUSTOM", "status": True},
            format="json",
        )
        second = self.client.post(
            "/api/inventory/units/",
            {"name": "台", "code": "CUSTOM", "status": True},
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data["code"], "UNIT0001")
        self.assertEqual(second.data["code"], "UNIT0002")

    def test_update_unit_does_not_change_generated_code(self):
        created = self.client.post(
            "/api/inventory/units/",
            {"name": "瓶", "status": True},
            format="json",
        )
        unit_id = created.data["id"]

        updated = self.client.patch(
            f"/api/inventory/units/{unit_id}/",
            {"name": "瓶装", "code": "HACKED"},
            format="json",
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["name"], "瓶装")
        self.assertEqual(updated.data["code"], "UNIT0001")

    def test_delete_unit_in_use_returns_user_friendly_error(self):
        category = ProductCategory.objects.create(name="Unit Delete Category")
        unit = Unit.objects.create(name="斤", code="UNIT-DELETE")
        Product.objects.create(
            product_code="UNIT-DELETE-PRODUCT",
            name="西红柿",
            category=category,
            unit=unit,
            status="ACTIVE",
            created_by=self.user,
        )

        response = self.client.delete(f"/api/inventory/units/{unit.id}/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("无法删除单位", response.data["detail"])
        self.assertIn("西红柿", response.data["detail"])
        self.assertTrue(Unit.objects.filter(id=unit.id).exists())

    def test_init_common_units_creates_default_units_once(self):
        created_units = UnitService.init_common_units()
        first_count = Unit.objects.count()
        second_created_units = UnitService.init_common_units()

        self.assertEqual(len(created_units), len(COMMON_UNIT_NAMES))
        self.assertEqual(first_count, len(COMMON_UNIT_NAMES))
        self.assertEqual(second_created_units, [])
        self.assertEqual(Unit.objects.count(), first_count)
        self.assertTrue(Unit.objects.filter(name="件", code="UNIT0002").exists())
        self.assertTrue(Unit.objects.filter(name="千克").exists())
