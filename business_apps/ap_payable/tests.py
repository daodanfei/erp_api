from django.test import TestCase
from django.utils import timezone
from decimal import Decimal
from unittest.mock import Mock, patch
from rest_framework import status
from rest_framework.test import APITestCase
from business_apps.ap_payable.models import APAccount, APPayment, APAllocation, SupplierCreditNote
from business_apps.ap_payable.services import APService
from business_apps.supplier.models import Supplier
from business_apps.supplier.services import SupplierSettlementService
from business_apps.purchase.models import PurchaseOrder, PurchaseReceipt, PurchaseOrderItem, PurchaseReceiptItem
from business_apps.inventory.models import Product, Warehouse, Unit, ProductCategory
from business_apps.finance.models import CashAccount
from core_apps.authentication.models import User, Permission, Role
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion, SystemInstance
from core_apps.erp_auth.models import ERPPermission, ERPRole
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant
from core_apps.tenant.services import TenantService

from business_apps.platform.models import CodeRule

class APServiceTest(TestCase):
    def setUp(self):
        # Create necessary CodeRules
        CodeRule.objects.create(rule_code='AP_ACCOUNT', prefix='AR', sequence_length=4, reset_type='DAY', status='ACTIVE')
        CodeRule.objects.create(rule_code='AP_PAYMENT', prefix='RC', sequence_length=4, reset_type='DAY', status='ACTIVE')
        CodeRule.objects.create(rule_code='AP_ALLOCATION', prefix='WO', sequence_length=4, reset_type='DAY', status='ACTIVE')

        self.user = User.objects.create_user(username='fin_user', password='password')
        self.approver = User.objects.create_user(username='fin_approver', password='password')
        self.cash_account = CashAccount.objects.create(name='Bank', type='BANK', current_balance=Decimal('2000.00'))
        self.supplier = Supplier.objects.create(
            supplier_code='S001',
            supplier_name='Test Supplier',
            status='ACTIVE',
            payment_term='NET_30',
        )
        self.category = ProductCategory.objects.create(name="Test Cat")
        self.unit = Unit.objects.create(name="Unit", code="PCS")
        self.product = Product.objects.create(
            product_code='P001', name='Test Product', 
            category=self.category, unit=self.unit, cost_price=100
        )
        self.warehouse = Warehouse.objects.create(warehouse_code='W001', warehouse_name='Main')
        
        self.order = PurchaseOrder.objects.create(
            purchase_order_no='PO001', supplier=self.supplier, status='APPROVED'
        )
        self.po_item = PurchaseOrderItem.objects.create(
            purchase_order=self.order, product=self.product, quantity=10, unit_price=100, amount=1000
        )
        self.receipt = PurchaseReceipt.objects.create(
            receipt_no='PR001', purchase_order=self.order, warehouse=self.warehouse, status='COMPLETED'
        )
        self.pr_item = PurchaseReceiptItem.objects.create(
            receipt=self.receipt, purchase_order_item=self.po_item, product=self.product, received_quantity=10
        )

    def test_generate_ap_from_receipt(self):
        ap = APService.generate_ap_from_receipt(self.receipt, self.user)
        self.assertEqual(ap.total_amount, 1000)
        self.assertEqual(ap.status, 'PENDING')
        self.assertEqual(ap.supplier, self.supplier)
        self.assertEqual(ap.source_type, 'PURCHASE_RECEIPT')
        self.assertEqual(ap.source_id, self.receipt.id)
        self.assertEqual(ap.purchase_receipt, self.receipt)
        self.assertEqual(ap.source_document_no_snapshot, 'PR001')
        self.assertEqual(
            ap.due_date,
            self.receipt.created_at.date() + timezone.timedelta(days=30),
        )

    def test_generate_ap_due_date_uses_supplier_payment_term(self):
        self.supplier.payment_term = 'NET_60'
        self.supplier.save(update_fields=['payment_term'])
        frozen_now = timezone.datetime(2026, 6, 29, 9, 0, 0, tzinfo=timezone.get_current_timezone())

        with patch('business_apps.ap_payable.services.timezone.now', return_value=frozen_now):
            ap = APService.generate_ap_from_receipt(self.receipt, self.user)

        self.assertEqual(
            ap.due_date,
            SupplierSettlementService.calculate_due_date(
                self.supplier,
                base_date=self.receipt.created_at.date(),
            ),
        )

    def test_generate_ap_due_date_uses_prepaid_term(self):
        self.supplier.payment_term = 'PREPAID'
        self.supplier.save(update_fields=['payment_term'])
        frozen_now = timezone.datetime(2026, 6, 29, 9, 0, 0, tzinfo=timezone.get_current_timezone())

        with patch('business_apps.ap_payable.services.timezone.now', return_value=frozen_now):
            ap = APService.generate_ap_from_receipt(self.receipt, self.user)

        self.assertEqual(
            ap.due_date,
            SupplierSettlementService.calculate_due_date(
                self.supplier,
                base_date=self.receipt.created_at.date(),
            ),
        )

    def test_payment_approve_then_execute_then_allocate(self):
        ap = APService.generate_ap_from_receipt(self.receipt, self.user)
        payment = APService.create_payment(self.supplier, 1200, timezone.now().date(), 'BANK_TRANSFER', self.user, cash_account=self.cash_account)
        self.cash_account.refresh_from_db()
        self.assertEqual(payment.status, 'DRAFT')
        self.assertEqual(self.cash_account.current_balance, Decimal('2000.00'))

        with self.assertRaises(ValueError):
            APService.allocate_payment(payment, [{'ap_id': ap.id, 'amount': 400}], self.user)

        APService.submit_payment(payment, self.user)
        with self.assertRaises(ValueError):
            APService.approve_payment(payment, self.user)

        APService.approve_payment(payment, self.approver)
        self.cash_account.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'APPROVED')
        self.assertEqual(self.cash_account.current_balance, Decimal('2000.00'))

        APService.execute_payment(payment, self.approver)
        self.cash_account.refresh_from_db()
        payment.refresh_from_db()
        self.assertIsNotNone(payment.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal('800.00'))
        
        # Partially allocate 400
        APService.allocate_payment(payment, [{'ap_id': ap.id, 'amount': 400}], self.user)
        
        ap.refresh_from_db()
        payment.refresh_from_db()
        
        self.assertEqual(ap.paid_amount, 400)
        self.assertEqual(ap.status, 'PARTIAL')
        self.assertEqual(payment.allocated_amount, 400)
        allocation = APAllocation.objects.get(payment=payment, ap_account=ap, amount=Decimal('400.00'))
        self.assertEqual(allocation.allocation_date, timezone.now().date())
        
        # Fully allocate remaining 600
        APService.allocate_payment(payment, [{'ap_id': ap.id, 'amount': 600}], self.user)
        ap.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(ap.paid_amount, 1000)
        self.assertEqual(ap.status, 'PAID')
        self.assertEqual(payment.status, 'APPROVED')

    def test_create_payment_rejects_blacklisted_supplier(self):
        self.supplier.status = 'BLACKLIST'
        self.supplier.save(update_fields=['status'])

        with self.assertRaisesRegex(ValueError, '黑名单供应商禁止创建付款单'):
            APService.create_payment(self.supplier, 100, timezone.now().date(), 'BANK_TRANSFER', self.user)

    def test_over_allocation_prevented(self):
        ap = APService.generate_ap_from_receipt(self.receipt, self.user)
        payment = APService.create_payment(self.supplier, 500, timezone.now().date(), 'BANK_TRANSFER', self.user)
        APService.submit_payment(payment, self.user)
        APService.approve_payment(payment, self.approver)
        APService.execute_payment(payment, self.approver)
        
        with self.assertRaises(ValueError):
            APService.allocate_payment(payment, [{'ap_id': ap.id, 'amount': 600}], self.user)

    def test_allocate_requires_executed_payment_and_reduces_ap_only_after_allocation(self):
        ap = APService.generate_ap_from_receipt(self.receipt, self.user)
        payment = APService.create_payment(
            self.supplier,
            500,
            timezone.now().date(),
            'BANK_TRANSFER',
            self.user,
            cash_account=self.cash_account,
        )
        APService.submit_payment(payment, self.user)
        APService.approve_payment(payment, self.approver)

        with self.assertRaises(ValueError):
            APService.allocate_payment(payment, [{'ap_id': ap.id, 'amount': 200}], self.user)

        self.cash_account.refresh_from_db()
        ap.refresh_from_db()
        self.assertEqual(self.cash_account.current_balance, Decimal('2000.00'))
        self.assertEqual(ap.paid_amount, Decimal('0.00'))

        APService.execute_payment(payment, self.approver)
        self.cash_account.refresh_from_db()
        self.assertEqual(self.cash_account.current_balance, Decimal('1500.00'))

        APService.allocate_payment(payment, [{'ap_id': ap.id, 'amount': 200}], self.user)
        ap.refresh_from_db()
        self.assertEqual(ap.paid_amount, Decimal('200.00'))
        self.assertEqual(ap.status, 'PARTIAL')

    def test_get_supplier_summary_returns_aggregates(self):
        APService.generate_ap_from_receipt(self.receipt, self.user)
        APAccount.objects.create(
            ap_no='AP002',
            supplier=self.supplier,
            source_type='MANUAL',
            source_id=None,
            total_amount=Decimal('500.00'),
            paid_amount=Decimal('100.00'),
            due_date=timezone.now().date(),
            status='PENDING',
            created_by=self.user,
        )

        summary = APService.get_supplier_summary()

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]['supplier__supplier_name'], 'Test Supplier')
        self.assertEqual(summary[0]['total_ap'], Decimal('1500.00'))
        self.assertEqual(summary[0]['total_paid'], Decimal('100.00'))
        self.assertEqual(summary[0]['balance'], Decimal('1400.00'))

    def test_purchase_return_offsets_ap(self):
        ap = APService.generate_ap_from_receipt(self.receipt, self.user)
        return_item = Mock(product_id=self.product.id, quantity=Decimal('2.000'), product=self.product)
        return_order = Mock(
            id=1,
            purchase_order_id=self.order.id,
            supplier_id=self.supplier.id,
            purchase_order=self.order,
            supplier=self.supplier,
            return_no='PRT001',
        )
        return_order.items.all.return_value = [return_item]

        amount = APService.reverse_ap_for_purchase_return(return_order, self.user)

        ap.refresh_from_db()
        self.assertEqual(amount, Decimal('200.000'))
        self.assertEqual(ap.total_amount, Decimal('800.00'))
        self.assertEqual(ap.status, 'PENDING')

    def test_purchase_return_creates_supplier_credit_note_when_return_exceeds_open_ap(self):
        ap = APService.generate_ap_from_receipt(self.receipt, self.user)
        return_item = Mock(product_id=self.product.id, quantity=Decimal('12.000'), product=self.product)
        return_order = Mock(
            id=2,
            purchase_order_id=self.order.id,
            supplier_id=self.supplier.id,
            purchase_order=self.order,
            supplier=self.supplier,
            return_no='PRT002',
        )
        return_order.items.all.return_value = [return_item]

        amount = APService.reverse_ap_for_purchase_return(return_order, self.user)

        ap.refresh_from_db()
        credit_note = SupplierCreditNote.objects.get(supplier=self.supplier)
        self.assertEqual(amount, Decimal('1200.000'))
        self.assertEqual(ap.total_amount, Decimal('0.00'))
        self.assertEqual(ap.status, 'PAID')
        self.assertEqual(credit_note.amount, Decimal('200.00'))
        self.assertEqual(credit_note.source_document_no_snapshot, 'PRT002')
        self.assertEqual(credit_note.status, 'OPEN')

    def test_statistics_returns_actual_values(self):
        APService.generate_ap_from_receipt(self.receipt, self.user)
        payment = APService.create_payment(
            self.supplier,
            300,
            timezone.now().date(),
            'BANK_TRANSFER',
            self.user,
            cash_account=self.cash_account,
        )
        APService.submit_payment(payment, self.user)
        APService.approve_payment(payment, self.approver)
        APService.execute_payment(payment, self.approver)

        stats = APService.get_statistics()

        self.assertEqual(stats['total_accounts'], 1)
        self.assertEqual(stats['total_amount'], Decimal('1000.00'))
        self.assertEqual(stats['total_paid'], Decimal('0.00'))
        self.assertEqual(stats['total_balance'], Decimal('1000.00'))
        self.assertEqual(stats['total_executed_payments'], Decimal('300.00'))
        self.assertEqual(stats['by_status']['PENDING'], 1)
        self.assertEqual(stats['by_supplier'][0]['supplier__supplier_name'], 'Test Supplier')


