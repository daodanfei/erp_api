from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ObjectDoesNotExist
from django_filters.rest_framework import DjangoFilterBackend
from core_apps.common.viewsets import BaseBusinessViewSet
from core_apps.common.permissions import ERPActionPermission
from .models import OutboundOrder, TransferOrder, SalesReturnOrder, PurchaseReturnOrder, InventoryAlert
from .serializers import (
    OutboundOrderSerializer, OutboundOrderListSerializer,
    TransferOrderSerializer, TransferOrderListSerializer,
    SalesReturnOrderSerializer, SalesReturnOrderListSerializer,
    PurchaseReturnOrderSerializer, PurchaseReturnOrderListSerializer,
    InventoryAlertSerializer,
)
from .services import OutboundService, TransferService, SalesReturnService, PurchaseReturnService, InventoryAlertService, InventoryTraceService
from .filters import (
    OutboundOrderFilter, TransferOrderFilter,
    SalesReturnOrderFilter, PurchaseReturnOrderFilter, InventoryAlertFilter,
)
from business_apps.inventory.models import Product, Warehouse
from business_apps.crm.models import Customer
from business_apps.supplier.models import Supplier


class OutboundOrderViewSet(BaseBusinessViewSet):
    queryset = OutboundOrder.objects.all()
    serializer_class = OutboundOrderSerializer
    user_field = 'created_by'
    permission_classes = [ERPActionPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_class = OutboundOrderFilter

    permission_map = {
        'list': 'supply_chain:outbound:view',
        'retrieve': 'supply_chain:outbound:view',
        'create': 'supply_chain:outbound:create',
        'update': 'supply_chain:outbound:update',
        'partial_update': 'supply_chain:outbound:update',
        'destroy': 'supply_chain:outbound:delete',
        'submit': 'supply_chain:outbound:update',
        'approve': 'supply_chain:outbound:approve',
        'complete': 'supply_chain:outbound:complete',
        'cancel': 'supply_chain:outbound:cancel',
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return OutboundOrderListSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        warehouse_id = request.data.get('warehouse')
        items_data = request.data.get('items', [])
        if not warehouse_id or not items_data:
            return Response({"detail": "缺少仓库或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            warehouse = self.get_scoped_related_object(Warehouse.objects.all(), id=warehouse_id)
            sales_order = None
            if request.data.get('sales_order'):
                from business_apps.sales.models import SalesOrder
                sales_order = self.get_scoped_related_object(SalesOrder.objects.all(), id=request.data['sales_order'])

            processed_items = []
            for item in items_data:
                processed_items.append({
                    'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=item['product']),
                    'quantity': item['quantity'],
                    'remark': item.get('remark', ''),
                })

            order = OutboundService.create_order(
                sales_order, warehouse, processed_items, request.user,
                remark=request.data.get('remark')
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """提交审核：DRAFT -> PENDING"""
        order = self.get_object()
        try:
            OutboundService.submit_order(order, request.user)
            return Response({'status': 'pending'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        order = self.get_object()
        try:
            OutboundService.complete_order(order, request.user)
            return Response({'status': 'completed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        order = self.get_object()
        try:
            OutboundService.approve_order(order, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            OutboundService.cancel_order(order, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class TransferOrderViewSet(BaseBusinessViewSet):
    queryset = TransferOrder.objects.all()
    serializer_class = TransferOrderSerializer
    user_field = 'created_by'
    permission_classes = [ERPActionPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_class = TransferOrderFilter

    permission_map = {
        'list': 'supply_chain:transfer:view',
        'retrieve': 'supply_chain:transfer:view',
        'create': 'supply_chain:transfer:create',
        'update': 'supply_chain:transfer:update',
        'partial_update': 'supply_chain:transfer:update',
        'destroy': 'supply_chain:transfer:delete',
        'submit': 'supply_chain:transfer:submit',
        'approve': 'supply_chain:transfer:approve',
        'start': 'supply_chain:transfer:start',
        'complete': 'supply_chain:transfer:complete',
        'cancel': 'supply_chain:transfer:cancel',
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return TransferOrderListSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        from_wh_id = request.data.get('from_warehouse')
        to_wh_id = request.data.get('to_warehouse')
        items_data = request.data.get('items', [])
        if not from_wh_id or not to_wh_id or not items_data:
            return Response({"detail": "缺少仓库或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from_wh = self.get_scoped_related_object(Warehouse.objects.all(), id=from_wh_id)
            to_wh = self.get_scoped_related_object(Warehouse.objects.all(), id=to_wh_id)
            processed_items = [
                {
                    'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=i['product']),
                    'quantity': i['quantity'],
                    'remark': i.get('remark', ''),
                }
                for i in items_data
            ]

            order = TransferService.create_order(from_wh, to_wh, processed_items, request.user, remark=request.data.get('remark'))
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        from_wh_id = request.data.get('from_warehouse')
        to_wh_id = request.data.get('to_warehouse')
        items_data = request.data.get('items', [])

        if not from_wh_id or not to_wh_id or items_data is None:
            return Response({"detail": "缺少仓库或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from_wh = self.get_scoped_related_object(Warehouse.objects.all(), id=from_wh_id)
            to_wh = self.get_scoped_related_object(Warehouse.objects.all(), id=to_wh_id)
            processed_items = [
                {
                    'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=i['product']),
                    'quantity': i['quantity'],
                    'remark': i.get('remark', ''),
                }
                for i in items_data
            ]
            order = TransferService.update_order(
                order,
                from_wh,
                to_wh,
                processed_items,
                request.user,
                remark=request.data.get('remark'),
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        order = self.get_object()
        try:
            order = TransferService.submit_order(order, request.user)
            return Response({'status': order.status.lower()})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        order = self.get_object()
        try:
            TransferService.approve_order(order, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        order = self.get_object()
        try:
            TransferService.start_transfer(order, request.user)
            return Response({'status': 'in_transit'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        order = self.get_object()
        try:
            TransferService.complete_transfer(order, request.user)
            return Response({'status': 'completed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            TransferService.cancel_transfer(order, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SalesReturnOrderViewSet(BaseBusinessViewSet):
    queryset = SalesReturnOrder.objects.all()
    serializer_class = SalesReturnOrderSerializer
    user_field = 'created_by'
    permission_classes = [ERPActionPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_class = SalesReturnOrderFilter

    permission_map = {
        'list': 'supply_chain:sales_return:view',
        'retrieve': 'supply_chain:sales_return:view',
        'create': 'supply_chain:sales_return:create',
        'update': 'supply_chain:sales_return:update',
        'partial_update': 'supply_chain:sales_return:update',
        'destroy': 'supply_chain:sales_return:delete',
        'approve': 'supply_chain:sales_return:approve',
        'complete': 'supply_chain:sales_return:complete',
        'cancel': 'supply_chain:sales_return:cancel',
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return SalesReturnOrderListSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        warehouse_id = request.data.get('warehouse')
        items_data = request.data.get('items', [])
        if not warehouse_id or not items_data:
            return Response({"detail": "缺少仓库或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            warehouse = self.get_scoped_related_object(Warehouse.objects.all(), id=warehouse_id)
            customer = self.get_scoped_related_object(Customer.objects.filter(is_deleted=False), id=request.data['customer']) if request.data.get('customer') else None
            sales_order = None
            if request.data.get('sales_order'):
                from business_apps.sales.models import SalesOrder
                sales_order = self.get_scoped_related_object(SalesOrder.objects.all(), id=request.data['sales_order'])

            processed_items = [
                {
                    'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=i['product']),
                    'quantity': i['quantity'],
                    'remark': i.get('remark', ''),
                }
                for i in items_data
            ]

            order = SalesReturnService.create_order(
                customer, sales_order, warehouse, processed_items, request.user,
                reason=request.data.get('reason'), remark=request.data.get('remark')
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        order = self.get_object()
        try:
            SalesReturnService.approve_order(order, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        order = self.get_object()
        try:
            SalesReturnService.complete_order(order, request.user)
            return Response({'status': 'completed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            SalesReturnService.cancel_order(order, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PurchaseReturnOrderViewSet(BaseBusinessViewSet):
    queryset = PurchaseReturnOrder.objects.all()
    serializer_class = PurchaseReturnOrderSerializer
    user_field = 'created_by'
    permission_classes = [ERPActionPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_class = PurchaseReturnOrderFilter

    permission_map = {
        'list': 'supply_chain:purchase_return:view',
        'retrieve': 'supply_chain:purchase_return:view',
        'create': 'supply_chain:purchase_return:create',
        'update': 'supply_chain:purchase_return:update',
        'partial_update': 'supply_chain:purchase_return:update',
        'destroy': 'supply_chain:purchase_return:delete',
        'approve': 'supply_chain:purchase_return:approve',
        'complete': 'supply_chain:purchase_return:complete',
        'cancel': 'supply_chain:purchase_return:cancel',
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseReturnOrderListSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        warehouse_id = request.data.get('warehouse')
        items_data = request.data.get('items', [])
        if not warehouse_id or not items_data:
            return Response({"detail": "缺少仓库或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            warehouse = self.get_scoped_related_object(Warehouse.objects.all(), id=warehouse_id)
            supplier = self.get_scoped_related_object(Supplier.objects.filter(is_deleted=False), id=request.data['supplier']) if request.data.get('supplier') else None
            purchase_order = None
            if request.data.get('purchase_order'):
                from business_apps.purchase.models import PurchaseOrder
                purchase_order = self.get_scoped_related_object(PurchaseOrder.objects.all(), id=request.data['purchase_order'])

            processed_items = [
                {
                    'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=i['product']),
                    'quantity': i['quantity'],
                    'remark': i.get('remark', ''),
                }
                for i in items_data
            ]

            order = PurchaseReturnService.create_order(
                supplier, purchase_order, warehouse, processed_items, request.user,
                reason=request.data.get('reason'), remark=request.data.get('remark')
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseReturnService.approve_order(order, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseReturnService.complete_order(order, request.user)
            return Response({'status': 'completed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseReturnService.cancel_order(order, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class InventoryAlertViewSet(BaseBusinessViewSet):
    queryset = InventoryAlert.objects.all()
    serializer_class = InventoryAlertSerializer
    user_field = 'created_by'
    permission_classes = [ERPActionPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_class = InventoryAlertFilter

    permission_map = {
        'list': 'supply_chain:alert:view',
        'retrieve': 'supply_chain:alert:view',
        'resolve': 'supply_chain:alert:resolve',
        'scan': 'supply_chain:alert:view',
    }

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        try:
            InventoryAlertService.resolve_alert(alert.id, request.user)
            return Response({'status': 'resolved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def scan(self, request):
        """手动触发预警扫描"""
        count = InventoryAlertService.check_and_create_alerts(user=request.user)
        return Response({'alerts_created': count})


class InventoryTraceViewSet(viewsets.ViewSet):
    """库存追溯API"""
    permission_classes = [ERPActionPermission]

    permission_map = {
        'trace': 'supply_chain:alert:view',
    }

    def list(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({"detail": "缺少product_id参数"}, status=status.HTTP_400_BAD_REQUEST)

        days = int(request.query_params.get('days', 30))
        warehouse_id = request.query_params.get('warehouse_id')

        try:
            qs = InventoryTraceService.get_product_trace(
                product_id=product_id,
                days=days,
                warehouse_id=warehouse_id,
                user=request.user,
            )
            data = [{
                'id': t.id,
                'transaction_no': t.transaction_no,
                'warehouse_id': t.warehouse_id,
                'warehouse_name': t.warehouse.warehouse_name,
                'product_id': t.product_id,
                'product_name': t.product.name,
                'transaction_type': t.transaction_type,
                'quantity': str(t.quantity),
                'before_qty': str(t.before_qty),
                'after_qty': str(t.after_qty),
                'reference_type': t.reference_type,
                'reference_id': t.reference_id,
                'remark': t.remark,
                'operator_name': t.operator.username if t.operator else None,
                'created_at': t.created_at.isoformat(),
            } for t in qs]
            return Response(data)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
