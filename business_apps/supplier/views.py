from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth
from core_apps.common.viewsets import BaseBusinessViewSet
from core_apps.common.utils.data_scope import get_data_scope_filter
from core_apps.erp_auth.compat import build_erp_user_and_dept_kwargs, build_erp_user_fk_kwargs
from core_apps.erp_auth.models import ERPUser
from core_apps.policies.registry import get_policy
from .models import Supplier, SupplierContact, SupplierFollowRecord, SupplierTag, SupplierAttachment, SupplierEvaluation, SupplierTransferLog
from .serializers import (
    SupplierSerializer, SupplierContactSerializer, SupplierFollowRecordSerializer, 
    SupplierTagSerializer, SupplierAttachmentSerializer, SupplierEvaluationSerializer, SupplierTransferLogSerializer
)
from .services import generate_supplier_code, check_duplicate_supplier, transfer_supplier, check_can_delete_supplier
from business_apps.purchase.models import PurchaseOrder, PurchaseOrderItem

MODULE_KEY = "supplier"

class SupplierViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = Supplier.objects.filter(is_deleted=False)
    serializer_class = SupplierSerializer
    user_field = 'owner'
    
    permission_map = {
        'list': 'supplier:supplier:view',
        'retrieve': 'supplier:supplier:view',
        'create': 'supplier:supplier:create',
        'update': 'supplier:supplier:update',
        'destroy': 'supplier:supplier:delete',
        'transfer': 'supplier:supplier:transfer',
        'purchase_statistics': 'supplier:supplier:view',
    }

    def perform_create(self, serializer):
        policy = get_policy("supplier", user=self.request.user)
        # 1. Duplication check
        errors = check_duplicate_supplier(
            self.request.data.get('supplier_name'),
            self.request.data.get('tax_number'),
            self.request.data.get('contact_phone'),
            self.request.data.get('email')
        )
        if errors:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": errors})
            
        supplier_code = self.request.data.get("supplier_code")
        if policy.code_auto_generate_enabled():
            supplier_code = generate_supplier_code()
        elif not supplier_code:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"supplier_code": ["请填写供应商编码"]})

        serializer.save(
            supplier_code=supplier_code,
            status='INACTIVE' if policy.approval_enabled() else serializer.validated_data.get('status', 'ACTIVE'),
            owner=self.request.user if isinstance(self.request.user, ERPUser) else None,
            **build_erp_user_and_dept_kwargs(Supplier, user=self.request.user, user_field="created_by"),
        )

    def perform_update(self, serializer):
        errors = check_duplicate_supplier(
            self.request.data.get('supplier_name', serializer.instance.supplier_name),
            self.request.data.get('tax_number', serializer.instance.tax_number),
            self.request.data.get('contact_phone', serializer.instance.contact_phone),
            self.request.data.get('email', serializer.instance.email),
            exclude_id=serializer.instance.id,
        )
        if errors:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": errors})

        serializer.save()

    def perform_destroy(self, instance):
        # Prevent deletion if supplier is in use
        reasons = check_can_delete_supplier(instance)
        if reasons:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": f"无法删除供应商：{', '.join(reasons)}"})
            
        # Soft delete
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        delete_kwargs = build_erp_user_fk_kwargs(
            Supplier,
            user=self.request.user,
            field_names=("deleted_by",),
        )
        instance.deleted_by = delete_kwargs.get("deleted_by")
        instance.save()

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        supplier = self.get_object()
        policy = get_policy("supplier", user=request.user)
        if not policy.owner_transfer_enabled():
            return Response({"detail": "当前配置未启用供应商负责人转移"}, status=status.HTTP_400_BAD_REQUEST)
        new_owner_id = request.data.get('new_owner_id')
        remark = request.data.get('remark')
        
        new_owner = ERPUser.objects.get(id=new_owner_id, tenant=request.user.tenant, status=True)
        
        transfer_supplier(supplier, new_owner, request.user, remark)
        return Response({'status': 'success'})

    @action(detail=True, methods=['get'])
    def contacts(self, request, pk=None):
        supplier = self.get_object()
        contacts = supplier.contacts.all()
        serializer = SupplierContactSerializer(contacts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def follow_records(self, request, pk=None):
        supplier = self.get_object()
        records = supplier.follow_records.all().order_by('-created_at')
        serializer = SupplierFollowRecordSerializer(records, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def evaluations(self, request, pk=None):
        supplier = self.get_object()
        evals = supplier.evaluations.all().order_by('-evaluated_at')
        serializer = SupplierEvaluationSerializer(evals, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='purchase-statistics')
    def purchase_statistics(self, request, pk=None):
        supplier = self.get_object()
        purchase_scope = get_data_scope_filter(
            request.user,
            dept_field='dept',
            user_field='created_by',
        )
        order_qs = PurchaseOrder.objects.filter(
            purchase_scope,
            supplier=supplier,
        ).exclude(status='CANCELLED')

        total_orders = order_qs.count()
        total_amount = order_qs.aggregate(total=Sum('total_amount'))['total'] or 0
        total_quantity = order_qs.aggregate(total=Sum('total_quantity'))['total'] or 0
        completed_orders = order_qs.filter(status='RECEIVED').count()
        pending_orders = order_qs.exclude(status='RECEIVED').count()

        by_status = dict(
            order_qs.values('status').annotate(count=Count('id')).values_list('status', 'count')
        )

        recent_orders = list(
            order_qs.order_by('-created_at').values(
                'id',
                'purchase_order_no',
                'status',
                'order_date',
                'expected_arrival_date',
                'total_quantity',
                'total_amount',
            )[:10]
        )

        top_products = list(
            PurchaseOrderItem.objects.filter(
                purchase_order__in=order_qs
            ).values(
                'product_name_snapshot',
                'product_code_snapshot',
            ).annotate(
                qty=Sum('quantity'),
                received_qty=Sum('received_quantity'),
                amount=Sum('amount'),
            ).order_by('-amount')[:10]
        )

        by_month = list(
            order_qs.annotate(month=TruncMonth('order_date'))
            .values('month')
            .annotate(
                count=Count('id'),
                amount=Sum('total_amount'),
            )
            .order_by('-month')[:12]
        )

        return Response({
            'summary': {
                'total_orders': total_orders,
                'completed_orders': completed_orders,
                'pending_orders': pending_orders,
                'total_amount': total_amount,
                'total_quantity': total_quantity,
                'completion_rate': round((completed_orders / total_orders) * 100, 2) if total_orders else 0,
            },
            'by_status': by_status,
            'recent_orders': recent_orders,
            'top_products': top_products,
            'by_month': by_month,
        })

class SupplierContactViewSet(viewsets.ModelViewSet):
    module_key = MODULE_KEY
    queryset = SupplierContact.objects.all()
    serializer_class = SupplierContactSerializer

class SupplierFollowRecordViewSet(viewsets.ModelViewSet):
    module_key = MODULE_KEY
    queryset = SupplierFollowRecord.objects.all()
    serializer_class = SupplierFollowRecordSerializer

    def perform_create(self, serializer):
        supplier = serializer.validated_data['supplier']
        if supplier.status == 'BLACKLIST':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("黑名单供应商禁止跟进")
        serializer.save(
            **build_erp_user_fk_kwargs(
                SupplierFollowRecord,
                user=self.request.user,
                field_names=("created_by",),
            ),
        )

class SupplierEvaluationViewSet(viewsets.ModelViewSet):
    module_key = MODULE_KEY
    queryset = SupplierEvaluation.objects.all()
    serializer_class = SupplierEvaluationSerializer

    def perform_create(self, serializer):
        supplier = serializer.validated_data["supplier"]
        policy = get_policy("supplier", user=self.request.user)
        if not policy.rating_enabled():
            from rest_framework.exceptions import ValidationError
            raise ValidationError("当前配置未启用供应商评级")
        serializer.save(
            **build_erp_user_fk_kwargs(
                SupplierEvaluation,
                user=self.request.user,
                field_names=("evaluated_by",),
            ),
        )

class SupplierTagViewSet(viewsets.ModelViewSet):
    module_key = MODULE_KEY
    queryset = SupplierTag.objects.all()
    serializer_class = SupplierTagSerializer

class SupplierAttachmentViewSet(viewsets.ModelViewSet):
    module_key = MODULE_KEY
    queryset = SupplierAttachment.objects.all()
    serializer_class = SupplierAttachmentSerializer

    def perform_create(self, serializer):
        policy = get_policy("supplier", user=self.request.user)
        if not policy.attachment_enabled():
            from rest_framework.exceptions import ValidationError
            raise ValidationError("当前配置未启用供应商附件")
        serializer.save(
            **build_erp_user_fk_kwargs(
                SupplierAttachment,
                user=self.request.user,
                field_names=("uploaded_by",),
            ),
        )
