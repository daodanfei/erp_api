import hashlib
import os
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings


class FileService:
    """统一文件服务"""

    @staticmethod
    def compute_md5(file_obj):
        """计算文件MD5"""
        md5 = hashlib.md5()
        for chunk in file_obj.chunks():
            md5.update(chunk)
        return md5.hexdigest()

    @staticmethod
    def check_duplicate(md5):
        """MD5去重检查，返回已有文件或None"""
        from .models import File
        return File.objects.filter(md5=md5, is_deleted=False).first()

    @staticmethod
    @transaction.atomic
    def upload(file_obj, module, business_type, business_id, uploaded_by, access_level='BUSINESS'):
        """上传文件（支持去重）"""
        from .models import File

        file_name = file_obj.name
        file_ext = os.path.splitext(file_name)[1].lower()
        mime_type = getattr(file_obj, 'content_type', '') or ''
        file_size = file_obj.size

        # 计算MD5（需要先读取文件内容，之后seek回开头）
        md5 = FileService.compute_md5(file_obj)
        file_obj.seek(0)  # 重置文件指针，否则后续保存时读到空内容

        # 存储文件
        storage_type = getattr(settings, 'FILE_STORAGE_TYPE', 'LOCAL')
        file_url, object_key, bucket = FileService._save_file(file_obj, module, md5, file_ext)

        file_record = File.objects.create(
            file_name=file_name,
            file_ext=file_ext,
            mime_type=mime_type,
            file_size=file_size,
            storage_type=storage_type,
            bucket=bucket,
            object_key=object_key,
            file_url=file_url,
            md5=md5,
            module=module,
            business_type=business_type,
            business_id=business_id,
            access_level=access_level,
            uploaded_by=uploaded_by,
        )
        return file_record

    @staticmethod
    def _save_file(file_obj, module, md5, file_ext):
        """保存文件到存储，返回 (file_url, object_key, bucket)"""
        storage_type = getattr(settings, 'FILE_STORAGE_TYPE', 'LOCAL')

        if storage_type == 'MINIO':
            return FileService._save_to_minio(file_obj, module, md5, file_ext)
        elif storage_type == 'S3':
            return FileService._save_to_s3(file_obj, module, md5, file_ext)
        else:
            return FileService._save_to_local(file_obj, module, md5, file_ext)

    @staticmethod
    def _save_to_local(file_obj, module, md5, file_ext):
        """本地存储"""
        now = timezone.now()
        date_path = now.strftime('%Y/%m/%d')
        file_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', module, date_path)
        os.makedirs(file_dir, exist_ok=True)

        # 用MD5前8位+时间戳避免冲突
        short_md5 = md5[:8] if md5 else ''
        file_name = f"{short_md5}_{now.strftime('%H%M%S')}{file_ext}"
        file_path = os.path.join(file_dir, file_name)

        with open(file_path, 'wb+') as destination:
            for chunk in file_obj.chunks():
                destination.write(chunk)

        file_url = f"/media/uploads/{module}/{date_path}/{file_name}"
        return file_url, f"uploads/{module}/{date_path}/{file_name}", ''

    @staticmethod
    def _save_to_minio(file_obj, module, md5, file_ext):
        """MinIO存储"""
        try:
            from minio import Minio
            minio_config = getattr(settings, 'MINIO_CONFIG', {})
            client = Minio(
                minio_config.get('ENDPOINT', 'localhost:9000'),
                access_key=minio_config.get('ACCESS_KEY', 'minioadmin'),
                secret_key=minio_config.get('SECRET_KEY', 'minioadmin'),
                secure=minio_config.get('SECURE', False),
            )
            bucket = minio_config.get('BUCKET', 'erp-files')
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

            now = timezone.now()
            object_key = f"uploads/{module}/{now.strftime('%Y/%m/%d')}/{md5[:8]}_{now.strftime('%H%M%S')}{file_ext}"
            client.put_object(bucket, object_key, file_obj, file_obj.size,
                              content_type=getattr(file_obj, 'content_type', ''))

            file_url = f"{minio_config.get('EXTERNAL_URL', '')}/{bucket}/{object_key}"
            return file_url, object_key, bucket
        except ImportError:
            # minio包未安装，降级到本地存储
            return FileService._save_to_local(file_obj, module, md5, file_ext)

    @staticmethod
    def _save_to_s3(file_obj, module, md5, file_ext):
        """S3存储"""
        try:
            import boto3
            s3_config = getattr(settings, 'S3_CONFIG', {})
            s3 = boto3.client('s3',
                              endpoint_url=s3_config.get('ENDPOINT_URL'),
                              aws_access_key_id=s3_config.get('ACCESS_KEY'),
                              aws_secret_access_key=s3_config.get('SECRET_KEY'),
                              region_name=s3_config.get('REGION', 'us-east-1'))
            bucket = s3_config.get('BUCKET', 'erp-files')
            now = timezone.now()
            object_key = f"uploads/{module}/{now.strftime('%Y/%m/%d')}/{md5[:8]}_{now.strftime('%H%M%S')}{file_ext}"
            s3.upload_fileobj(file_obj, bucket, object_key)

            file_url = f"https://{bucket}.s3.{s3_config.get('REGION', 'us-east-1')}.amazonaws.com/{object_key}"
            return file_url, object_key, bucket
        except ImportError:
            return FileService._save_to_local(file_obj, module, md5, file_ext)

    @staticmethod
    @transaction.atomic
    def delete(file_id, user):
        """软删除文件"""
        from .models import File
        file = File.objects.get(id=file_id)
        file.is_deleted = True
        file.save()
        return file

    @staticmethod
    def get_business_files(module, business_type, business_id):
        """获取业务对象关联的文件列表"""
        from .models import File
        return File.objects.filter(
            module=module, business_type=business_type,
            business_id=business_id, is_deleted=False,
        )

    @staticmethod
    def can_preview(file_ext):
        """判断文件是否可预览"""
        previewable = ['.pdf', '.jpg', '.jpeg', '.png', '.webp', '.txt', '.gif', '.bmp']
        return file_ext.lower() in previewable