class APPaymentApiTest(APITestCase):
    @staticmethod
    def _build_config():
        return {
            "basic": {
                "name": "ap_api",
                "industry": "trade",
                "mode": "saas",
            },
            "enabled_modules": ["ap_payable"],
            "module_configs": {
                "ap_payable": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            },
        }

    def setUp(self):
        CodeRule.objects.create(rule_code='AP_ACCOUNT', prefix='AR', sequence_length=4, reset_type='DAY', status='ACTIVE')
        CodeRule.objects.create(rule_code='AP_PAYMENT', prefix='RC', sequence_length=4, reset_type='DAY', status='ACTIVE')
        CodeRule.objects.create(rule_code='AP_ALLOCATION', prefix='WO', sequence_length=4, reset_type='DAY', status='ACTIVE')

        self.platform_user = User.objects.create_user(username='ap_api_owner', password='password')
        self.blueprint = SystemBlueprint.objects.create(
            key='ap_api_bp',
            name='AP API Blueprint',
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version='v1',
            config_json=self._build_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name='AP API Instance',
            mode='SAAS',
            runtime_mode='SAAS',
            status='ACTIVE',
            created_by=self.platform_user,
        )
        self.tenant = Tenant.objects.create(
            code='ap-api-tenant',
            name='AP API Tenant',
            status='ACTIVE',
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.creator = bind_result.initial_admin.user

        self.view_permission, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:view',
            defaults={'name': '查看付款单', 'type': 'BUTTON'},
        )
        self.create_permission, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:create',
            defaults={'name': '创建付款单', 'type': 'BUTTON'},
        )
        self.submit_permission, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:submit',
            defaults={'name': '提交付款单', 'type': 'BUTTON'},
        )
        self.approve_permission, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:approve',
            defaults={'name': '审核付款单', 'type': 'BUTTON'},
        )
        self.execute_permission, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:execute',
            defaults={'name': '执行付款单', 'type': 'BUTTON'},
        )
        self.account_view_permission, _ = ERPPermission.objects.get_or_create(
            code='ap:account:view',
            defaults={'name': '查看应付统计', 'type': 'BUTTON'},
        )

        self.creator_role = ERPRole.objects.create(
            tenant=self.tenant,
            name='应付创建人',
            code='ap_creator',
            data_scope='SELF',
            status=True,
        )
        self.creator_role.permissions.add(
            self.view_permission,
            self.create_permission,
            self.submit_permission,
            self.account_view_permission,
        )
        self.approver_role = ERPRole.objects.create(
            tenant=self.tenant,
            name='应付审核员',
            code='ap_approver',
            data_scope='SELF',
            status=True,
        )
        self.approver_role.permissions.add(self.view_permission, self.approve_permission, self.account_view_permission)
        self.executor_role = ERPRole.objects.create(
            tenant=self.tenant,
            name='应付执行员',
            code='ap_executor',
            data_scope='SELF',
            status=True,
        )
        self.executor_role.permissions.add(self.view_permission, self.execute_permission, self.account_view_permission)

        self.creator.roles.add(self.creator_role)
        self.approver = ERPUser.objects.create_user(tenant=self.tenant, username='ap_approver', password='password')
        self.approver.roles.add(self.approver_role)
        self.executor = ERPUser.objects.create_user(tenant=self.tenant, username='ap_executor', password='password')
        self.executor.roles.add(self.executor_role)

        self.cash_account = CashAccount.objects.create(
            tenant=self.tenant,
            name='API Bank',
            type='BANK',
            current_balance=Decimal('1000.00'),
        )
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code='S-API-001',
            supplier_name='API Supplier',
            status='ACTIVE',
        )
        self.payment = APService.create_payment(
            self.supplier,
            300,
            timezone.now().date(),
            'BANK_TRANSFER',
            self.creator,
            cash_account=self.cash_account,
        )
        APService.submit_payment(self.payment, self.creator)

    def test_approve_and_execute_are_separated_in_api(self):
        self.client.force_authenticate(self.approver)

        approve_response = self.client.post(f'/api/ap-payable/payments/{self.payment.id}/approve/', format='json')
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.cash_account.refresh_from_db()
        self.assertEqual(self.payment.status, 'APPROVED')
        self.assertIsNone(self.payment.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal('1000.00'))

        forbidden_execute = self.client.post(f'/api/ap-payable/payments/{self.payment.id}/execute/', format='json')
        self.assertEqual(forbidden_execute.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.executor)
        list_response = self.client.get('/api/ap-payable/payments/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        rows = list_response.data if isinstance(list_response.data, list) else list_response.data.get('results', [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], self.payment.id)
        self.assertEqual(rows[0]['can_execute'], True)

        execute_response = self.client.post(f'/api/ap-payable/payments/{self.payment.id}/execute/', format='json')
        self.assertEqual(execute_response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.cash_account.refresh_from_db()
        self.assertIsNotNone(self.payment.executed_at)
        self.assertEqual(self.cash_account.current_balance, Decimal('700.00'))

    def test_statistics_endpoint_returns_real_values(self):
        ap = APAccount.objects.create(
            ap_no='AP-API-001',
            supplier=self.supplier,
            source_type='MANUAL',
            source_document_no_snapshot='MANUAL-001',
            total_amount=Decimal('500.00'),
            paid_amount=Decimal('100.00'),
            due_date=timezone.now().date(),
            status='PARTIAL',
            created_by=self.approver,
        )
        self.client.force_authenticate(self.approver)
        response = self.client.get('/api/ap-payable/accounts/statistics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_accounts'], 1)
        self.assertEqual(Decimal(str(response.data['total_amount'])), Decimal('500.00'))
        self.assertEqual(Decimal(str(response.data['total_paid'])), Decimal('100.00'))
        self.assertEqual(Decimal(str(response.data['total_balance'])), Decimal('400.00'))
        self.assertEqual(response.data['by_status']['PARTIAL'], 1)
        self.assertEqual(response.data['by_supplier'][0]['supplier__supplier_name'], ap.supplier.supplier_name)


class APPaymentTenantScopeApiTest(APITestCase):
    @staticmethod
    def _build_config():
        return {
            "basic": {
                "name": "ap_payment_scope",
                "industry": "trade",
                "mode": "saas",
            },
            "enabled_modules": ["ap_payable"],
            "module_configs": {
                "ap_payable": {"features": {}, "workflows": {}, "field_rules": {}, "defaults": {}},
            },
        }

    def setUp(self):
        CodeRule.objects.create(rule_code='AP_PAYMENT', prefix='RC', sequence_length=4, reset_type='DAY', status='ACTIVE')

        self.platform_user = User.objects.create_user(username='ap_scope_owner', password='password')
        self.blueprint = SystemBlueprint.objects.create(
            key='ap_scope_bp',
            name='AP Scope Blueprint',
            created_by=self.platform_user,
        )
        self.version = SystemBlueprintVersion.objects.create(
            blueprint=self.blueprint,
            version='v1',
            config_json=self._build_config(),
            created_by=self.platform_user,
            is_published=True,
        )
        self.instance = SystemInstance.objects.create(
            blueprint=self.blueprint,
            blueprint_version=self.version,
            name='AP Scope Instance',
            mode='SAAS',
            runtime_mode='SAAS',
            status='ACTIVE',
            created_by=self.platform_user,
        )

        self.tenant = Tenant.objects.create(
            code='ap-scope-tenant',
            name='AP Scope Tenant',
            status='ACTIVE',
            instance=self.instance,
        )
        bind_result = TenantService.bind_instance_to_tenant(
            tenant=self.tenant,
            instance=self.instance,
            blueprint_version=self.version,
        )
        self.erp_user = bind_result.initial_admin.user

        payment_view, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:view',
            defaults={'name': '查看付款单', 'type': 'BUTTON'},
        )
        payment_create, _ = ERPPermission.objects.get_or_create(
            code='ap:payment:create',
            defaults={'name': '创建付款单', 'type': 'BUTTON'},
        )
        role = ERPRole.objects.create(
            tenant=self.tenant,
            name='AP Payment Operator',
            code='ap_payment_operator',
            data_scope='SELF',
            status=True,
        )
        role.permissions.add(payment_view, payment_create)
        self.erp_user.roles.add(role)
        self.client.force_authenticate(self.erp_user)

        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code='SUP-AP-SCOPE-001',
            supplier_name='Tenant Supplier',
            status='ACTIVE',
            payment_term='NET_30',
            created_by=self.erp_user,
        )

        self.other_tenant = Tenant.objects.create(
            code='ap-scope-other',
            name='AP Scope Other',
            status='ACTIVE',
            instance=self.instance,
        )
        self.other_supplier = Supplier.objects.create(
            tenant=self.other_tenant,
            supplier_code='SUP-AP-SCOPE-002',
            supplier_name='Other Tenant Supplier',
            status='ACTIVE',
            payment_term='NET_30',
        )

    def test_created_payment_is_listed_in_current_tenant(self):
        create_response = self.client.post(
            '/api/ap-payable/payments/',
            {
                'supplier': self.supplier.id,
                'payment_amount': '120.00',
                'payment_date': timezone.now().date().isoformat(),
                'payment_method': 'BANK_TRANSFER',
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['tenant'], self.tenant.id)

        list_response = self.client.get('/api/ap-payable/payments/')

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        rows = list_response.data if isinstance(list_response.data, list) else list_response.data.get('results', [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], create_response.data['id'])
        self.assertEqual(rows[0]['tenant'], self.tenant.id)

    def test_create_rejects_cross_tenant_supplier(self):
        response = self.client.post(
            '/api/ap-payable/payments/',
            {
                'supplier': self.other_supplier.id,
                'payment_amount': '88.00',
                'payment_date': timezone.now().date().isoformat(),
                'payment_method': 'BANK_TRANSFER',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('当前租户', response.data['detail'])
