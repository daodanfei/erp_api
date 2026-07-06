from rest_framework import serializers
from .models import Supplier, SupplierContact, SupplierFollowRecord, SupplierTag, SupplierAttachment, SupplierEvaluation, SupplierTransferLog

class SupplierContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierContact
        fields = '__all__'

class SupplierFollowRecordSerializer(serializers.ModelSerializer):
    creator_name = serializers.CharField(source='created_by.username', read_only=True)
    class Meta:
        model = SupplierFollowRecord
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at')

class SupplierTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierTag
        fields = '__all__'

class SupplierAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierAttachment
        fields = '__all__'

class SupplierEvaluationSerializer(serializers.ModelSerializer):
    evaluated_by_name = serializers.CharField(source='evaluated_by.username', read_only=True)
    average_score = serializers.ReadOnlyField()
    class Meta:
        model = SupplierEvaluation
        fields = '__all__'

class SupplierSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='owner.username', read_only=True)
    dept_name = serializers.CharField(source='dept.name', read_only=True)
    tags = SupplierTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=SupplierTag.objects.all(), source='tags', write_only=True, required=False)
    attachments = SupplierAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Supplier
        fields = '__all__'
        read_only_fields = ('supplier_code', 'owner', 'dept', 'created_by', 'is_deleted', 'deleted_at', 'deleted_by')

class SupplierTransferLogSerializer(serializers.ModelSerializer):
    old_owner_name = serializers.CharField(source='old_owner.username', read_only=True)
    new_owner_name = serializers.CharField(source='new_owner.username', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    class Meta:
        model = SupplierTransferLog
        fields = '__all__'
