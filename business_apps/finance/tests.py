from django.test import TestCase
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from business_apps.crm.services import CustomerCreditService
from business_apps.finance.services import CreditService, FinanceStatsService, ReconciliationService
from business_apps.crm.models import Customer
from business_apps.supplier.models import Supplier
from business_apps.ar_receivable.models import Receivable, Receipt, WriteOff
from business_apps.ap_payable.models import APAccount, APPayment, APAllocation
from business_apps.finance.models import CashAccount, CashAccountTransaction
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.authentication.models import Permission, Role, User
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser


def build_finance_config(*, multi_cash_account=True, reconciliation_enabled=True, cash_flow_analysis_enabled=True):
    return {
        "basic": {"name": "finance_policy", "industry": "trade", "mode": "saas"},
        "enabled_modules": ["finance"],
        "module_configs": {
            "finance": {
                "features": {
                    "multi_cash_account": multi_cash_account,
                    "reconciliation_enabled": reconciliation_enabled,
                    "opening_balance_editable": False,
                    "cash_flow_analysis_enabled": cash_flow_analysis_enabled,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {"default_currency": "CNY"},
            }
        },
    }

class CreditServiceTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            customer_code='C001', 
            customer_name='Credit Test',
            credit_limit=1000,
            current_balance=800,
            credit_control_mode='BLOCK',
        )

    def test_credit_check_pass(self):
        allowed, msg = CreditService.check_limit(self.customer, 150)
        self.assertTrue(allowed)
        self.assertIsNone(msg)

    def test_credit_check_fail(self):
        allowed, msg = CreditService.check_limit(self.customer, 250)
        self.assertFalse(allowed)
        self.assertIn("超过信用额度", msg)

    def test_unlimited_credit(self):
        self.customer.credit_limit = 0
        self.customer.save()
        allowed, msg = CreditService.check_limit(self.customer, 999999)
        self.assertTrue(allowed)

    def test_credit_check_blocks_by_mode(self):
        allowed, msg = CustomerCreditService.check_limit(self.customer, 250)
        self.assertFalse(allowed)
        self.assertIn("超过信用额度", msg)

    def test_credit_check_allows_exception_override(self):
        allowed, msg = CustomerCreditService.check_limit(self.customer, 250, allow_exception=True)
        self.assertTrue(allowed)
        self.assertIn("例外放行", msg)

    def test_credit_check_warn_mode_does_not_block(self):
        self.customer.credit_control_mode = 'WARN'
        self.customer.save(update_fields=['credit_control_mode'])

        allowed, msg = CustomerCreditService.check_limit(self.customer, 250)
        self.assertTrue(allowed)
        self.assertIn("超过信用额度", msg)


class ReconciliationServiceTest(TestCase):
    def setUp(self):
        today = timezone.now().date()
        self.start_date = today.strftime('%Y-%m-%d')
        self.end_date = today.strftime('%Y-%m-%d')
        self.customer = Customer.objects.create(
            customer_code='C-STMT',
            customer_name='Statement Customer',
        )
        self.supplier = Supplier.objects.create(
            supplier_code='S-STMT',
            supplier_name='Statement Supplier',
        )

    def test_customer_statement_uses_write_off_details_not_receipt_total(self):
        receivable = Receivable.objects.create(
            receivable_no='AR-STMT-001',
            customer=self.customer,
            amount=Decimal('1000.00'),
            written_off_amount=Decimal('300.00'),
            due_date=timezone.now().date(),
            status='PARTIAL_PAID',
        )
        receipt = Receipt.objects.create(
            receipt_no='RC-STMT-001',
            customer=self.customer,
            amount=Decimal('800.00'),
            unwritten_amount=Decimal('500.00'),
            receipt_date=timezone.now().date(),
            status='PARTIAL_WRITTEN',
        )
        WriteOff.objects.create(
            write_off_no='WO-STMT-001',
            receivable=receivable,
            receipt=receipt,
            amount=Decimal('300.00'),
        )

        statement = ReconciliationService.get_customer_statement(
            self.customer.id,
            self.start_date,
            self.end_date,
        )

        self.assertEqual(statement['new_receivables'], Decimal('1000.00'))
        self.assertEqual(statement['receipts'], Decimal('300.00'))
        self.assertEqual(statement['closing_balance'], Decimal('700.00'))
        self.assertCountEqual([item['type'] for item in statement['items']], ['AR', 'WRITE_OFF'])

    def test_supplier_statement_uses_allocation_details_not_payment_total(self):
        ap_account = APAccount.objects.create(
            ap_no='AP-STMT-001',
            supplier=self.supplier,
            source_type='PURCHASE_RECEIPT',
            total_amount=Decimal('1200.00'),
            paid_amount=Decimal('400.00'),
            due_date=timezone.now().date(),
            status='PARTIAL',
        )
        payment = APPayment.objects.create(
            payment_no='PAY-STMT-001',
            supplier=self.supplier,
            payment_date=timezone.now().date(),
            payment_amount=Decimal('900.00'),
            allocated_amount=Decimal('400.00'),
            status='APPROVED',
        )
        APAllocation.objects.create(
            allocation_no='ALLOC-STMT-001',
            ap_account=ap_account,
            payment=payment,
            amount=Decimal('400.00'),
        )

        statement = ReconciliationService.get_supplier_statement(
            self.supplier.id,
            self.start_date,
            self.end_date,
        )

        self.assertEqual(statement['new_payables'], Decimal('1200.00'))
        self.assertEqual(statement['payments'], Decimal('400.00'))
        self.assertEqual(statement['closing_balance'], Decimal('800.00'))
        self.assertCountEqual([item['type'] for item in statement['items']], ['AP', 'ALLOCATION'])


