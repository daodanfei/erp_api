from django.test import TestCase
from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import Mock, patch
from business_apps.ar_receivable.models import Receivable, Receipt, WriteOff
from business_apps.ar_receivable.services import ARService
from business_apps.crm.models import Customer
from business_apps.crm.services import CustomerCreditService
from business_apps.finance.models import CashAccount
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from core_apps.authentication.models import Permission, Role, User
from business_apps.sales.models import SalesOrder, SalesOrderItem
from business_apps.supply_chain.models import OutboundOrder, OutboundOrderItem

class ARServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.approver = User.objects.create_user(username='approver', password='password')
        self.customer = Customer.objects.create(
            customer_code='C001',
            customer_name='Test Customer',
            status='ACTIVE',
            payment_term='NET_30',
        )
        self.sales_order = SalesOrder.objects.create(order_no='SO001', customer=self.customer, total_amount=1000, status='SHIPPED')
        self.cash_account = CashAccount.objects.create(name='Bank', type='BANK', current_balance=0)
        self.category = ProductCategory.objects.create(name='Category')
        self.unit = Unit.objects.create(name='件', code='PCS')
        self.product = Product.objects.create(
            product_code='P001',
            name='Test Product',
            category=self.category,
            unit=self.unit,
            sale_price=Decimal('40.00'),
            status='ACTIVE',
        )
        self.warehouse = Warehouse.objects.create(warehouse_code='W001', warehouse_name='Main Warehouse')

    def test_generate_ar_from_order(self):
        receivable = ARService.generate_ar_from_order(self.sales_order, self.user)
        self.assertEqual(receivable.amount, 1000)
        self.assertEqual(receivable.status, 'UNPAID')
        self.assertEqual(receivable.balance, 1000)
        self.assertEqual(receivable.source_type, 'SALES_ORDER')
        self.assertEqual(
            receivable.due_date,
            self.sales_order.order_date + timezone.timedelta(days=30),
        )

    def test_generate_ar_due_date_uses_customer_payment_term(self):
        self.customer.payment_term = 'NET_60'
        self.customer.save(update_fields=['payment_term'])
        frozen_now = timezone.datetime(2026, 6, 29, 10, 0, 0, tzinfo=timezone.get_current_timezone())

        with patch('business_apps.ar_receivable.services.timezone.now', return_value=frozen_now):
            receivable = ARService.generate_ar_from_order(self.sales_order, self.user)

        self.assertEqual(
            receivable.due_date,
            CustomerCreditService.calculate_due_date(
                self.customer,
                base_date=self.sales_order.order_date,
            ),
        )

    def test_create_receipt(self):
        receipt = ARService.create_receipt(
            self.customer,
            500,
            timezone.now().date(),
            'BANK_TRANSFER',
            self.user,
            cash_account=self.cash_account,
        )
        self.assertEqual(receipt.amount, 500)
        self.assertEqual(receipt.unwritten_amount, 500)
        self.assertEqual(receipt.status, 'DRAFT')
        self.cash_account.refresh_from_db()
        self.assertEqual(self.cash_account.current_balance, 0)

    def test_create_receipt_rejects_blacklisted_customer(self):
        self.customer.status = 'BLACKLIST'
        self.customer.save(update_fields=['status'])

        with self.assertRaisesRegex(ValueError, '黑名单客户禁止创建收款单'):
            ARService.create_receipt(
                self.customer,
                100,
                timezone.now().date(),
                'BANK_TRANSFER',
                self.user,
            )

    def test_approve_then_execute_receipt_posts_cash_and_blocks_creator(self):
        receipt = ARService.create_receipt(
            self.customer,
            500,
            timezone.now().date(),
            'BANK_TRANSFER',
            self.user,
            cash_account=self.cash_account,
        )

        with self.assertRaises(ValueError):
            ARService.approve_receipt(receipt, self.user)

        approved = ARService.approve_receipt(receipt, self.approver)
        self.assertEqual(approved.status, 'UNWRITTEN')
        self.assertEqual(approved.approved_by, self.approver)
        self.cash_account.refresh_from_db()
        self.assertEqual(self.cash_account.current_balance, 0)

        executed = ARService.execute_receipt(receipt, self.approver)
        self.assertIsNotNone(executed.executed_at)
        self.cash_account.refresh_from_db()
        self.assertEqual(self.cash_account.current_balance, 500)

        with self.assertRaises(ValueError):
            ARService.execute_receipt(receipt, self.approver)

    def test_generate_ar_from_outbound_uses_customer_payment_term(self):
        self.customer.payment_term = 'NET_60'
        self.customer.save(update_fields=['payment_term'])
        completed_at = timezone.datetime(2026, 6, 29, 10, 0, 0, tzinfo=timezone.get_current_timezone())
        outbound = OutboundOrder.objects.create(
            outbound_no='OUT001',
            sales_order=self.sales_order,
            warehouse=self.warehouse,
            status='COMPLETED',
            created_by=self.user,
            completed_at=completed_at,
        )
        OutboundOrderItem.objects.create(
            outbound_order=outbound,
            product=self.product,
            quantity=Decimal('2.000'),
            unit_price=Decimal('40.00'),
            amount=Decimal('80.00'),
        )

        receivable = ARService.generate_ar_from_outbound(outbound, self.user)

        self.assertEqual(receivable.source_type, 'OUTBOUND_ORDER')
        self.assertEqual(receivable.amount, Decimal('80.00'))
        self.assertEqual(
            receivable.due_date,
            CustomerCreditService.calculate_due_date(
                self.customer,
                base_date=completed_at.date(),
            ),
        )

    def test_write_off_supports_prepayment_cross_document_and_partial_settlement(self):
        receivable = ARService.generate_ar_from_order(self.sales_order, self.user)
        second_receivable = Receivable.objects.create(
            receivable_no='AR-MANUAL-002',
            customer=self.customer,
            sales_order=self.sales_order,
            source_type='MANUAL',
            amount=Decimal('200.00'),
            written_off_amount=Decimal('0.00'),
            due_date=timezone.now().date(),
            status='UNPAID',
            created_by=self.user,
        )
        self.customer.current_balance = Decimal('1200.00')
        self.customer.save(update_fields=['current_balance'])

        receipt = ARService.create_receipt(self.customer, 700, timezone.now().date(), 'BANK_TRANSFER', self.user)

        with self.assertRaises(ValueError):
            ARService.write_off(receivable.id, receipt.id, 100, self.user)

        ARService.approve_receipt(receipt, self.approver)
        
        updated_receivable, updated_receipt = ARService.write_off(receivable.id, receipt.id, 500, self.user)
        second_receivable, updated_receipt_2 = ARService.write_off(second_receivable.id, receipt.id, 150, self.user)
        
        self.assertEqual(updated_receivable.written_off_amount, 500)
        self.assertEqual(updated_receivable.balance, 500)
        self.assertEqual(updated_receivable.status, 'PARTIAL_PAID')
        self.assertEqual(second_receivable.written_off_amount, 150)
        self.assertEqual(second_receivable.balance, 50)
        self.assertEqual(second_receivable.status, 'PARTIAL_PAID')
        
        self.assertEqual(updated_receipt_2.unwritten_amount, 50)
        self.assertEqual(updated_receipt_2.status, 'PARTIAL_WRITTEN')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_balance, Decimal('550.00'))

    def test_sales_return_reverse_offsets_existing_receivable(self):
        sales_item = SalesOrderItem.objects.create(
            order=self.sales_order,
            product=self.product,
            warehouse=self.warehouse,
            quantity=Decimal('2.000'),
            unit_price=Decimal('40.00'),
            amount=Decimal('80.00'),
        )
        receivable = Receivable.objects.create(
            receivable_no='AR-RETURN-001',
            customer=self.customer,
            sales_order=self.sales_order,
            source_type='OUTBOUND_ORDER',
            amount=Decimal('80.00'),
            written_off_amount=Decimal('0.00'),
            due_date=timezone.now().date(),
            status='UNPAID',
            created_by=self.user,
        )
        self.customer.current_balance = Decimal('80.00')
        self.customer.save(update_fields=['current_balance'])

        return_item = Mock(product_id=self.product.id, quantity=Decimal('1.000'), product=self.product)
        return_order = Mock(
            sales_order_id=self.sales_order.id,
            customer_id=self.customer.id,
            sales_order=self.sales_order,
            customer=self.customer,
            return_no='SR001',
        )
        return_order.items.all.return_value = [return_item]

        amount = ARService.reverse_ar_for_sales_return(return_order, self.user)

        receivable.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(sales_item.amount, Decimal('80.00'))
        self.assertEqual(amount, Decimal('40.000'))
        self.assertEqual(receivable.amount, Decimal('40.00'))
        self.assertEqual(receivable.status, 'UNPAID')
        self.assertEqual(self.customer.current_balance, Decimal('40.00'))

    def test_sales_return_reverse_creates_red_receivable_when_return_exceeds_open_ar(self):
        SalesOrderItem.objects.create(
            order=self.sales_order,
            product=self.product,
            warehouse=self.warehouse,
            quantity=Decimal('2.000'),
            unit_price=Decimal('40.00'),
            amount=Decimal('80.00'),
        )
        receivable = Receivable.objects.create(
            receivable_no='AR-RETURN-002',
            customer=self.customer,
            sales_order=self.sales_order,
            source_type='OUTBOUND_ORDER',
            amount=Decimal('80.00'),
            written_off_amount=Decimal('0.00'),
            due_date=timezone.now().date(),
            status='UNPAID',
            created_by=self.user,
        )
        self.customer.current_balance = Decimal('80.00')
        self.customer.save(update_fields=['current_balance'])

        return_item = Mock(product_id=self.product.id, quantity=Decimal('3.000'), product=self.product)
        return_order = Mock(
            sales_order_id=self.sales_order.id,
            customer_id=self.customer.id,
            sales_order=self.sales_order,
            customer=self.customer,
            return_no='SR002',
        )
        return_order.items.all.return_value = [return_item]

        amount = ARService.reverse_ar_for_sales_return(return_order, self.user)

        receivable.refresh_from_db()
        red_receivable = Receivable.objects.exclude(id=receivable.id).get()
        self.customer.refresh_from_db()
        self.assertEqual(amount, Decimal('120.000'))
        self.assertEqual(receivable.amount, Decimal('0.00'))
        self.assertEqual(receivable.status, 'PAID')
        self.assertEqual(red_receivable.source_type, 'SALES_RETURN')
        self.assertEqual(red_receivable.amount, Decimal('-40.00'))
        self.assertEqual(red_receivable.status, 'UNPAID')
        self.assertEqual(self.customer.current_balance, Decimal('-40.00'))


