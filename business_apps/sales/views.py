from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ObjectDoesNotExist
from core_apps.common.viewsets import BaseBusinessViewSet
from core_apps.system.operation_log import (
    OperationLogChangeTracker,
    build_operation_log_new_value,
    summarize_operation_log_items,
)
from .models import SalesOrder, SalesOrderItem, Shipment, OrderApprovalLog, OrderAttachment
from .serializers import SalesOrderSerializer, SalesOrderItemSerializer, ShipmentSerializer, OrderApprovalLogSerializer, SalesOrderReferenceSerializer
from business_apps.supply_chain.serializers import OutboundOrderSerializer
from .services import SalesOrderService
from business_apps.crm.models import Customer
from business_apps.inventory.models import Product, Warehouse

MODULE_KEY = "sales"


class SalesOrderViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = SalesOrder.objects.all()
    serializer_class = SalesOrderSerializer
    user_field = 'created_by'
    filterset_fields = ['status', 'customer']
    search_fields = ['order_no', 'customer_name_snapshot', 'customer__customer_name']
    
    permission_map = {
        'list': 'sales:order:view',
        'retrieve': 'sales:order:view',
        'reference_options': 'sales:order:reference',
        'create': 'sales:order:create',
        'update': 'sales:order:update',
        'destroy': 'sales:order:delete',
        'approve': 'sales:order:approve',
        'reject': 'sales:order:approve',
        'allocate': 'sales:order:allocate',
        'create_outbound': 'sales:order:ship',
        'ship': 'sales:order:ship',
        'close': 'sales:order:close',
        'cancel': 'sales:order:cancel',
        'statistics': 'sales:stats:view',
    }

    def get_serializer_class(self):
        if self.action == 'reference_options':
            return SalesOrderReferenceSerializer
        return SalesOrderSerializer

    @action(detail=False, methods=['get'], url_path='reference-options')
    def reference_options(self, request):
        queryset = self.get_tenant_scoped_queryset().prefetch_related('items__product').order_by('-order_date', '-id')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        customer_id = request.data.get('customer')
        items_data = request.data.get('items', [])
        remark = request.data.get('remark')
        expected_delivery_date = request.data.get('expected_delivery_date')

        if not customer_id or not items_data:
            return Response({"detail": "缺少客户或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer = self.get_tenant_scoped_related_object(Customer.objects.all(), id=customer_id)
            # Resolve products
            processed_items = []
            for item in items_data:
                processed_items.append({
                    'product': self.get_tenant_scoped_related_object(Product.objects.filter(is_deleted=False), id=item['product']),
                    'warehouse': (
                        self.get_tenant_scoped_related_object(Warehouse.objects.filter(status=True), id=item['warehouse'])
                        if item.get('warehouse') is not None else None
                    ),
                    'quantity': item['quantity'],
                    'unit_price': item['unit_price'],
                })
            
            order = SalesOrderService.create_order(
                customer,
                processed_items,
                request.user,
                remark,
                expected_delivery_date,
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在、已停用或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        change_tracker = OperationLogChangeTracker(order, request.data)
        if order.status not in ('DRAFT', 'REJECTED'):
            return Response({"detail": "只有草稿或已驳回状态的订单可以修改"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer_id = request.data.get('customer')
            items_data = request.data.get('items')
            remark = request.data.get('remark')
            expected_delivery_date = request.data.get('expected_delivery_date')

            customer = self.get_tenant_scoped_related_object(Customer.objects.all(), id=customer_id) if customer_id else None
            processed_items = None
            if items_data is not None:
                processed_items = []
                for item in items_data:
                    processed_items.append({
                        'product': self.get_tenant_scoped_related_object(Product.objects.filter(is_deleted=False), id=item['product']),
                        'warehouse': (
                            self.get_tenant_scoped_related_object(Warehouse.objects.filter(status=True), id=item['warehouse'])
                            if item.get('warehouse') is not None else None
                        ),
                        'quantity': item['quantity'],
                        'unit_price': item['unit_price'],
                    })

            order = SalesOrderService.update_order(
                order,
                request.user,
                customer=customer,
                items_data=processed_items,
                remark=remark,
                expected_delivery_date=expected_delivery_date,
            )
            change_tracker.finish(
                request,
                order,
                extra_changes=(
                    [build_operation_log_new_value("items", summarize_operation_log_items(processed_items))]
                    if processed_items is not None else []
                ),
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
            SalesOrderService.submit_order(order, request.user)
            return Response({'status': 'submitted'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        order = self.get_object()
        comment = request.data.get('comment')
        try:
            SalesOrderService.approve_order(order, request.user, comment)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        order = self.get_object()
        comment = request.data.get('comment')
        try:
            SalesOrderService.reject_order(order, request.user, comment)
            return Response({'status': 'rejected'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def allocate(self, request, pk=None):
        order = self.get_object()
        try:
            SalesOrderService.allocate_stock(order, request.user)
            return Response({'status': 'allocated'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def create_outbound(self, request, pk=None):
        order = self.get_object()
        items_data = request.data.get('items', [])
        
        try:
            processed_items = []
            for item in items_data:
                processed_items.append({
                    'order_item': self.get_scoped_related_object(SalesOrderItem.objects.all(), id=item['order_item']),
                    'quantity': item['quantity']
                })
            
            outbound_orders = SalesOrderService.create_outbound_request(order, processed_items, request.user)
            serializer = OutboundOrderSerializer(outbound_orders, many=True)
            return Response(serializer.data)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        return self.create_outbound(request, pk=pk)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        order = self.get_object()
        try:
            SalesOrderService.close_order(order, request.user)
            return Response({'status': 'closed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            SalesOrderService.cancel_order(order, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        stats = SalesOrderService.get_statistics(request.user)
        return Response(stats)
