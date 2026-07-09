from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ObjectDoesNotExist
from django_filters.rest_framework import DjangoFilterBackend
from core_apps.common.viewsets import BaseBusinessViewSet
from .models import PurchaseOrder, PurchaseOrderItem, PurchaseReceipt, PurchaseAttachment
from .serializers import (
    PurchaseOrderSerializer, PurchaseOrderListSerializer,
    PurchaseReceiptSerializer, PurchaseReceiptListSerializer,
    PurchaseAttachmentSerializer
)
from .services import PurchaseOrderService
from .filters import PurchaseOrderFilter, PurchaseReceiptFilter
from business_apps.supplier.models import Supplier
from business_apps.inventory.models import Product, Warehouse

MODULE_KEY = "purchase"


class PurchaseOrderViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = PurchaseOrder.objects.all()
    serializer_class = PurchaseOrderSerializer
    user_field = 'created_by'
    filter_backends = [DjangoFilterBackend]
    filterset_class = PurchaseOrderFilter

    permission_map = {
        'list': 'purchase:order:view',
        'retrieve': 'purchase:order:view',
        'create': 'purchase:order:create',
        'update': 'purchase:order:update',
        'partial_update': 'purchase:order:update',
        'destroy': 'purchase:order:delete',
        'submit': 'purchase:order:update',
        'approve': 'purchase:order:approve',
        'reject': 'purchase:order:approve',
        'close': 'purchase:order:update',
        'cancel': 'purchase:order:cancel',
        'statistics': 'purchase:order:view',
        'upload_attachment': 'purchase:order:update',
        'delete_attachment': 'purchase:order:update',
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseOrderListSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        supplier_id = request.data.get('supplier')
        items_data = request.data.get('items', [])
        remark = request.data.get('remark')
        expected_arrival_date = request.data.get('expected_arrival_date')

        if not supplier_id or not items_data:
            return Response({"detail": "缺少供应商或商品明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            supplier = self.get_scoped_related_object(Supplier.objects.filter(is_deleted=False), id=supplier_id)
            processed_items = []
            for item in items_data:
                processed_items.append({
                    'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=item['product']),
                    'warehouse': item.get('warehouse'),
                    'quantity': item['quantity'],
                    'unit_price': item['unit_price'],
                    'remark': item.get('remark', ''),
                })

            order = PurchaseOrderService.create_order(
                supplier, processed_items, request.user, remark, expected_arrival_date
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status not in (PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_REJECTED):
            return Response({"detail": "只有草稿或已驳回状态的订单可以修改"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            supplier_id = request.data.get('supplier')
            items_data = request.data.get('items')
            remark = request.data.get('remark')
            expected_arrival_date = request.data.get('expected_arrival_date')

            supplier = self.get_scoped_related_object(Supplier.objects.filter(is_deleted=False), id=supplier_id) if supplier_id else None

            processed_items = None
            if items_data is not None:
                processed_items = []
                for item in items_data:
                    processed_items.append({
                        'product': self.get_scoped_related_object(Product.objects.filter(is_deleted=False), id=item['product']),
                        'warehouse': item.get('warehouse'),
                        'quantity': item['quantity'],
                        'unit_price': item['unit_price'],
                        'remark': item.get('remark', ''),
                    })

            order = PurchaseOrderService.update_order(
                order, request.user, supplier, processed_items, remark, expected_arrival_date
            )
            serializer = self.get_serializer(order)
            return Response(serializer.data)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        """仅允许删除草稿状态的订单"""
        order = self.get_object()
        if order.status != 'DRAFT':
            return Response({"detail": "只有草稿状态的订单可以删除"}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """提交审核：DRAFT -> PENDING_APPROVAL"""
        order = self.get_object()
        try:
            PurchaseOrderService.submit_order(order, request.user)
            return Response({'status': 'submitted'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseOrderService.approve_order(order, request.user, request.data.get('comment'))
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseOrderService.reject_order(order, request.user, request.data.get('comment'))
            return Response({'status': 'rejected'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseOrderService.close_order(order, request.user)
            return Response({'status': 'closed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseOrderService.cancel_order(order, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        stats = PurchaseOrderService.get_statistics(start_date, end_date)
        return Response(stats)

    @action(detail=True, methods=['post'])
    def upload_attachment(self, request, pk=None):
        order = self.get_object()
        file_name = request.data.get('file_name')
        file_url = request.data.get('file_url')
        if not file_name or not file_url:
            return Response({"detail": "缺少文件名或文件地址"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            attachment = PurchaseOrderService.upload_attachment(order, file_name, file_url, request.user)
            serializer = PurchaseAttachmentSerializer(attachment)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'], url_path='attachments/(?P<attachment_id>[^/.]+)')
    def delete_attachment(self, request, pk=None, attachment_id=None):
        try:
            PurchaseOrderService.delete_attachment(attachment_id, request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PurchaseReceiptViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = PurchaseReceipt.objects.all()
    serializer_class = PurchaseReceiptSerializer
    user_field = 'created_by'
    filter_backends = [DjangoFilterBackend]
    filterset_class = PurchaseReceiptFilter

    permission_map = {
        'list': 'purchase:receipt:view',
        'retrieve': 'purchase:receipt:view',
        'create': 'purchase:receipt:create',
        'complete': 'purchase:receipt:complete',
        'cancel': 'purchase:receipt:cancel',
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseReceiptListSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        po_id = request.data.get('purchase_order')
        warehouse_id = request.data.get('warehouse')
        items_data = request.data.get('items', [])
        remark = request.data.get('remark')

        if not po_id or not items_data:
            return Response({"detail": "缺少采购订单或入库明细"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = self.get_scoped_related_object(PurchaseOrder.objects.all(), id=po_id)
            processed_items = []
            for item in items_data:
                po_item = self.get_scoped_related_object(PurchaseOrderItem.objects.all(), id=item['purchase_order_item'])
                processed_items.append({
                    'purchase_order_item': po_item,
                    'received_quantity': item['received_quantity'],
                    'remark': item.get('remark', ''),
                })

            warehouse = self.get_scoped_related_object(Warehouse.objects.all(), id=warehouse_id)
            receipt = PurchaseOrderService.create_receipt(order, warehouse, processed_items, request.user, remark)
            serializer = self.get_serializer(receipt)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """执行入库。"""
        receipt = self.get_object()
        try:
            PurchaseOrderService.execute_receipt(receipt, request.user)
            return Response({'status': 'executed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        receipt = self.get_object()
        try:
            PurchaseOrderService.cancel_receipt(receipt, request.user)
            return Response({'status': 'cancelled'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
