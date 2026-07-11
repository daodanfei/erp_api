import re
import json

from django.apps import apps

from rest_framework import serializers

from .models import OperationLog

RESOURCE_LABELS = {
    ("inventory", "products"): "商品",
    ("crm", "customers"): "客户",
    ("supplier", "suppliers"): "供应商",
    ("purchase", "orders"): "采购订单",
    ("sales", "orders"): "销售订单",
    ("system", "logs"): "操作日志",
}

ACTION_LABELS = {
    "submit": "提交",
    "approve": "审核",
    "confirm": "确认",
    "post": "过账",
    "complete": "完成",
    "close": "关闭",
    "open": "启用",
    "disable": "停用",
    "enable": "启用",
    "delete": "删除",
    "remove": "删除",
    "cancel": "取消",
    "execute": "执行",
    "reset-password": "重置密码",
    "reset_initial_admin_password": "重置初始管理员密码",
    "reset-initial-admin-password": "重置初始管理员密码",
}

RESOURCE_MODEL_LABELS = {
    ("inventory", "products"): ("inventory", "Product"),
    ("crm", "customers"): ("crm", "Customer"),
    ("supplier", "suppliers"): ("supplier", "Supplier"),
    ("purchase", "orders"): ("purchase", "PurchaseOrder"),
    ("sales", "orders"): ("sales", "SalesOrder"),
}

IGNORED_PARAM_KEYS = {
    "csrfmiddlewaretoken",
}

COMMON_FIELD_LABELS = {
    "name": "名称",
    "short_name": "简称",
    "phone": "手机号",
    "mobile": "手机",
    "email": "邮箱",
    "website": "网址",
    "country": "国家",
    "province": "省份",
    "city": "城市",
    "address": "地址",
    "remark": "备注",
    "status": "状态",
    "industry": "行业",
    "brand": "品牌",
    "barcode": "条码",
    "specification": "规格型号",
}


def _split_path(path: str) -> list[str]:
    return [segment for segment in (path or "").strip("/").split("/") if segment]


def _humanize_action(segment: str) -> str:
    action = ACTION_LABELS.get(segment)
    if action:
        return action
    return segment.replace("-", " ").replace("_", " ").strip() or "处理"


def _resolve_model(path: str):
    segments = _split_path(path)
    if len(segments) < 3:
        return None
    app_model = RESOURCE_MODEL_LABELS.get((segments[1], segments[2]))
    if not app_model:
        return None
    app_label, model_name = app_model
    return apps.get_model(app_label, model_name)


def _load_params(params_text: str | None):
    if not params_text:
        return {}
    try:
        payload = json.loads(params_text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _field_label_map(path: str) -> dict[str, str]:
    model = _resolve_model(path)
    labels = dict(COMMON_FIELD_LABELS)
    if model is None:
        return labels
    for field in model._meta.fields:
        verbose_name = str(getattr(field, "verbose_name", field.name))
        labels[field.name] = verbose_name if verbose_name != field.name else labels.get(field.name, field.name)
    return labels


def _summarize_changed_fields(path: str, params_text: str | None) -> str:
    params = _load_params(params_text)
    if not params:
        return ""
    labels = _field_label_map(path)
    field_labels = []
    for key in params.keys():
        if key in IGNORED_PARAM_KEYS or key in {"id"}:
            continue
        if key.endswith("_ids"):
            base_key = key[:-4]
            label = labels.get(base_key) or labels.get(key) or key
            field_labels.append(f"{label}关联")
            continue
        label = labels.get(key)
        if label:
            field_labels.append(label)
        elif isinstance(params.get(key), list):
            field_labels.append(f"{key}明细")
        else:
            field_labels.append(key)
    if not field_labels:
        return ""
    deduped = list(dict.fromkeys(field_labels))
    if len(deduped) <= 3:
        return "，涉及" + "、".join(deduped)
    return "，涉及" + "、".join(deduped[:3]) + f"等{len(deduped)}项内容"


class OperationLogSerializer(serializers.ModelSerializer):
    operator_name = serializers.SerializerMethodField()
    resource_label = serializers.SerializerMethodField()
    operation_summary = serializers.SerializerMethodField()
    result_summary = serializers.SerializerMethodField()
    technical_summary = serializers.SerializerMethodField()

    class Meta:
        model = OperationLog
        fields = [
            "id",
            "tenant",
            "erp_user",
            "path",
            "method",
            "params",
            "response",
            "status_code",
            "ip",
            "browser",
            "execution_time",
            "created_at",
            "operator_name",
            "resource_label",
            "operation_summary",
            "result_summary",
            "technical_summary",
        ]

    def get_operator_name(self, obj):
        if obj.erp_user:
            return obj.erp_user.name or obj.erp_user.username
        return "系统"

    def get_resource_label(self, obj):
        segments = _split_path(obj.path)
        if len(segments) < 3:
            return "业务数据"
        return RESOURCE_LABELS.get((segments[1], segments[2]), "业务数据")

    def get_operation_summary(self, obj):
        segments = _split_path(obj.path)
        resource_label = self.get_resource_label(obj)
        last_segment = segments[-1] if segments else ""
        second_last_segment = segments[-2] if len(segments) >= 2 else ""
        if (
            obj.method == "POST"
            and len(segments) >= 5
            and re.fullmatch(r"\d+", second_last_segment)
            and not re.fullmatch(r"\d+", last_segment)
        ):
            action = _humanize_action(last_segment)
        elif obj.method == "POST":
            action = "新建"
        elif obj.method in {"PUT", "PATCH"}:
            action = "修改"
        elif obj.method == "DELETE":
            action = "删除"
        elif obj.method == "GET":
            action = "查看"
        else:
            action = "处理"
        details = ""
        if obj.method in {"POST", "PUT", "PATCH"}:
            details = _summarize_changed_fields(obj.path, obj.params)
        return f"{action}{resource_label}{details}"

    def get_result_summary(self, obj):
        if 200 <= obj.status_code < 300:
            return "已成功完成"
        if 400 <= obj.status_code < 500:
            return "未成功，请检查权限或填写内容"
        return "执行失败，请稍后重试"

    def get_technical_summary(self, obj):
        method_label = obj.method.upper()
        return f"{method_label} {obj.path}"