class DictionaryService:
    """统一字典服务"""

    CACHE_PREFIX = 'dict:'
    CACHE_TIMEOUT = 3600  # 1小时缓存

    @staticmethod
    def get_items(dict_code, status='ACTIVE'):
        """获取字典项列表（优先走缓存）"""
        cache_key = f'{DictionaryService.CACHE_PREFIX}{dict_code}'
        cached = cache.get(cache_key)
        if cached is not None:
            if status == 'ACTIVE':
                return [item for item in cached if item['status'] == 'ACTIVE']
            return cached

        from .models import DictType, DictItem
        try:
            dict_type = DictType.objects.get(dict_code=dict_code)
        except DictType.DoesNotExist:
            return []

        items = DictItem.objects.filter(dict_type=dict_type).order_by('sort', 'id')
        data = [{
            'id': item.id,
            'item_code': item.item_code,
            'item_name': item.item_name,
            'item_value': item.item_value,
            'color': item.color,
            'sort': item.sort,
            'status': item.status,
        } for item in items]

        cache.set(cache_key, data, DictionaryService.CACHE_TIMEOUT)
        if status == 'ACTIVE':
            return [item for item in data if item['status'] == 'ACTIVE']
        return data

    @staticmethod
    def get_item_name(dict_code, item_code):
        """获取字典项名称"""
        items = DictionaryService.get_items(dict_code)
        for item in items:
            if item['item_code'] == item_code:
                return item['item_name']
        return item_code

    @staticmethod
    def get_choices(dict_code):
        """获取Django choices格式 [(code, name), ...]"""
        items = DictionaryService.get_items(dict_code)
        return [(item['item_code'], item['item_name']) for item in items]

    @staticmethod
    def clear_cache(dict_code=None):
        """清除字典缓存"""
        if dict_code:
            cache.delete(f'{DictionaryService.CACHE_PREFIX}{dict_code}')
        else:
            from .models import DictType
            for dt in DictType.objects.all():
                cache.delete(f'{DictionaryService.CACHE_PREFIX}{dt.dict_code}')

    @staticmethod
    @transaction.atomic
    def create_or_update_type(dict_code, dict_name, remark='', items=None, created_by=None):
        """创建或更新字典分类+项"""
        from .models import DictType, DictItem
        dict_type, created = DictType.objects.update_or_create(
            dict_code=dict_code,
            defaults={'dict_name': dict_name, 'remark': remark, 'created_by': created_by}
        )
        if items:
            for idx, item_data in enumerate(items):
                DictItem.objects.update_or_create(
                    dict_type=dict_type,
                    item_code=item_data['code'],
                    defaults={
                        'item_name': item_data['name'],
                        'item_value': item_data.get('value', ''),
                        'color': item_data.get('color', ''),
                        'sort': item_data.get('sort', idx),
                        'status': item_data.get('status', 'ACTIVE'),
                    }
                )
        # 清除缓存
        DictionaryService.clear_cache(dict_code)
        return dict_type


