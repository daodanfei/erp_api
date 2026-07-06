from rest_framework import serializers
from .models import File, DictType, DictItem, CodeRule


class FileSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.username', read_only=True)
    can_preview = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = '__all__'
        read_only_fields = ('uploaded_by', 'uploaded_at', 'md5', 'is_deleted', 'storage_type', 'bucket', 'object_key')

    def get_can_preview(self, obj):
        from .services import FileService
        return FileService.can_preview(obj.file_ext)


class FileListSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.username', read_only=True)
    can_preview = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = ('id', 'file_name', 'file_ext', 'file_size', 'file_url', 'module',
                  'business_type', 'business_id', 'access_level', 'uploaded_by_name',
                  'uploaded_at', 'can_preview', 'mime_type')

    def get_can_preview(self, obj):
        from .services import FileService
        return FileService.can_preview(obj.file_ext)


class DictItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DictItem
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class DictTypeSerializer(serializers.ModelSerializer):
    items = DictItemSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = DictType
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at')

    def get_item_count(self, obj):
        return obj.items.count()


class DictTypeListSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = DictType
        fields = ('id', 'dict_code', 'dict_name', 'remark', 'status', 'sort', 'item_count', 'created_at')

    def get_item_count(self, obj):
        return obj.items.count()


class CodeRuleSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = CodeRule
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'current_sequence', 'current_date_key')