class FinanceStatsServiceTest(TestCase):
    def test_dashboard_uses_executed_payment_date_for_cash_outflow(self):
        supplier = Supplier.objects.create(
            supplier_code='S-KPI',
            supplier_name='KPI Supplier',
        )
        today = timezone.now().date()
        APPayment.objects.create(
            payment_no='PAY-KPI-001',
            supplier=supplier,
            payment_date=today,
            payment_amount=Decimal('500.00'),
            allocated_amount=Decimal('0.00'),
            status='APPROVED',
        )
        APPayment.objects.create(
            payment_no='PAY-KPI-002',
            supplier=supplier,
            payment_date=today,
            payment_amount=Decimal('700.00'),
            allocated_amount=Decimal('0.00'),
            status='APPROVED',
            executed_at=timezone.now(),
        )

        kpis = FinanceStatsService.get_dashboard_kpis()

        self.assertEqual(kpis['today_payments'], Decimal('700.00'))

    def test_cash_account_transaction_keeps_balance_cache_consistent(self):
        user = User.objects.create_user(username='cash_user', password='password')
        account = CashAccount.objects.create(
            name='Main Bank',
            type='BANK',
            account_type='BANK',
            current_balance=Decimal('0.00'),
            opening_balance_date=timezone.now().date(),
        )

        CashAccountTransaction.record_change(
            cash_account=account,
            direction='INFLOW',
            amount=Decimal('1000.00'),
            source_type='OPENING_BALANCE',
            source_document_no_snapshot='OPEN-001',
            transaction_date=timezone.now().date(),
            operator=user,
        )
        CashAccountTransaction.record_change(
            cash_account=account,
            direction='OUTFLOW',
            amount=Decimal('250.00'),
            source_type='MANUAL',
            source_document_no_snapshot='ADJ-001',
            transaction_date=timezone.now().date(),
            operator=user,
        )

        account.refresh_from_db()
        inflow = CashAccountTransaction.objects.filter(cash_account=account, direction='INFLOW').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        outflow = CashAccountTransaction.objects.filter(cash_account=account, direction='OUTFLOW').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        self.assertEqual(account.current_balance, inflow - outflow)
        self.assertEqual(account.current_balance, Decimal('750.00'))