class CodeRuleService:
    """统一编码规则服务（并发安全）"""

    DEFAULT_RULES = [
        ('SALES_ORDER', '销售订单', 'SO', '%Y%m%d', 4, 'DAY'),
        ('PURCHASE_ORDER', '采购订单', 'PO', '%Y%m%d', 4, 'DAY'),
        ('PURCHASE_RECEIPT', '采购入库单', 'PR', '%Y%m%d', 4, 'DAY'),
        ('OUTBOUND_ORDER', '销售出库单', 'OB', '%Y%m%d', 4, 'DAY'),
        ('TRANSFER_ORDER', '调拨单', 'TF', '%Y%m%d', 4, 'DAY'),
        ('SALES_RETURN', '销售退货单', 'SR', '%Y%m%d', 4, 'DAY'),
        ('PURCHASE_RETURN', '采购退货单', 'PRT', '%Y%m%d', 4, 'DAY'),
        ('CUSTOMER_CODE', '客户编码', 'CUS', '%Y%m', 4, 'MONTH'),
        ('SUPPLIER_CODE', '供应商编码', 'SUP', '%Y%m', 4, 'MONTH'),
        ('PRODUCT_CODE', '商品编码', 'PRO', '%Y%m', 4, 'MONTH'),
        ('UNIT_CODE', '计量单位编码', 'UNIT', '', 4, 'NEVER'),
        ('WAREHOUSE_CODE', '仓库编码', 'WH', '', 4, 'NEVER'),
        ('INVENTORY_TRANSACTION', '库存流水', 'TRX', '%Y%m%d%H%M%S', 4, 'NEVER'),
        ('SHIPMENT', '发货单', 'SHP', '%Y%m%d%H%M%S', 4, 'NEVER'),
        ('STOCKTAKE', '盘点单', 'STK', '%Y%m%d%H%M%S', 4, 'NEVER'),
        ('AR_ACCOUNT', '应收账款', 'AR', '%Y%m%d', 4, 'DAY'),
        ('AR_RECEIPT', '收款单', 'RC', '%Y%m%d', 4, 'DAY'),
        ('AP_ACCOUNT', '应付账款', 'AP', '%Y%m%d', 4, 'DAY'),
        ('AP_PAYMENT', '付款单', 'PAY', '%Y%m%d', 4, 'DAY'),
        ('AP_ALLOCATION', '付款核销单', 'APA', '%Y%m%d', 4, 'DAY'),
        ('ACCOUNTING_VOUCHER', '会计凭证', 'V', '%Y%m%d', 4, 'DAY'),
    ]

    @staticmethod
    def ensure_default_rule(rule_code, created_by=None):
        from .models import CodeRule

        defaults = {
            code: {
                'rule_name': name,
                'prefix': prefix,
                'date_format': date_fmt,
                'sequence_length': seq_len,
                'reset_type': reset_type,
                'created_by': created_by,
            }
            for code, name, prefix, date_fmt, seq_len, reset_type in CodeRuleService.DEFAULT_RULES
        }
        if rule_code not in defaults:
            return None
        rule, created = CodeRule.objects.get_or_create(rule_code=rule_code, defaults=defaults[rule_code])
        if not created:
            changed_fields = []
            for field, value in defaults[rule_code].items():
                if field == 'created_by':
                    continue
                if getattr(rule, field) in (None, ''):
                    setattr(rule, field, value)
                    changed_fields.append(field)
            if rule.status != 'ACTIVE':
                rule.status = 'ACTIVE'
                changed_fields.append('status')
            if changed_fields:
                rule.save(update_fields=changed_fields)
        return rule

    @staticmethod
    @transaction.atomic
    def generate(rule_code):
        """
        生成编号（行级锁保证并发安全）
        用法: CodeRuleService.generate('SALES_ORDER') -> 'SO20260615000001'
        """
        from .models import CodeRule

        # select_for_update 行级锁；内置规则缺失时自动补齐，避免新环境未初始化导致业务接口 500。
        try:
            rule = CodeRule.objects.select_for_update().get(rule_code=rule_code, status='ACTIVE')
        except CodeRule.DoesNotExist:
            CodeRuleService.ensure_default_rule(rule_code)
            rule = CodeRule.objects.select_for_update().get(rule_code=rule_code, status='ACTIVE')

        now = timezone.now()
        # 计算日期键
        if rule.reset_type == 'DAY':
            date_key = now.strftime('%Y%m%d')
        elif rule.reset_type == 'MONTH':
            date_key = now.strftime('%Y%m')
        elif rule.reset_type == 'YEAR':
            date_key = now.strftime('%Y')
        else:  # NEVER
            date_key = 'NEVER'

        # 判断是否需要重置序号
        if rule.current_date_key != date_key:
            rule.current_sequence = 0
            rule.current_date_key = date_key

        # 递增序号
        rule.current_sequence += 1
        rule.save()

        # 格式化日期部分
        if rule.date_format:
            date_part = now.strftime(rule.date_format)
        else:
            date_part = ''

        # 格式化序号
        seq_str = str(rule.current_sequence).zfill(rule.sequence_length)

        return f"{rule.prefix}{date_part}{seq_str}"

    @staticmethod
    def test_generate(rule):
        """测试生成（不修改数据库）"""
        now = timezone.now()
        if rule.date_format:
            date_part = now.strftime(rule.date_format)
        else:
            date_part = ''
        seq_str = str(rule.current_sequence + 1).zfill(rule.sequence_length)
        return f"{rule.prefix}{date_part}{seq_str}"

    @staticmethod
    def init_default_rules(created_by=None):
        """初始化默认编码规则"""
        from .models import CodeRule
        for rule_code, name, prefix, date_fmt, seq_len, reset_type in CodeRuleService.DEFAULT_RULES:
            CodeRule.objects.get_or_create(
                rule_code=rule_code,
                defaults={
                    'rule_name': name,
                    'prefix': prefix,
                    'date_format': date_fmt,
                    'sequence_length': seq_len,
                    'reset_type': reset_type,
                    'created_by': created_by,
                }
            )
