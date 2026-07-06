from decimal import Decimal
from django.db.models import Sum, F
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import timedelta
from business_apps.ar_receivable.models import Receivable, Receipt, WriteOff
from business_apps.ap_payable.models import APAccount, APPayment, APAllocation
from .models import CashAccount, FinancialSnapshot

class FinanceStatsService:
    @staticmethod
    def get_dashboard_kpis():
        today = timezone.now().date()
        month_start = today.replace(day=1)
        
        # AR/AP Balances
        total_ar = Receivable.objects.filter(is_deleted=False).exclude(status='PAID').aggregate(
            bal=Sum(F('amount') - F('written_off_amount'))
        )['bal'] or Decimal('0')
        
        total_ap = APAccount.objects.filter(is_deleted=False).exclude(status='PAID').aggregate(
            bal=Sum(F('total_amount') - F('paid_amount'))
        )['bal'] or Decimal('0')
        
        # Cash
        total_cash = CashAccount.objects.filter(status=True).aggregate(total=Sum('current_balance'))['total'] or Decimal('0')
        
        # Daily flow
        today_receipts = Receipt.objects.filter(executed_at__date=today, is_deleted=False).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        today_payments = APPayment.objects.filter(executed_at__date=today).aggregate(total=Sum('payment_amount'))['total'] or Decimal('0')
        
        # Monthly flow
        month_receipts = Receipt.objects.filter(executed_at__date__gte=month_start, is_deleted=False).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        month_payments = APPayment.objects.filter(executed_at__date__gte=month_start).aggregate(total=Sum('payment_amount'))['total'] or Decimal('0')

        return {
            'total_ar': total_ar,
            'total_ap': total_ap,
            'total_cash': total_cash,
            'today_receipts': today_receipts,
            'today_payments': today_payments,
            'month_receipts': month_receipts,
            'month_payments': month_payments,
        }

    @staticmethod
    def get_cash_flow_trend(days=30):
        today = timezone.now().date()
        trend = []
        for i in range(days):
            date = today - timedelta(days=i)
            receipts = Receipt.objects.filter(executed_at__date=date, is_deleted=False).aggregate(total=Sum('amount'))['total'] or 0
            payments = APPayment.objects.filter(executed_at__date=date).aggregate(total=Sum('payment_amount'))['total'] or 0
            trend.append({
                'date': date.strftime('%Y-%m-%d'),
                'inflow': receipts,
                'outflow': payments,
                'net': receipts - payments
            })
        return trend[::-1] # Chronological

    @staticmethod
    def get_aging_summary(type='AR'):
        today = timezone.now().date()
        if type == 'AR':
            qs = Receivable.objects.filter(is_deleted=False).exclude(status='PAID')
            amount_expr = F('amount') - F('written_off_amount')
        else:
            qs = APAccount.objects.filter(is_deleted=False).exclude(status='PAID')
            amount_expr = F('total_amount') - F('paid_amount')

        buckets = {
            '0_30': qs.filter(due_date__gte=today - timedelta(days=30)).aggregate(total=Sum(amount_expr))['total'] or 0,
            '31_60': qs.filter(due_date__lt=today - timedelta(days=30), due_date__gte=today - timedelta(days=60)).aggregate(total=Sum(amount_expr))['total'] or 0,
            '61_90': qs.filter(due_date__lt=today - timedelta(days=60), due_date__gte=today - timedelta(days=90)).aggregate(total=Sum(amount_expr))['total'] or 0,
            '91_plus': qs.filter(due_date__lt=today - timedelta(days=90)).aggregate(total=Sum(amount_expr))['total'] or 0,
        }
        return buckets