class ReceiptApprovalApiTest(APITestCase):
    def setUp(self):
        self.view_permission = Permission.objects.create(name='查看收款单', code='ar:receipt:view', type='BUTTON')
        self.create_permission = Permission.objects.create(name='创建收款单', code='ar:receipt:create', type='BUTTON')
        self.approve_permission = Permission.objects.create(name='审核收款单', code='ar:receipt:approve', type='BUTTON')
        self.execute_permission = Permission.objects.create(name='执行收款单', code='ar:receipt:execute', type='BUTTON')
        self.write_off_permission = Permission.objects.create(name='收款单核销', code='ar:receipt:write_off', type='BUTTON')
        self.creator_role = Role.objects.create(name='收款创建人', code='receipt_creator', data_scope='SELF')
        self.creator_role.permissions.add(self.view_permission, self.create_permission, self.approve_permission)
        self.approver_role = Role.objects.create(name='收款审核员', code='receipt_approver', data_scope='SELF')
        self.approver_role.permissions.add(self.view_permission, self.approve_permission)
        self.executor_role = Role.objects.create(name='收款执行员', code='receipt_executor', data_scope='SELF')
        self.executor_role.permissions.add(self.view_permission, self.execute_permission, self.write_off_permission)

        self.creator = User.objects.create_user(username='creator', password='password')
        self.creator.roles.add(self.creator_role)
        self.approver = User.objects.create_user(username='approver_api', password='password')
        self.approver.roles.add(self.approver_role)
        self.executor = User.objects.create_user(username='executor_api', password='password')
        self.executor.roles.add(self.executor_role)

        self.customer = Customer.objects.create(customer_code='C-API-001', customer_name='API Customer', status='ACTIVE')
        self.cash_account = CashAccount.objects.create(name='API Bank', type='BANK', current_balance=0)

        self.receipt = ARService.create_receipt(
            self.customer,
            500,
            timezone.now().date(),
            'BANK_TRANSFER',
            self.creator,
            cash_account=self.cash_account,
        )

    def test_creator_cannot_approve_own_receipt(self):
        self.client.force_authenticate(self.creator)

        list_response = self.client.get('/api/ar-receivable/receipts/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        rows = list_response.data if isinstance(list_response.data, list) else list_response.data.get('results', [])
        self.assertEqual(rows[0]['can_approve'], False)

        response = self.client.post(f'/api/ar-receivable/receipts/{self.receipt.id}/approve/', format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('创建人', response.data['detail'])

    def test_other_user_with_approve_permission_can_list_and_approve_receipt(self):
        self.client.force_authenticate(self.approver)

        list_response = self.client.get('/api/ar-receivable/receipts/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        rows = list_response.data if isinstance(list_response.data, list) else list_response.data.get('results', [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], self.receipt.id)
        self.assertEqual(rows[0]['can_approve'], True)

        approve_response = self.client.post(f'/api/ar-receivable/receipts/{self.receipt.id}/approve/', format='json')

        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)
        self.receipt.refresh_from_db()
        self.cash_account.refresh_from_db()
        self.assertEqual(self.receipt.status, 'UNWRITTEN')
        self.assertEqual(self.receipt.approved_by, self.approver)
        self.assertEqual(self.cash_account.current_balance, 0)

        post_approve_list = self.client.get('/api/ar-receivable/receipts/')
        self.assertEqual(post_approve_list.status_code, status.HTTP_200_OK)
        post_rows = post_approve_list.data if isinstance(post_approve_list.data, list) else post_approve_list.data.get('results', [])
        self.assertEqual(len(post_rows), 0)

    def test_execute_requires_dedicated_permission_and_executor_can_access_self_scope_workbench(self):
        self.client.force_authenticate(self.approver)
        approve_response = self.client.post(f'/api/ar-receivable/receipts/{self.receipt.id}/approve/', format='json')
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)

        forbidden_execute = self.client.post(f'/api/ar-receivable/receipts/{self.receipt.id}/execute/', format='json')
        self.assertEqual(forbidden_execute.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.executor)
        list_response = self.client.get('/api/ar-receivable/receipts/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        rows = list_response.data if isinstance(list_response.data, list) else list_response.data.get('results', [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], self.receipt.id)
        self.assertEqual(rows[0]['can_execute'], True)

        execute_response = self.client.post(f'/api/ar-receivable/receipts/{self.receipt.id}/execute/', format='json')
        self.assertEqual(execute_response.status_code, status.HTTP_200_OK)
        self.receipt.refresh_from_db()
        self.cash_account.refresh_from_db()
        self.assertIsNotNone(self.receipt.executed_at)
        self.assertEqual(self.cash_account.current_balance, 500)
