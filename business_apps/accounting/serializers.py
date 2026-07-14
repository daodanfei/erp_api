from rest_framework import serializers

from .models import (
    AccountSubject,
    AccountingPeriod,
    Voucher,
    VoucherLine,
    BusinessPostingLog,
)


class AccountSubjectSerializer(serializers.ModelSerializer):
    parent_code = serializers.CharField(source="parent.code", read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True)

    class Meta:
        model = AccountSubject
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "created_at", "updated_at")


class AccountingPeriodSerializer(serializers.ModelSerializer):
    closed_by_name = serializers.CharField(source="closed_by.username", read_only=True)

    class Meta:
        model = AccountingPeriod
        fields = "__all__"
        read_only_fields = ("tenant", "closed_at", "closed_by", "created_at", "updated_at")


class VoucherLineSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)

    class Meta:
        model = VoucherLine
        fields = "__all__"


class VoucherSerializer(serializers.ModelSerializer):
    lines = VoucherLineSerializer(many=True, read_only=True)
    period_label = serializers.SerializerMethodField()
    posted_by_name = serializers.CharField(source="posted_by.username", read_only=True)

    class Meta:
        model = Voucher
        fields = "__all__"

    def get_period_label(self, obj):
        return str(obj.period)


class BusinessPostingLogSerializer(serializers.ModelSerializer):
    voucher_no = serializers.CharField(source="voucher.voucher_no", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = BusinessPostingLog
        fields = "__all__"
