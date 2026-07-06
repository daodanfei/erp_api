import os
import json
from rest_framework import viewsets, status, parsers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.http import FileResponse
from django.conf import settings
from django.db.models import Q

from core_apps.common.permissions import ERPActionPermission
from core_apps.common.authz import has_erp_full_data_scope, has_erp_role_permission
from core_apps.common.viewsets import BaseBusinessViewSet
from .models import File, DictType, DictItem, CodeRule
from .serializers import (
    FileSerializer, FileListSerializer,
    DictTypeSerializer, DictTypeListSerializer, DictItemSerializer,
    CodeRuleSerializer,
)
from .filters import FileFilter, DictTypeFilter, CodeRuleFilter
from .services import FileService, DictionaryService, CodeRuleService
from core_apps.policies.registry import get_policy


def _log_operation(user, action, model_name, obj_id, before=None, after=None):
    """记录操作日志（通过OperationLogMiddleware自动记录API操作，此处记录变更前后值）"""
    try:
        from core_apps.operation_log.models import OperationLog
        OperationLog.objects.create(
            user=user,
            action=action,
            resource_type=model_name,
            resource_id=str(obj_id),
            detail=json.dumps({
                'before': before or {},
                'after': after or {},
            }, ensure_ascii=False, default=str),
        )
    except Exception:
        pass  # 日志记录失败不影响业务


def _check_file_access(file_record, user):
    """检查文件访问权限"""
    if file_record.access_level == 'PUBLIC':
        return True
    if file_record.access_level == 'LOGIN':
        return user.is_authenticated
    # BUSINESS: 继承业务模块权限
    perm_map = {
        'customer': 'crm:customer:view',
        'supplier': 'supplier:supplier:view',
        'product': 'inventory:product:view',
        'purchase': 'purchase:order:view',
        'sales': 'sales:order:view',
        'inventory': 'inventory:inventory:view',
        'supply_chain': 'supply_chain:outbound:view',
        'report': 'reports:dashboard:view',
        'system': 'platform:file:view',
    }
    required_perm = perm_map.get(file_record.module, 'platform:file:view')
    return has_erp_role_permission(user, required_perm)


class PlatformFeatureGuardMixin:
    module_key = "platform"
    feature_key = ""
    feature_error_message = "当前配置未启用该功能"

    def initial(self, request, *args, **kwargs):
        response = super().initial(request, *args, **kwargs)
        policy = get_policy(self.module_key, user=request.user)
        if not policy.is_feature_enabled(self.feature_key, default=True):
            raise ValidationError({"detail": self.feature_error_message})
        return response


# ==================== 文件中心 ====================

class FileViewSet(PlatformFeatureGuardMixin, BaseBusinessViewSet):
    feature_key = "file_center"
    feature_error_message = "当前配置未启用文件中心"
    queryset = File.objects.filter(is_deleted=False)
    serializer_class = FileSerializer
    permission_classes = [IsAuthenticated, ERPActionPermission]
    permission_map = {
        'list': 'platform:file:view',
        'retrieve': 'platform:file:view',
        'upload': 'platform:file:upload',
        'delete': 'platform:file:delete',
        'download': 'platform:file:download',
        'business_files': 'platform:file:view',
    }
    filterset_class = FileFilter
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def get_serializer_class(self):
        if self.action == 'list':
            return FileListSerializer
        return FileSerializer

    def get_queryset(self):
        """数据权限过滤：管理员看全部，普通用户看自己上传的或公开/登录可见的"""
        qs = super().get_queryset()
        role = self.request.user.roles.first()
        if has_erp_full_data_scope(self.request.user) or (role and role.data_scope == 'ALL'):
            return qs
        # 普通用户：自己上传的 + PUBLIC + LOGIN
        return qs.filter(
            Q(uploaded_by=self.request.user) |
            Q(access_level='PUBLIC') |
            Q(access_level='LOGIN')
        )

    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        """文件上传"""
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'detail': '请选择文件'}, status=status.HTTP_400_BAD_REQUEST)

        module = request.data.get('module', 'system')
        business_type = request.data.get('business_type', 'general')
        business_id = int(request.data.get('business_id', 0))
        access_level = request.data.get('access_level', 'BUSINESS')

        file_record = FileService.upload(
            file_obj, module, business_type, business_id,
            uploaded_by=request.user, access_level=access_level,
        )
        _log_operation(request.user, 'UPLOAD', 'File', file_record.id,
                       after={'file_name': file_record.file_name, 'module': module, 'business_type': business_type})
        serializer = FileSerializer(file_record)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='delete')
    def delete(self, request, pk=None):
        """软删除文件"""
        file = self.get_object()
        before = {'file_name': file.file_name, 'is_deleted': False}
        FileService.delete(file.id, request.user)
        _log_operation(request.user, 'DELETE', 'File', file.id,
                       before=before, after={'is_deleted': True})
        return Response({'detail': '删除成功'})

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """文件下载（含权限校验）"""
        file = self.get_object()
        if not _check_file_access(file, request.user):
            return Response({'detail': '无权访问此文件'}, status=status.HTTP_403_FORBIDDEN)

        if file.storage_type == 'LOCAL':
            local_path = os.path.join(settings.MEDIA_ROOT, file.object_key)
            if os.path.exists(local_path):
                response = FileResponse(open(local_path, 'rb'), as_attachment=True, filename=file.file_name)
                return response
            return Response({'detail': '文件不存在'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'url': file.file_url})

    @action(detail=False, methods=['get'], url_path='business')
    def business_files(self, request):
        """获取业务对象关联的文件列表"""
        module = request.query_params.get('module')
        business_type = request.query_params.get('business_type')
        business_id = request.query_params.get('business_id')
        if not all([module, business_type, business_id]):
            return Response({'detail': '缺少参数'}, status=status.HTTP_400_BAD_REQUEST)

        files = FileService.get_business_files(module, business_type, int(business_id))
        serializer = FileListSerializer(files, many=True)
        return Response(serializer.data)


