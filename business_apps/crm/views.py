from rest_framework import status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from core_apps.common.viewsets import BaseBusinessViewSet, ModuleAwareModelViewSet, build_erp_tenant_save_kwargs, validate_erp_related_tenant_scope
from core_apps.common.utils.data_scope import get_data_scope_filter
from core_apps.erp_auth.compat import build_erp_user_and_dept_kwargs, build_erp_user_fk_kwargs
from core_apps.erp_auth.models import ERPUser
from core_apps.policies.registry import get_policy
from .models import Customer, Contact, FollowRecord, CustomerTag, CustomerAttachment, TransferLog
from .serializers import (
    CustomerSerializer, ContactSerializer, FollowRecordSerializer, 
    CustomerReferenceSerializer,
    CustomerTagSerializer, CustomerAttachmentSerializer, TransferLogSerializer
)
from .services import generate_customer_code, check_duplicate, transfer_customer
from .services import CustomerCreditService
from business_apps.sales.models import SalesOrder, SalesOrderItem

MODULE_KEY = "crm"

class CustomerViewSet(BaseBusinessViewSet):
    module_key = MODULE_KEY
    queryset = Customer.objects.filter(is_deleted=False)
    serializer_class = CustomerSerializer
    user_field = 'owner' # BaseBusinessViewSet will use this for data scope filtering
    
    permission_map = {
        'list': 'crm:customer:view',
        'retrieve': 'crm:customer:view',
        'reference_options': 'crm:customer:reference',
        'create': 'crm:customer:create',
        'update': 'crm:customer:update',
        'destroy': 'crm:customer:delete',
        'transfer': 'crm:customer:transfer',
        'sales_statistics': 'crm:customer:view',
        'credit_overview': 'crm:customer:view',
    }
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    def get_serializer_class(self):
        if self.action == 'reference_options':
            return CustomerReferenceSerializer
        return CustomerSerializer

    @action(detail=False, methods=['get'], url_path='reference-options')
    def reference_options(self, request):
        queryset = self.filter_queryset(self.get_queryset()).filter(status='ACTIVE')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        policy = get_policy("crm", user=self.request.user)
        # 1. Duplication check
        errors = check_duplicate(
            self.request.data.get('customer_name'),
            self.request.data.get('phone'),
            self.request.data.get('email'),
            tenant=self.request.user.tenant
        )
        if errors:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": errors})
            
        customer_code = self.request.data.get("customer_code")
        if policy.code_auto_generate_enabled():
            customer_code = generate_customer_code()
        elif not customer_code:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"customer_code": ["请填写客户编码"]})

        extra_values = {}
        if not policy.credit_limit_enabled():
            extra_values["credit_limit"] = 0
            extra_values["credit_control_mode"] = "NONE"

        serializer.save(
            customer_code=customer_code,
            status='INACTIVE' if policy.approval_enabled() else serializer.validated_data.get('status', 'ACTIVE'),
            owner=self.request.user if isinstance(self.request.user, ERPUser) else None,
            **build_erp_tenant_save_kwargs(Customer, user=self.request.user),
            **extra_values,
            **build_erp_user_and_dept_kwargs(Customer, user=self.request.user, user_field="created_by"),
        )

    def perform_update(self, serializer):
        policy = get_policy("crm", user=self.request.user)
        errors = check_duplicate(
            self.request.data.get('customer_name', serializer.instance.customer_name),
            self.request.data.get('phone', serializer.instance.phone),
            self.request.data.get('email', serializer.instance.email),
            exclude_id=serializer.instance.id,
            tenant=self.request.user.tenant
        )
        if errors:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": errors})

        extra_values = {}
        if not policy.credit_limit_enabled():
            extra_values["credit_limit"] = 0
            extra_values["credit_control_mode"] = "NONE"
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(**extra_values)

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        delete_kwargs = build_erp_user_fk_kwargs(
            Customer,
            user=self.request.user,
            field_names=("deleted_by",),
        )
        instance.deleted_by = delete_kwargs.get("deleted_by")
        instance.save()

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        customer = self.get_object()
        policy = get_policy("crm", user=request.user)
        if not policy.transfer_enabled():
            return Response({"detail": "当前配置未启用客户转移"}, status=status.HTTP_400_BAD_REQUEST)
        new_owner_id = request.data.get('new_owner_id')
        remark = request.data.get('remark')
        
        new_owner = ERPUser.objects.get(id=new_owner_id, tenant=request.user.tenant, status=True)
        
        transfer_customer(customer, new_owner, request.user, remark)
        return Response({'status': 'success'})

    @action(detail=True, methods=['get'])
    def contacts(self, request, pk=None):
        customer = self.get_object()
        contacts = customer.contacts.all()
        serializer = ContactSerializer(contacts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def follow_records(self, request, pk=None):
        customer = self.get_object()
        records = customer.follow_records.all().order_by('-created_at')
        serializer = FollowRecordSerializer(records, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='credit-overview')
    def credit_overview(self, request, pk=None):
        customer = self.get_object()
        return Response(CustomerCreditService.get_credit_overview(customer))

    @action(detail=True, methods=['get'], url_path='sales-statistics')
    def sales_statistics(self, request, pk=None):
        customer = self.get_object()
        sales_scope = get_data_scope_filter(
            request.user,
            dept_field='created_by__dept',
            user_field='created_by',
        )
        order_qs = SalesOrder.objects.filter(
            sales_scope,
            customer=customer,
        ).exclude(status='CANCELLED')

        total_orders = order_qs.count()
        total_amount = order_qs.aggregate(total=Sum('total_amount'))['total'] or 0
        total_quantity = order_qs.aggregate(total=Sum('total_quantity'))['total'] or 0
        completed_orders = order_qs.filter(status__in=['SHIPPED', 'CLOSED']).count()
        pending_orders = order_qs.exclude(status__in=['SHIPPED', 'CLOSED']).count()

        by_status = dict(
            order_qs.values('status').annotate(count=Count('id')).values_list('status', 'count')
        )

        recent_orders = list(
            order_qs.order_by('-created_at').values(
                'id',
                'order_no',
                'status',
                'order_date',
                'expected_delivery_date',
                'total_quantity',
                'total_amount',
            )[:10]
        )

        top_products = list(
            SalesOrderItem.objects.filter(
                order__in=order_qs
            ).values(
                'product_name_snapshot',
            ).annotate(
                qty=Sum('quantity'),
                shipped_qty=Sum('shipped_quantity'),
                amount=Sum('amount'),
            ).order_by('-amount')[:10]
        )

        by_month = list(
            order_qs.annotate(month=TruncMonth('order_date'))
            .values('month')
            .annotate(count=Count('id'), amount=Sum('total_amount'))
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

class ContactViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_map = {
        'list': 'crm:customer:view',
        'retrieve': 'crm:customer:view',
        'create': 'crm:contact:create',
        'update': 'crm:contact:update',
        'destroy': 'crm:contact:delete',
    }

    def perform_create(self, serializer):
        customer = serializer.validated_data['customer']
        if customer.status == 'BLACKLIST':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("黑名单客户禁止操作")
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(**build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user))

class FollowRecordViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = FollowRecord.objects.all()
    serializer_class = FollowRecordSerializer

    def perform_create(self, serializer):
        customer = serializer.validated_data['customer']
        policy = get_policy("crm", user=self.request.user)
        if not policy.follow_record_enabled():
            from rest_framework.exceptions import ValidationError
            raise ValidationError("当前配置未启用客户跟进记录")
        if customer.status == 'BLACKLIST':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("黑名单客户禁止跟进")
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(
            **build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user),
            **build_erp_user_fk_kwargs(
                FollowRecord,
                user=self.request.user,
                field_names=("created_by",),
            ),
        )

    def update(self, request, *args, **kwargs):
        return Response({"detail": "跟进记录不可编辑"}, status=status.HTTP_403_FORBIDDEN)

class CustomerTagViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = CustomerTag.objects.all()
    serializer_class = CustomerTagSerializer

class CustomerAttachmentViewSet(ModuleAwareModelViewSet):
    module_key = MODULE_KEY
    queryset = CustomerAttachment.objects.all()
    serializer_class = CustomerAttachmentSerializer

    def perform_create(self, serializer):
        policy = get_policy("crm", user=self.request.user)
        if not policy.attachment_enabled():
            from rest_framework.exceptions import ValidationError
            raise ValidationError("当前配置未启用客户附件")
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(
            **build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user),
            **build_erp_user_fk_kwargs(
                CustomerAttachment,
                user=self.request.user,
                field_names=("uploaded_by",),
            ),
        )