class FinanceApiPermissionTest(APITestCase):
    def setUp(self):
        self.dashboard_permission = Permission.objects.create(name='财务看板', code='finance:dashboard:view', type='BUTTON')
        self.aging_permission = Permission.objects.create(name='账龄分析', code='finance:aging:view', type='BUTTON')
        self.customer_recon_permission = Permission.objects.create(name='客户对账', code='finance:reconciliation:customer:view', type='BUTTON')
        self.supplier_recon_permission = Permission.objects.create(name='供应商对账', code='finance:reconciliation:supplier:view', type='BUTTON')
        self.cash_view_permission = Permission.objects.create(name='资金账户查看', code='finance:cash:view', type='BUTTON')
        self.cash_create_permission = Permission.objects.create(name='资金账户创建', code='finance:cash:create', type='BUTTON')
        self.cash_update_permission = Permission.objects.create(name='资金账户维护', code='finance:cash:update', type='BUTTON')

        self.role = Role.objects.create(name='finance_viewer', code='finance_viewer', data_scope='ALL')
        self.user = User.objects.create_user(username='finance_api_user', password='password')
        self.user.roles.add(self.role)
        self.no_permission_user = User.objects.create_user(username='finance_no_perm', password='password')

        self.customer = Customer.objects.create(customer_code='C-FIN-001', customer_name='Finance Customer')
        self.supplier = Supplier.objects.create(supplier_code='S-FIN-001', supplier_name='Finance Supplier')
        self.account = CashAccount.objects.create(
            name='Finance Bank',
            type='BANK',
            account_type='BANK',
            current_balance=Decimal('0.00'),
            opening_balance_date=timezone.now().date(),
        )
        CashAccountTransaction.record_change(
            cash_account=self.account,
            direction='INFLOW',
            amount=Decimal('300.00'),
            source_type='OPENING_BALANCE',
            source_document_no_snapshot='OPEN-FIN-001',
            transaction_date=timezone.now().date(),
        )

    def _apply_runtime_config(self, user, config):
        blueprint = SystemBlueprint.objects.create(key=f"finance-bp-{Tenant.objects.count()}", name="Finance Policy", created_by=user)
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=user,
        )
        tenant = Tenant.objects.create(code=f"finance-tenant-{Tenant.objects.count()}", name="Finance Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(tenant=tenant, blueprint_version=version, config_json=config)
        return tenant

    def test_finance_endpoints_require_granular_permissions(self):
        self.client.force_authenticate(self.user)

        dashboard_response = self.client.get('/api/finance/dashboard/')
        self.assertEqual(dashboard_response.status_code, status.HTTP_403_FORBIDDEN)

        self.role.permissions.add(self.dashboard_permission)
        dashboard_response = self.client.get('/api/finance/dashboard/')
        self.assertEqual(dashboard_response.status_code, status.HTTP_200_OK)

        aging_response = self.client.get('/api/finance/aging/')
        self.assertEqual(aging_response.status_code, status.HTTP_403_FORBIDDEN)
        self.role.permissions.add(self.aging_permission)
        aging_response = self.client.get('/api/finance/aging/')
        self.assertEqual(aging_response.status_code, status.HTTP_200_OK)

        customer_recon = self.client.get(
            f'/api/finance/reconciliation/customer/{self.customer.id}/',
            {'start_date': timezone.now().date().isoformat(), 'end_date': timezone.now().date().isoformat()},
        )
        self.assertEqual(customer_recon.status_code, status.HTTP_403_FORBIDDEN)
        self.role.permissions.add(self.customer_recon_permission)
        customer_recon = self.client.get(
            f'/api/finance/reconciliation/customer/{self.customer.id}/',
            {'start_date': timezone.now().date().isoformat(), 'end_date': timezone.now().date().isoformat()},
        )
        self.assertEqual(customer_recon.status_code, status.HTTP_200_OK)

        supplier_recon = self.client.get(
            f'/api/finance/reconciliation/supplier/{self.supplier.id}/',
            {'start_date': timezone.now().date().isoformat(), 'end_date': timezone.now().date().isoformat()},
        )
        self.assertEqual(supplier_recon.status_code, status.HTTP_403_FORBIDDEN)
        self.role.permissions.add(self.supplier_recon_permission)
        supplier_recon = self.client.get(
            f'/api/finance/reconciliation/supplier/{self.supplier.id}/',
            {'start_date': timezone.now().date().isoformat(), 'end_date': timezone.now().date().isoformat()},
        )
        self.assertEqual(supplier_recon.status_code, status.HTTP_200_OK)

    def test_cash_account_transactions_endpoint_respects_permission(self):
        self.client.force_authenticate(self.user)

        forbidden = self.client.get(f'/api/finance/cash-accounts/{self.account.id}/transactions/')
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.role.permissions.add(self.cash_view_permission)
        allowed = self.client.get(f'/api/finance/cash-accounts/{self.account.id}/transactions/')
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(len(allowed.data), 1)
        self.assertEqual(Decimal(str(allowed.data[0]['balance_after'])), Decimal('300.00'))

    def test_cash_account_crud_requires_dedicated_finance_role_permissions(self):
        self.client.force_authenticate(self.user)

        create_response = self.client.post(
            '/api/finance/cash-accounts/',
            {
                'name': 'Ops Bank',
                'type': 'BANK',
                'account_type': 'BANK',
                'opening_balance_date': timezone.now().date().isoformat(),
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

        self.role.permissions.add(self.cash_create_permission)
        create_response = self.client.post(
            '/api/finance/cash-accounts/',
            {
                'name': 'Ops Bank',
                'type': 'BANK',
                'account_type': 'BANK',
                'opening_balance_date': timezone.now().date().isoformat(),
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        account_id = create_response.data['id']
        update_response = self.client.patch(
            f'/api/finance/cash-accounts/{account_id}/',
            {'remark': 'updated by finance role'},
            format='json',
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

        self.role.permissions.add(self.cash_update_permission)
        update_response = self.client.patch(
            f'/api/finance/cash-accounts/{account_id}/',
            {'remark': 'updated by finance role'},
            format='json',
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

    def test_user_without_finance_permissions_cannot_view_financial_data(self):
        self.client.force_authenticate(self.no_permission_user)

        self.assertEqual(self.client.get('/api/finance/dashboard/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/finance/cash-accounts/').status_code, status.HTTP_403_FORBIDDEN)

    def test_reconciliation_endpoint_is_blocked_when_policy_disabled(self):
        self._apply_runtime_config(self.user, build_finance_config(reconciliation_enabled=False))
        self.role.permissions.add(self.customer_recon_permission)
        self.client.force_authenticate(self.user)

        response = self.client.get(
            f'/api/finance/reconciliation/customer/{self.customer.id}/',
            {'start_date': timezone.now().date().isoformat(), 'end_date': timezone.now().date().isoformat()},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_single_cash_account_policy_blocks_second_account_creation(self):
        self._apply_runtime_config(self.user, build_finance_config(multi_cash_account=False))
        self.role.permissions.add(self.cash_create_permission)
        self.client.force_authenticate(self.user)

        response = self.client.post(
            '/api/finance/cash-accounts/',
            {
                'name': 'Second Bank',
                'type': 'BANK',
                'account_type': 'BANK',
                'opening_balance_date': timezone.now().date().isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