# ==================== 字典中心 ====================

class DictTypeViewSet(PlatformFeatureGuardMixin, BaseBusinessViewSet):
    feature_key = "dict_center"
    feature_error_message = "当前配置未启用字典中心"
    queryset = DictType.objects.all()
    serializer_class = DictTypeSerializer
    permission_classes = [IsAuthenticated, ERPActionPermission]
    permission_map = {
        'list': 'platform:dict:view',
        'retrieve': 'platform:dict:view',
        'create': 'platform:dict:create',
        'update': 'platform:dict:update',
        'destroy': 'platform:dict:delete',
    }
    filterset_class = DictTypeFilter

    def get_serializer_class(self):
        if self.action == 'list':
            return DictTypeListSerializer
        return DictTypeSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        DictionaryService.clear_cache(serializer.instance.dict_code)
        _log_operation(self.request.user, 'CREATE', 'DictType', serializer.instance.id,
                       after=serializer.data)

    def perform_update(self, serializer):
        old_data = DictTypeSerializer(serializer.instance).data
        serializer.save()
        DictionaryService.clear_cache(serializer.instance.dict_code)
        _log_operation(self.request.user, 'UPDATE', 'DictType', serializer.instance.id,
                       before=old_data, after=serializer.data)

    def perform_destroy(self, instance):
        old_data = DictTypeSerializer(instance).data
        DictionaryService.clear_cache(instance.dict_code)
        instance.delete()
        _log_operation(self.request.user, 'DELETE', 'DictType', instance.id, before=old_data)


class DictItemViewSet(PlatformFeatureGuardMixin, BaseBusinessViewSet):
    feature_key = "dict_center"
    feature_error_message = "当前配置未启用字典中心"
    queryset = DictItem.objects.all()
    serializer_class = DictItemSerializer
    permission_classes = [IsAuthenticated, ERPActionPermission]
    permission_map = {
        'list': 'platform:dict:view',
        'retrieve': 'platform:dict:view',
        'create': 'platform:dict:create',
        'update': 'platform:dict:update',
        'destroy': 'platform:dict:delete',
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        dict_type_id = self.request.query_params.get('dict_type_id')
        if dict_type_id:
            queryset = queryset.filter(dict_type_id=dict_type_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save()
        DictionaryService.clear_cache(serializer.instance.dict_type.dict_code)
        _log_operation(self.request.user, 'CREATE', 'DictItem', serializer.instance.id,
                       after=serializer.data)

    def perform_update(self, serializer):
        old_data = DictItemSerializer(serializer.instance).data
        serializer.save()
        DictionaryService.clear_cache(serializer.instance.dict_type.dict_code)
        _log_operation(self.request.user, 'UPDATE', 'DictItem', serializer.instance.id,
                       before=old_data, after=DictItemSerializer(serializer.instance).data)

    def perform_destroy(self, instance):
        old_data = DictItemSerializer(instance).data
        DictionaryService.clear_cache(instance.dict_type.dict_code)
        instance.delete()
        _log_operation(self.request.user, 'DELETE', 'DictItem', instance.id, before=old_data)


class DictItemsByCodeView(PlatformFeatureGuardMixin, APIView):
    """根据字典编码获取字典项（供前端下拉框使用）"""
    feature_key = "dict_center"
    feature_error_message = "当前配置未启用字典中心"
    permission_classes = [IsAuthenticated]

    def get(self, request, dict_code):
        items = DictionaryService.get_items(dict_code)
        return Response(items)


# ==================== 编码规则中心 ====================

class CodeRuleViewSet(PlatformFeatureGuardMixin, BaseBusinessViewSet):
    feature_key = "code_rule_center"
    feature_error_message = "当前配置未启用编码规则中心"
    queryset = CodeRule.objects.all()
    serializer_class = CodeRuleSerializer
    permission_classes = [IsAuthenticated, ERPActionPermission]
    permission_map = {
        'list': 'platform:coderule:view',
        'retrieve': 'platform:coderule:view',
        'create': 'platform:coderule:create',
        'update': 'platform:coderule:update',
        'test': 'platform:coderule:view',
        'generate': 'platform:coderule:view',
    }
    filterset_class = CodeRuleFilter

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        _log_operation(self.request.user, 'CREATE', 'CodeRule', serializer.instance.id,
                       after=serializer.data)

    def perform_update(self, serializer):
        old_data = CodeRuleSerializer(serializer.instance).data
        serializer.save()
        _log_operation(self.request.user, 'UPDATE', 'CodeRule', serializer.instance.id,
                       before=old_data, after=CodeRuleSerializer(serializer.instance).data)

    @action(detail=True, methods=['post'], url_path='test')
    def test(self, request, pk=None):
        """测试生成编号（不修改数据库）"""
        rule = self.get_object()
        result = CodeRuleService.test_generate(rule)
        return Response({'generated': result})

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        """生成编号"""
        rule_code = request.data.get('rule_code')
        if not rule_code:
            return Response({'detail': '缺少rule_code'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            code = CodeRuleService.generate(rule_code)
            return Response({'code': code})
        except CodeRule.DoesNotExist:
            return Response({'detail': f'编码规则 {rule_code} 不存在'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['post'], url_path='init-defaults')
    def init_defaults(self, request):
        """初始化默认编码规则"""
        CodeRuleService.init_default_rules(created_by=request.user)
        return Response({'detail': '默认编码规则已初始化'})
