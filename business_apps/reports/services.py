from decimal import Decimal
from datetime import timedelta, datetime
from django.db.models import Sum, Count, Avg, F, Q, Value, DecimalField, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncDate, TruncMonth, TruncWeek, TruncQuarter, TruncYear
from django.utils import timezone
from django.core.cache import cache
import functools
from core_apps.common.authz import has_erp_full_data_scope
from core_apps.common.viewsets import apply_erp_tenant_scope


def _cache_report(prefix, timeout=300):
    """报表缓存装饰器：5分钟缓存"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 构建缓存key：prefix + 函数参数
            user = args[0] if args else None
            user_id = user.id if hasattr(user, 'id') else 0
            key_parts = [prefix, str(user_id)]
            for v in args[1:]:
                key_parts.append(str(v))
            for k, v in sorted(kwargs.items()):
                key_parts.append(f"{k}={v}")
            cache_key = ':'.join(key_parts)

            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result
        return wrapper
    return decorator


def _aware_datetime(date_value, end=False):
    """把日期转换成当前时区下的 datetime。"""
    time_value = datetime.max.time() if end else datetime.min.time()
    return timezone.make_aware(datetime.combine(date_value, time_value), timezone.get_current_timezone())


def _get_date_range(period, start_date=None, end_date=None):
    """根据时间维度返回 (start, end) datetime"""
    now = timezone.now()
    today = now.date()

    if start_date and end_date:
        return _aware_datetime(start_date), _aware_datetime(end_date, end=True)

    if period == 'today':
        return _aware_datetime(today), _aware_datetime(today, end=True)
    elif period == 'yesterday':
        yesterday = today - timedelta(days=1)
        return _aware_datetime(yesterday), _aware_datetime(yesterday, end=True)
    elif period == 'week':
        start = today - timedelta(days=today.weekday())
        return _aware_datetime(start), now
    elif period == 'month':
        start = today.replace(day=1)
        return _aware_datetime(start), now
    elif period == 'quarter':
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=quarter_start_month, day=1)
        return _aware_datetime(start), now
    elif period == 'year':
        start = today.replace(month=1, day=1)
        return _aware_datetime(start), now
    else:
        # default month
        start = today.replace(day=1)
        return _aware_datetime(start), now


def _apply_dept_filter(qs, user, dept_field='created_by__dept'):
    """根据用户数据权限过滤查询集"""
    role = user.roles.first()
    if not role:
        return qs.filter(**{dept_field: user.dept_id}) if user.dept_id else qs.none()
    if has_erp_full_data_scope(user) or role.data_scope == 'ALL':
        return qs
    elif role.data_scope == 'DEPARTMENT':
        return qs.filter(**{dept_field: user.dept_id}) if user.dept_id else qs.none()
    else:  # SELF
        return qs.filter(created_by=user)


def _tenant_qs(qs, user):
    return apply_erp_tenant_scope(qs, user=user)


def _tenant_and_dept_qs(qs, user, dept_field='created_by__dept'):
    return _apply_dept_filter(_tenant_qs(qs, user), user, dept_field)


class DashboardService:
    """经营驾驶舱"""

    @staticmethod
    def get_kpi(user):
        """KPI卡片数据"""
        cache_key = f'dashboard:kpi:{user.id}:{timezone.now().date()}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        today = timezone.now().date()
        month_start = today.replace(day=1)
        today_start = _aware_datetime(today)
        today_end = _aware_datetime(today, end=True)
        month_start_dt = _aware_datetime(month_start)

        from business_apps.sales.models import SalesOrder
        from business_apps.purchase.models import PurchaseOrder
        from business_apps.inventory.models import Product, Inventory
        from business_apps.crm.models import Customer
        from business_apps.supplier.models import Supplier

        # 销售额
        sales_today = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
            created_at__range=(today_start, today_end),
        ).aggregate(total=Coalesce(Sum('total_amount'), Decimal(0)))['total']

        sales_month = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
            created_at__range=(month_start_dt, today_end),
        ).aggregate(total=Coalesce(Sum('total_amount'), Decimal(0)))['total']

        # 采购额
        purchase_today = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
            created_at__range=(today_start, today_end),
        ).aggregate(total=Coalesce(Sum('total_amount'), Decimal(0)))['total']

        purchase_month = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
            created_at__range=(month_start_dt, today_end),
        ).aggregate(total=Coalesce(Sum('total_amount'), Decimal(0)))['total']

        # 库存总价值（聚合查询替代Python循环）
        inv_value = _tenant_qs(Inventory.objects.select_related('product'), user).aggregate(
            total_value=Coalesce(Sum(F('current_qty') * F('product__cost_price'), output_field=DecimalField()), Decimal(0))
        )['total_value']

        # 缺货/低库存统计（聚合查询）
        out_of_stock = _tenant_qs(Inventory.objects.all(), user).filter(current_qty=0).count()
        low_stock = _tenant_qs(Inventory.objects.all(), user).filter(
            current_qty__gt=0, current_qty__lt=F('product__min_stock')
        ).count()

        # 统计数量
        customer_count = _tenant_qs(Customer.objects.all(), user).filter(is_deleted=False).count()
        supplier_count = _tenant_qs(Supplier.objects.all(), user).filter(is_deleted=False).count()
        product_count = _tenant_qs(Product.objects.all(), user).filter(is_deleted=False).count()

        data = {
            'sales_today': str(sales_today),
            'sales_month': str(sales_month),
            'purchase_today': str(purchase_today),
            'purchase_month': str(purchase_month),
            'inventory_value': str(inv_value),
            'customer_count': customer_count,
            'supplier_count': supplier_count,
            'product_count': product_count,
        }
        cache.set(cache_key, data, 300)  # 5分钟缓存
        return data

    @staticmethod
    def get_sales_trend(user, days=30):
        """销售趋势"""
        from business_apps.sales.models import SalesOrder

        end = timezone.now()
        start = end - timedelta(days=days)

        qs = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
            created_at__range=(start, end),
        )

        daily = qs.annotate(date=TruncDate('created_at')).values('date').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            order_count=Count('id'),
        ).order_by('date')

        return [{'date': d['date'].isoformat() if d['date'] else '', 'amount': str(d['total_amount']), 'count': d['order_count']} for d in daily]

    @staticmethod
    def get_purchase_trend(user, days=30):
        """采购趋势"""
        from business_apps.purchase.models import PurchaseOrder

        end = timezone.now()
        start = end - timedelta(days=days)

        qs = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
            created_at__range=(start, end),
        )

        daily = qs.annotate(date=TruncDate('created_at')).values('date').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            order_count=Count('id'),
        ).order_by('date')

        return [{'date': d['date'].isoformat() if d['date'] else '', 'amount': str(d['total_amount']), 'count': d['order_count']} for d in daily]

    @staticmethod
    def get_inventory_overview(user):
        """库存概览"""
        from business_apps.inventory.models import Inventory

        inventories = _tenant_qs(Inventory.objects.select_related('product'), user)

        sku_count = inventories.count()
        agg = inventories.aggregate(
            total_qty=Coalesce(Sum('current_qty'), Decimal(0)),
            total_value=Coalesce(Sum(F('current_qty') * F('product__cost_price'), output_field=DecimalField()), Decimal(0)),
        )
        out_of_stock = _tenant_qs(Inventory.objects.all(), user).filter(current_qty=0).count()
        low_stock = _tenant_qs(Inventory.objects.all(), user).filter(
            current_qty__gt=0, current_qty__lt=F('product__min_stock')
        ).count()

        return {
            'sku_count': sku_count,
            'total_qty': str(agg['total_qty']),
            'total_value': str(agg['total_value']),
            'out_of_stock': out_of_stock,
            'low_stock': low_stock,
        }

    @staticmethod
    def get_top10(user):
        """Top10排行榜"""
        from business_apps.sales.models import SalesOrderItem
        from business_apps.sales.models import SalesOrder
        from business_apps.purchase.models import PurchaseOrderItem, PurchaseOrder

        # 销售额Top10商品
        valid_sales = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED']
        )
        product_top10 = SalesOrderItem.objects.filter(
            order__in=valid_sales
        ).values('product__name', 'product__product_code').annotate(
            total_amount=Coalesce(Sum('amount'), Decimal(0)),
        ).order_by('-total_amount')[:10]

        # 销售额Top10客户
        customer_top10 = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED']
        ).values('customer__customer_name').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
        ).order_by('-total_amount')[:10]

        # 采购额Top10供应商
        valid_purchase = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED']
        )
        supplier_top10 = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED']
        ).values('supplier__supplier_name').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
        ).order_by('-total_amount')[:10]

        return {
            'product_top10': [{'name': p['product__name'], 'code': p['product__product_code'], 'amount': str(p['total_amount'])} for p in product_top10],
            'customer_top10': [{'name': c['customer__customer_name'], 'amount': str(c['total_amount'])} for c in customer_top10],
            'supplier_top10': [{'name': s['supplier__supplier_name'], 'amount': str(s['total_amount'])} for s in supplier_top10],
        }


class SalesReportService:
    """销售分析"""

    @staticmethod
    def get_drill_orders(user, period='month', start_date=None, end_date=None,
                         product_id=None, customer_id=None, supplier_id=None):
        """钻取：从汇总/排行点击进入订单明细列表"""
        from business_apps.sales.models import SalesOrder, SalesOrderItem

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_and_dept_qs(
            SalesOrder.objects.filter(
                status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
                created_at__range=(start, end),
            ).select_related('customer', 'created_by'), user
        )

        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if product_id:
            qs = qs.filter(items__product_id=product_id).distinct()

        return qs.order_by('-created_at')[:100]

    @staticmethod
    @_cache_report('rpt:sales:summary')
    def get_summary(user, period='month', start_date=None, end_date=None):
        from business_apps.sales.models import SalesOrder
        from business_apps.supply_chain.models import SalesReturnOrder, SalesReturnOrderItem

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_and_dept_qs(
            SalesOrder.objects.filter(
                status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
                created_at__range=(start, end),
            ), user
        )

        agg = qs.aggregate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            total_quantity=Coalesce(Sum('total_quantity'), Decimal(0)),
            order_count=Count('id'),
        )
        avg_amount = agg['total_amount'] / agg['order_count'] if agg['order_count'] > 0 else Decimal(0)

        # 退货统计
        return_qs = _tenant_qs(SalesReturnOrder.objects.all(), user).filter(
            status='COMPLETED', completed_at__range=(start, end)
        )
        return_items = SalesReturnOrderItem.objects.filter(return_order__in=return_qs)
        return_amount = Decimal(0)
        for item in return_items:
            return_amount += item.quantity * (item.product.sale_price or Decimal(0))

        return_qty = return_items.aggregate(total=Coalesce(Sum('quantity'), Decimal(0)))['total']
        return_rate = (return_qty / agg['total_quantity'] * 100) if agg['total_quantity'] > 0 else Decimal(0)

        return {
            'total_amount': str(agg['total_amount']),
            'total_quantity': str(agg['total_quantity']),
            'order_count': agg['order_count'],
            'avg_amount': str(round(avg_amount, 2)),
            'return_amount': str(return_amount),
            'return_quantity': str(return_qty),
            'return_rate': str(round(return_rate, 2)),
        }

    @staticmethod
    @_cache_report('rpt:sales:trend')
    def get_trend(user, period='month', granularity='day', start_date=None, end_date=None):
        """销售趋势"""
        from business_apps.sales.models import SalesOrder

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
            created_at__range=(start, end),
        )

        trunc_map = {
            'day': TruncDate,
            'week': TruncWeek,
            'month': TruncMonth,
            'quarter': TruncQuarter,
            'year': TruncYear,
        }
        trunc_fn = trunc_map.get(granularity, TruncDate)

        trend = qs.annotate(period=trunc_fn('created_at')).values('period').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            order_count=Count('id'),
        ).order_by('period')

        return [{'period': t['period'].isoformat() if t['period'] else '', 'amount': str(t['total_amount']), 'count': t['order_count']} for t in trend]

    @staticmethod
    def get_product_ranking(user, period='month', limit=20, start_date=None, end_date=None):
        """商品销售排行"""
        from business_apps.sales.models import SalesOrder, SalesOrderItem

        start, end = _get_date_range(period, start_date, end_date)

        valid_orders = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
            created_at__range=(start, end),
        )

        ranking = SalesOrderItem.objects.filter(
            order__in=valid_orders
        ).values('product__name', 'product__product_code', 'product_id').annotate(
            total_quantity=Coalesce(Sum('quantity'), Decimal(0)),
            total_amount=Coalesce(Sum('amount'), Decimal(0)),
        ).order_by('-total_amount')[:limit]

        return [{'product_id': r['product_id'], 'name': r['product__name'], 'code': r['product__product_code'], 'quantity': str(r['total_quantity']), 'amount': str(r['total_amount'])} for r in ranking]

    @staticmethod
    def get_customer_ranking(user, period='month', limit=20, start_date=None, end_date=None):
        """客户销售排行"""
        from business_apps.sales.models import SalesOrder

        start, end = _get_date_range(period, start_date, end_date)

        ranking = _tenant_qs(SalesOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'ALLOCATED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CLOSED'],
            created_at__range=(start, end),
        ).values('customer_id', 'customer__customer_name').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            order_count=Count('id'),
        ).order_by('-total_amount')[:limit]

        return [{'customer_id': r['customer_id'], 'name': r['customer__customer_name'], 'amount': str(r['total_amount']), 'order_count': r['order_count']} for r in ranking]


class PurchaseReportService:
    """采购分析"""

    @staticmethod
    def get_drill_orders(user, period='month', start_date=None, end_date=None,
                         product_id=None, supplier_id=None):
        """钻取：从采购排行点击进入订单明细"""
        from business_apps.purchase.models import PurchaseOrder

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_and_dept_qs(
            PurchaseOrder.objects.filter(
                status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
                created_at__range=(start, end),
            ).select_related('supplier', 'created_by'), user, 'dept'
        )

        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        if product_id:
            qs = qs.filter(items__product_id=product_id).distinct()

        return qs.order_by('-created_at')[:100]

    @staticmethod
    @_cache_report('rpt:purchase:summary')
    def get_summary(user, period='month', start_date=None, end_date=None):
        """采购汇总"""
        from business_apps.purchase.models import PurchaseOrder
        from business_apps.supply_chain.models import PurchaseReturnOrder, PurchaseReturnOrderItem

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_and_dept_qs(
            PurchaseOrder.objects.filter(
                status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
                created_at__range=(start, end),
            ), user, 'dept'
        )

        agg = qs.aggregate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            total_quantity=Coalesce(Sum('total_quantity'), Decimal(0)),
            order_count=Count('id'),
        )

        # 退货统计
        return_qs = _tenant_qs(PurchaseReturnOrder.objects.all(), user).filter(
            status='COMPLETED', completed_at__range=(start, end)
        )
        return_items = PurchaseReturnOrderItem.objects.filter(return_order__in=return_qs)
        return_amount = Decimal(0)
        for item in return_items:
            return_amount += item.quantity * (item.product.cost_price or Decimal(0))

        return_qty = return_items.aggregate(total=Coalesce(Sum('quantity'), Decimal(0)))['total']
        return_rate = (return_qty / agg['total_quantity'] * 100) if agg['total_quantity'] > 0 else Decimal(0)

        return {
            'total_amount': str(agg['total_amount']),
            'total_quantity': str(agg['total_quantity']),
            'order_count': agg['order_count'],
            'return_amount': str(return_amount),
            'return_quantity': str(return_qty),
            'return_rate': str(round(return_rate, 2)),
        }

    @staticmethod
    @_cache_report('rpt:purchase:trend')
    def get_trend(user, period='month', granularity='day', start_date=None, end_date=None):
        """采购趋势"""
        from business_apps.purchase.models import PurchaseOrder

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
            created_at__range=(start, end),
        )

        trunc_map = {'day': TruncDate, 'week': TruncWeek, 'month': TruncMonth, 'quarter': TruncQuarter, 'year': TruncYear}
        trunc_fn = trunc_map.get(granularity, TruncDate)

        trend = qs.annotate(period=trunc_fn('created_at')).values('period').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            order_count=Count('id'),
        ).order_by('period')

        return [{'period': t['period'].isoformat() if t['period'] else '', 'amount': str(t['total_amount']), 'count': t['order_count']} for t in trend]

    @staticmethod
    def get_supplier_ranking(user, period='month', limit=20, start_date=None, end_date=None):
        """供应商采购排行"""
        from business_apps.purchase.models import PurchaseOrder

        start, end = _get_date_range(period, start_date, end_date)

        ranking = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
            created_at__range=(start, end),
        ).values('supplier_id', 'supplier__supplier_name').annotate(
            total_amount=Coalesce(Sum('total_amount'), Decimal(0)),
            total_quantity=Coalesce(Sum('total_quantity'), Decimal(0)),
            order_count=Count('id'),
        ).order_by('-total_amount')[:limit]

        return [{'supplier_id': r['supplier_id'], 'name': r['supplier__supplier_name'], 'amount': str(r['total_amount']), 'quantity': str(r['total_quantity']), 'order_count': r['order_count']} for r in ranking]

    @staticmethod
    def get_product_ranking(user, period='month', limit=20, start_date=None, end_date=None):
        """商品采购排行"""
        from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem

        start, end = _get_date_range(period, start_date, end_date)

        valid_orders = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            status__in=['APPROVED', 'PARTIALLY_RECEIVED', 'RECEIVED'],
            created_at__range=(start, end),
        )

        ranking = PurchaseOrderItem.objects.filter(
            purchase_order__in=valid_orders
        ).values('product__name', 'product__product_code', 'product_id').annotate(
            total_quantity=Coalesce(Sum('quantity'), Decimal(0)),
            total_amount=Coalesce(Sum('amount'), Decimal(0)),
        ).order_by('-total_amount')[:limit]

        return [{'product_id': r['product_id'], 'name': r['product__name'], 'code': r['product__product_code'], 'quantity': str(r['total_quantity']), 'amount': str(r['total_amount'])} for r in ranking]


class InventoryReportService:
    """库存分析"""

    @staticmethod
    def get_summary(user):
        """库存概览"""
        return DashboardService.get_inventory_overview(user)

    @staticmethod
    def get_aging(user):
        """库龄分析"""
        from business_apps.inventory.models import Inventory, InventoryTransaction

        now = timezone.now()
        ranges = [
            ('0-30天', 0, 30),
            ('31-60天', 31, 60),
            ('61-90天', 61, 90),
            ('90天以上', 91, 9999),
        ]

        result = []
        for label, min_days, max_days in ranges:
            # 统计最近入库且未出库的商品
            cutoff_start = now - timedelta(days=max_days)
            cutoff_end = now - timedelta(days=min_days)

            invs = _tenant_qs(Inventory.objects.filter(current_qty__gt=0).select_related('product'), user)
            total_value = Decimal(0)
            total_qty = Decimal(0)
            count = 0

            for inv in invs:
                # 查找最近一次入库时间
                last_in = _tenant_qs(InventoryTransaction.objects.all(), user).filter(
                    product=inv.product,
                    warehouse=inv.warehouse,
                    transaction_type__in=['PURCHASE_IN', 'TRANSFER_IN', 'RETURN_IN', 'STOCKTAKE_GAIN'],
                    quantity__gt=0,
                ).order_by('-created_at').first()

                if last_in:
                    days_since = (now - last_in.created_at).days
                    if min_days <= days_since <= max_days:
                        total_value += inv.current_qty * (inv.product.cost_price or Decimal(0))
                        total_qty += inv.current_qty
                        count += 1

            result.append({
                'range': label,
                'sku_count': count,
                'total_qty': str(total_qty),
                'total_value': str(total_value),
            })

        return result

    @staticmethod
    def get_alerts(user):
        """库存预警分析"""
        from business_apps.inventory.models import Inventory

        inventories = _tenant_qs(Inventory.objects.select_related('product', 'warehouse'), user).filter(current_qty__gte=0)

        low_stock = []
        out_of_stock = []
        over_stock = []

        for inv in inventories:
            product = inv.product
            if inv.current_qty == 0:
                out_of_stock.append({
                    'product_id': product.id, 'product_name': product.name, 'product_code': product.product_code,
                    'warehouse_name': inv.warehouse.warehouse_name, 'current_qty': str(inv.current_qty),
                    'min_stock': str(product.min_stock or 0),
                })
            elif product.min_stock and inv.current_qty < product.min_stock:
                low_stock.append({
                    'product_id': product.id, 'product_name': product.name, 'product_code': product.product_code,
                    'warehouse_name': inv.warehouse.warehouse_name, 'current_qty': str(inv.current_qty),
                    'min_stock': str(product.min_stock),
                })
            elif product.max_stock and inv.current_qty > product.max_stock:
                over_stock.append({
                    'product_id': product.id, 'product_name': product.name, 'product_code': product.product_code,
                    'warehouse_name': inv.warehouse.warehouse_name, 'current_qty': str(inv.current_qty),
                    'max_stock': str(product.max_stock),
                })

        return {
            'low_stock': low_stock,
            'out_of_stock': out_of_stock,
            'over_stock': over_stock,
            'low_stock_count': len(low_stock),
            'out_of_stock_count': len(out_of_stock),
            'over_stock_count': len(over_stock),
        }

    @staticmethod
    def get_transaction_summary(user, period='month', start_date=None, end_date=None):
        """库存流水分析"""
        from business_apps.inventory.models import InventoryTransaction

        start, end = _get_date_range(period, start_date, end_date)

        qs = _tenant_qs(InventoryTransaction.objects.all(), user).filter(created_at__range=(start, end))

        summary = qs.values('transaction_type').annotate(
            total_quantity=Coalesce(Sum('quantity'), Decimal(0)),
            count=Count('id'),
        ).order_by('transaction_type')

        type_map = {
            'PURCHASE_IN': '采购入库', 'SALE_OUT': '销售出库', 'TRANSFER_IN': '调拨入库',
            'TRANSFER_OUT': '调拨出库', 'RETURN_IN': '退货入库', 'RETURN_OUT': '退货出库',
            'MANUAL_ADJUST': '手动调整', 'STOCKTAKE_GAIN': '盘盈入库', 'STOCKTAKE_LOSS': '盘亏出库',
        }

        return [{'type': s['transaction_type'], 'label': type_map.get(s['transaction_type'], s['transaction_type']), 'quantity': str(s['total_quantity']), 'count': s['count']} for s in summary]


class CustomerReportService:
    """客户分析"""

    @staticmethod
    def get_stats(user, period='month', start_date=None, end_date=None):
        """客户数量统计"""
        from business_apps.crm.models import Customer

        start, end = _get_date_range(period, start_date, end_date)

        total = _tenant_qs(Customer.objects.all(), user).filter(is_deleted=False).count()
        new_customers = _tenant_qs(Customer.objects.all(), user).filter(is_deleted=False, created_at__range=(start, end)).count()

        return {
            'total_count': total,
            'new_count': new_customers,
        }

    @staticmethod
    def get_ranking(user, period='month', limit=20, start_date=None, end_date=None):
        """客户排行"""
        return SalesReportService.get_customer_ranking(user, period, limit, start_date, end_date)

    @staticmethod
    def get_activity(user):
        """客户活跃度分析（聚合查询）"""
        from business_apps.crm.models import Customer
        from business_apps.sales.models import SalesOrder

        now = timezone.now()
        last_30 = now - timedelta(days=30)
        last_90 = now - timedelta(days=90)

        total = _tenant_qs(Customer.objects.all(), user).filter(is_deleted=False).count()

        # 30天内有订单的客户ID
        active_30_ids = _tenant_qs(SalesOrder.objects.all(), user).filter(
            created_at__gte=last_30
        ).values_list('customer_id', flat=True).distinct()
        active_30 = _tenant_qs(Customer.objects.all(), user).filter(is_deleted=False, id__in=active_30_ids).count()

        # 90天内有订单的客户ID
        active_90_ids = _tenant_qs(SalesOrder.objects.all(), user).filter(
            created_at__gte=last_90
        ).values_list('customer_id', flat=True).distinct()
        active_90 = _tenant_qs(Customer.objects.all(), user).filter(is_deleted=False, id__in=active_90_ids).count()

        return {
            'active_30': active_30,
            'active_90': active_90,
            'inactive': total - active_90,
            'total': total,
        }

    @staticmethod
    def get_churn(user):
        """客户流失分析（90天无订单，聚合查询）"""
        from business_apps.crm.models import Customer
        from business_apps.sales.models import SalesOrder

        now = timezone.now()
        cutoff = now - timedelta(days=90)

        # 90天内有订单的客户ID
        active_ids = _tenant_qs(SalesOrder.objects.all(), user).filter(
            created_at__gte=cutoff
        ).values_list('customer_id', flat=True).distinct()

        # 流失客户 = 活跃状态但90天无订单
        churned_qs = _tenant_qs(Customer.objects.all(), user).filter(
            is_deleted=False, status='ACTIVE'
        ).exclude(id__in=active_ids)

        churned_count = churned_qs.count()
        # 取前50条详细信息（含最近下单时间）
        churned_customers = churned_qs[:50]

        # 批量获取最近下单时间
        last_orders = {}
        for so in _tenant_qs(SalesOrder.objects.all(), user).filter(
            customer_id__in=[c.id for c in churned_customers]
        ).values_list('customer_id', 'created_at').order_by('customer_id', '-created_at'):
            if so[0] not in last_orders:
                last_orders[so[0]] = so[1]

        churned = [{
            'customer_id': c.id,
            'customer_name': c.customer_name,
            'last_order_date': last_orders.get(c.id).isoformat() if c.id in last_orders else None,
        } for c in churned_customers]

        return {'churned_count': churned_count, 'churned': churned}


class SupplierReportService:
    """供应商分析"""

    @staticmethod
    def get_ranking(user, period='month', limit=20, start_date=None, end_date=None):
        """供应商排行"""
        return PurchaseReportService.get_supplier_ranking(user, period, limit, start_date, end_date)

    @staticmethod
    def get_activity(user):
        """供应商活跃度（聚合查询）"""
        from business_apps.supplier.models import Supplier
        from business_apps.purchase.models import PurchaseOrder

        now = timezone.now()
        last_30 = now - timedelta(days=30)

        total = _tenant_qs(Supplier.objects.all(), user).filter(is_deleted=False).count()

        # 30天内有采购的供应商ID
        active_30_ids = _tenant_qs(PurchaseOrder.objects.all(), user).filter(
            created_at__gte=last_30
        ).values_list('supplier_id', flat=True).distinct()
        active_30 = _tenant_qs(Supplier.objects.all(), user).filter(is_deleted=False, id__in=active_30_ids).count()

        return {
            'total': total,
            'active_30': active_30,
        }

    @staticmethod
    def get_evaluation_ranking(user, limit=20):
        """供应商评价排行"""
        from business_apps.supplier.models import SupplierEvaluation

        ranking = _tenant_qs(SupplierEvaluation.objects.select_related('supplier'), user).annotate(
            score_avg=ExpressionWrapper(
                (F('quality_score') + F('delivery_score') + F('service_score') + F('price_score')) / Value(4.0),
                output_field=FloatField(),
            )
        ).order_by('-score_avg')[:limit]
        return [
            {
                'supplier_id': e.supplier_id,
                'supplier_name': e.supplier.supplier_name,
                'score': str(e.score_avg),
            }
            for e in ranking
        ]


class ProductReportService:
    """商品分析"""

    @staticmethod
    def get_hot_products(user, period='month', limit=20, start_date=None, end_date=None):
        """热销商品"""
        return SalesReportService.get_product_ranking(user, period, limit, start_date, end_date)

    @staticmethod
    def get_slow_products(user, days=90):
        """滞销商品（N天无销售）"""
        from business_apps.inventory.models import Product, Inventory
        from business_apps.sales.models import SalesOrderItem, SalesOrder

        cutoff = timezone.now() - timedelta(days=days)
        products_with_sales = _tenant_qs(SalesOrderItem.objects.all(), user).filter(
            order__created_at__gte=cutoff
        ).values_list('product_id', flat=True).distinct()

        slow_products = _tenant_qs(Product.objects.all(), user).filter(
            is_deleted=False, status='ACTIVE'
        ).exclude(id__in=products_with_sales)

        result = []
        for p in slow_products[:50]:
            inv = _tenant_qs(Inventory.objects.all(), user).filter(product=p).first()
            result.append({
                'product_id': p.id, 'name': p.name, 'code': p.product_code,
                'current_stock': str(inv.current_qty) if inv else '0',
                'cost_price': str(p.cost_price or 0),
            })

        return {'count': slow_products.count(), 'products': result}

    @staticmethod
    def get_inventory_analysis(user):
        """商品库存分析"""
        from business_apps.inventory.models import Inventory

        inventories = _tenant_qs(Inventory.objects.select_related('product', 'warehouse'), user).filter(current_qty__gt=0)

        result = []
        for inv in inventories[:100]:
            result.append({
                'product_id': inv.product_id, 'product_name': inv.product.name,
                'product_code': inv.product.product_code,
                'warehouse_name': inv.warehouse.warehouse_name,
                'quantity': str(inv.current_qty),
                'value': str(inv.current_qty * (inv.product.cost_price or Decimal(0))),
                'cost_price': str(inv.product.cost_price or 0),
            })

        return result


class ExportService:
    """报表导出服务"""

    @staticmethod
    def create_task(report_type, params, user):
        """创建导出任务"""
        from .models import ReportExportTask
        task = ReportExportTask.objects.create(
            report_type=report_type,
            params=params,
            created_by=user,
        )
        # 同步执行导出（小数据量场景，大数据量应改为Celery异步）
        ExportService._execute_task(task)
        return task

    @staticmethod
    def _execute_task(task):
        """执行导出任务"""
        import openpyxl
        from io import BytesIO
        from django.core.files.base import ContentFile
        from .models import ReportExportTask

        try:
            task.status = 'PROCESSING'
            task.save()

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = task.get_report_type_display()

            # 根据报表类型生成数据
            data = ExportService._get_report_data(task)
            if data and len(data) > 0:
                # 写入表头
                headers = list(data[0].keys())
                ws.append(headers)
                # 写入数据
                for row in data:
                    ws.append([str(v) if v is not None else '' for v in row.values()])

            buffer = BytesIO()
            wb.save(buffer)
            buffer.seek(0)

            file_name = f"{task.get_report_type_display()}_{timezone.now().strftime('%Y%m%d%H%M%S')}.xlsx"
            task.file_name = file_name
            task.file_url = f"/media/exports/{file_name}"
            task.status = 'COMPLETED'
            task.completed_at = timezone.now()
            task.save()

            # 保存文件到media目录
            import os
            from django.conf import settings
            export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
            os.makedirs(export_dir, exist_ok=True)
            with open(os.path.join(export_dir, file_name), 'wb') as f:
                f.write(buffer.getvalue())

        except Exception as e:
            task.status = 'FAILED'
            task.error_message = str(e)
            task.save()

    @staticmethod
    def _get_report_data(task):
        """根据报表类型获取数据"""
        user = task.created_by
        params = task.params or {}
        period = params.get('period', 'month')

        if task.report_type == 'SALES_SUMMARY':
            return [SalesReportService.get_summary(user, period)]
        elif task.report_type == 'SALES_PRODUCTS':
            return SalesReportService.get_product_ranking(user, period)
        elif task.report_type == 'SALES_CUSTOMERS':
            return SalesReportService.get_customer_ranking(user, period)
        elif task.report_type == 'PURCHASE_SUMMARY':
            return [PurchaseReportService.get_summary(user, period)]
        elif task.report_type == 'PURCHASE_SUPPLIERS':
            return PurchaseReportService.get_supplier_ranking(user, period)
        elif task.report_type == 'INVENTORY_SUMMARY':
            return [InventoryReportService.get_summary(user)]
        elif task.report_type == 'INVENTORY_ALERTS':
            alerts = InventoryReportService.get_alerts(user)
            return alerts.get('low_stock', []) + alerts.get('out_of_stock', [])
        elif task.report_type == 'CUSTOMER_ANALYSIS':
            return CustomerReportService.get_ranking(user, period)
        elif task.report_type == 'SUPPLIER_ANALYSIS':
            return SupplierReportService.get_ranking(user, period)
        elif task.report_type == 'PRODUCT_ANALYSIS':
            return ProductReportService.get_hot_products(user, period)
        else:
            return []
