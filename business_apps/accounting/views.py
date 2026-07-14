from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from core_apps.common.viewsets import (
    ModuleAwareModelViewSet,
    ModuleAwareReadOnlyViewSet,
    validate_erp_related_tenant_scope,
)
from core_apps.common.permissions import ERPActionPermission
from core_apps.policies.registry import get_policy

from .models import AccountSubject, AccountingPeriod, Voucher, BusinessPostingLog
from .serializers import (
    AccountSubjectSerializer,
    AccountingPeriodSerializer,
    VoucherSerializer,
    BusinessPostingLogSerializer,
)
from .services import PeriodService, SubjectInitService


class AccountSubjectViewSet(ModuleAwareModelViewSet):
    module_key = "accounting"
    queryset = AccountSubject.objects.all()
    serializer_class = AccountSubjectSerializer
    permission_classes = [ERPActionPermission]
    filterset_fields = ["category", "enabled", "parent"]
    permission_map = {
        "list": "accounting:subject:view",
        "retrieve": "accounting:subject:view",
        "create": "accounting:subject:create",
        "update": "accounting:subject:update",
        "partial_update": "accounting:subject:update",
        "destroy": "accounting:subject:delete",
        "init_subjects": "accounting:subject:create",
    }

    @action(detail=False, methods=["post"])
    def init_subjects(self, request):
        subjects = SubjectInitService.init_subjects(created_by=request.user)
        serializer = self.get_serializer(subjects, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(
            code=serializer.validated_data.get("code") or SubjectInitService.generate_subject_code(tenant=self.request.user.tenant),
            tenant=self.request.user.tenant,
        )

    def perform_update(self, serializer):
        policy = get_policy("accounting", user=self.request.user)
        if not policy.subject_editable_after_init() and self.get_queryset().exists():
            raise ValidationError("当前配置不允许在科目初始化后修改会计科目")
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        policy = get_policy("accounting", user=self.request.user)
        if not policy.subject_editable_after_init() and self.get_queryset().exists():
            raise ValidationError("当前配置不允许在科目初始化后删除会计科目")
        instance.delete()


class AccountingPeriodViewSet(ModuleAwareModelViewSet):
    module_key = "accounting"
    queryset = AccountingPeriod.objects.all()
    serializer_class = AccountingPeriodSerializer
    permission_classes = [ERPActionPermission]
    filterset_fields = ["year", "month", "status"]
    permission_map = {
        "list": "accounting:period:view",
        "retrieve": "accounting:period:view",
        "create": "accounting:period:create",
        "update": "accounting:period:update",
        "partial_update": "accounting:period:update",
        "destroy": "accounting:period:delete",
        "close": "accounting:period:close",
        "open_period": "accounting:period:open",
    }

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        period = PeriodService.close_period(self.get_object(), request.user)
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"], url_path="open")
    def open_period(self, request, pk=None):
        period = PeriodService.open_period(self.get_object(), request.user)
        return Response(self.get_serializer(period).data)


class VoucherViewSet(ModuleAwareReadOnlyViewSet):
    module_key = "accounting"
    queryset = Voucher.objects.prefetch_related("lines", "lines__subject").select_related("period", "posted_by")
    serializer_class = VoucherSerializer
    permission_classes = [ERPActionPermission]
    filterset_fields = ["voucher_type", "source_type", "source_id", "period", "voucher_date"]
    permission_map = {
        "list": "accounting:voucher:view",
        "retrieve": "accounting:voucher:view",
    }


class BusinessPostingLogViewSet(ModuleAwareReadOnlyViewSet):
    module_key = "accounting"
    queryset = BusinessPostingLog.objects.select_related("voucher", "created_by")
    serializer_class = BusinessPostingLogSerializer
    permission_classes = [ERPActionPermission]
    filterset_fields = ["event_type", "business_type", "business_id", "voucher"]
    permission_map = {
        "list": "accounting:posting_log:view",
        "retrieve": "accounting:posting_log:view",
    }
