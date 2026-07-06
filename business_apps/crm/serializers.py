from rest_framework import serializers
from .models import Customer, Contact, FollowRecord, CustomerTag, CustomerAttachment, TransferLog

class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'

class FollowRecordSerializer(serializers.ModelSerializer):
    creator_name = serializers.CharField(source='created_by.username', read_only=True)
    class Meta:
        model = FollowRecord
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at')

class CustomerTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTag
        fields = '__all__'

class CustomerAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAttachment
        fields = '__all__'

class CustomerSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='owner.username', read_only=True)
    dept_name = serializers.CharField(source='dept.name', read_only=True)
    tags = CustomerTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(many=True, queryset=CustomerTag.objects.all(), source='tags', write_only=True, required=False)

    class Meta:
        model = Customer
        fields = '__all__'
        read_only_fields = ('customer_code', 'owner', 'dept', 'created_by', 'is_deleted', 'deleted_at', 'deleted_by')

class TransferLogSerializer(serializers.ModelSerializer):
    old_owner_name = serializers.CharField(source='old_owner.username', read_only=True)
    new_owner_name = serializers.CharField(source='new_owner.username', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    class Meta:
        model = TransferLog
        fields = '__all__'