class ReconciliationService:
    @staticmethod
    def _parse_date(value, label):
        parsed = parse_date(str(value))
        if not parsed:
            raise ValueError(f"{label}格式错误，请使用 YYYY-MM-DD")
        return parsed

    @staticmethod
    def get_customer_statement(customer_id, start_date, end_date):
        """
        Calculates statement from AR and write-off details:
        Opening + New AR - Write-offs = Closing.
        """
        from business_apps.crm.models import Customer
        start_date = ReconciliationService._parse_date(start_date, "开始日期")
        end_date = ReconciliationService._parse_date(end_date, "结束日期")
        customer = Customer.objects.get(id=customer_id)
        
        old_ar = Receivable.objects.filter(customer_id=customer_id, created_at__date__lt=start_date, is_deleted=False).aggregate(total=Sum('amount'))['total'] or 0
        old_write_offs = WriteOff.objects.filter(receivable__customer_id=customer_id, write_off_date__lt=start_date).aggregate(total=Sum('amount'))['total'] or 0
        opening_balance = old_ar - old_write_offs
        
        period_ar = Receivable.objects.filter(customer_id=customer_id, created_at__date__gte=start_date, created_at__date__lte=end_date, is_deleted=False)
        period_write_offs = WriteOff.objects.filter(receivable__customer_id=customer_id, write_off_date__gte=start_date, write_off_date__lte=end_date)
        
        total_new_ar = period_ar.aggregate(total=Sum('amount'))['total'] or 0
        total_write_offs = period_write_offs.aggregate(total=Sum('amount'))['total'] or 0
        closing_balance = opening_balance + total_new_ar - total_write_offs

        ar_items = [
            {
                'id': row['id'],
                'document_no': row['receivable_no'],
                'document_date': row['created_at'].date(),
                'type': 'AR',
                'type_label': '销售应收',
                'amount': row['amount'],
            }
            for row in period_ar.values('id', 'receivable_no', 'amount', 'created_at')
        ]
        write_off_items = [
            {
                'id': row['id'],
                'document_no': row['receipt__receipt_no'],
                'document_date': row['write_off_date'],
                'type': 'WRITE_OFF',
                'type_label': '收款核销',
                'amount': row['amount'],
            }
            for row in period_write_offs.values('id', 'receipt__receipt_no', 'amount', 'write_off_date')
        ]
        
        items = sorted(ar_items + write_off_items, key=lambda x: (x['document_date'], x['document_no'] or ''))

        return {
            'customer_name': customer.customer_name,
            'opening_balance': opening_balance,
            'new_receivables': total_new_ar,
            'receipts': total_write_offs,
            'closing_balance': closing_balance,
            'items': items,
        }

    @staticmethod
    def get_supplier_statement(supplier_id, start_date, end_date):
        """
        Calculates statement from AP and allocation details:
        Opening + New AP - Payment allocations = Closing.
        """
        from business_apps.supplier.models import Supplier
        start_date = ReconciliationService._parse_date(start_date, "开始日期")
        end_date = ReconciliationService._parse_date(end_date, "结束日期")
        supplier = Supplier.objects.get(id=supplier_id)

        old_ap = APAccount.objects.filter(supplier_id=supplier_id, created_at__date__lt=start_date, is_deleted=False).aggregate(total=Sum('total_amount'))['total'] or 0
        old_allocations = APAllocation.objects.filter(ap_account__supplier_id=supplier_id, created_at__date__lt=start_date).aggregate(total=Sum('amount'))['total'] or 0
        opening_balance = old_ap - old_allocations

        period_ap = APAccount.objects.filter(supplier_id=supplier_id, created_at__date__gte=start_date, created_at__date__lte=end_date, is_deleted=False)
        period_allocations = APAllocation.objects.filter(ap_account__supplier_id=supplier_id, created_at__date__gte=start_date, created_at__date__lte=end_date)

        total_new_ap = period_ap.aggregate(total=Sum('total_amount'))['total'] or 0
        total_allocations = period_allocations.aggregate(total=Sum('amount'))['total'] or 0
        closing_balance = opening_balance + total_new_ap - total_allocations

        ap_items = [
            {
                'id': row['id'],
                'document_no': row['ap_no'],
                'document_date': row['created_at'].date(),
                'type': 'AP',
                'type_label': '采购应付',
                'amount': row['total_amount'],
            }
            for row in period_ap.values('id', 'ap_no', 'total_amount', 'created_at')
        ]
        allocation_items = [
            {
                'id': row['id'],
                'document_no': row['payment__payment_no'],
                'document_date': row['created_at'].date(),
                'type': 'ALLOCATION',
                'type_label': '付款核销',
                'amount': row['amount'],
            }
            for row in period_allocations.values('id', 'payment__payment_no', 'amount', 'created_at')
        ]

        items = sorted(ap_items + allocation_items, key=lambda x: (x['document_date'], x['document_no'] or ''))

        return {
            'supplier_name': supplier.supplier_name,
            'opening_balance': opening_balance,
            'new_payables': total_new_ap,
            'payments': total_allocations,
            'closing_balance': closing_balance,
            'items': items,
        }

class CreditService:
    @staticmethod
    def check_limit(customer, new_order_amount, allow_exception=False):
        from business_apps.crm.services import CustomerCreditService

        return CustomerCreditService.check_limit(
            customer,
            new_order_amount,
            allow_exception=allow_exception,
        )
