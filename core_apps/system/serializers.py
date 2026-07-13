import json
from django.apps import apps
from rest_framework import serializers

from .models import OperationLog


MODULE_LABELS = {
    "accounting": "财务会计",
    "ap-payable": "应付管理",
    "ar-receivable": "应收管理",
    "crm": "客户管理",
    "erp-auth": "系统管理",
    "finance": "资金管理",
    "inventory": "库存管理",
    "org": "组织架构",
    "platform": "基础设置",
    "purchase": "采购管理",
    "reports": "经营报表",
    "sales": "销售管理",
    "supplier": "供应商管理",
    "supply-chain": "供应链管理",
    "system": "系统管理",
}

# 路径是日志长期保存的稳定信息，因此在这里统一把 API 资源翻译成业务名称。
# 新增会产生写日志的资源时，应同步补充此表和对应测试，避免页面回退成技术路径。
RESOURCE_LABELS = {
    ("accounting", "periods"): "会计期间",
    ("accounting", "posting-logs"): "业务过账记录",
    ("accounting", "subjects"): "会计科目",
    ("accounting", "vouchers"): "会计凭证",
    ("ap-payable", "accounts"): "应付账款",
    ("ap-payable", "allocations"): "付款分摊",
    ("ap-payable", "payments"): "付款单",
    ("ap-payable", "refunds"): "供应商退款单",
    ("ar-receivable", "receipts"): "收款单",
    ("ar-receivable", "receivables"): "应收账款",
    ("ar-receivable", "refunds"): "客户退款单",
    ("ar-receivable", "write-offs"): "应收核销单",
    ("crm", "attachments"): "客户附件",
    ("crm", "contacts"): "客户联系人",
    ("crm", "customers"): "客户",
    ("crm", "follow-records"): "客户跟进记录",
    ("crm", "tags"): "客户标签",
    ("erp-auth", "change-password"): "登录密码",
    ("erp-auth", "data-permissions"): "数据权限",
    ("erp-auth", "departments"): "部门",
    ("erp-auth", "permissions"): "功能权限",
    ("erp-auth", "roles"): "角色",
    ("erp-auth", "users"): "用户",
    ("finance", "cash-accounts"): "资金账户",
    ("finance", "export-tasks"): "资金报表导出任务",
    ("inventory", "attachments"): "商品附件",
    ("inventory", "categories"): "商品分类",
    ("inventory", "images"): "商品图片",
    ("inventory", "inventories"): "库存",
    ("inventory", "products"): "商品",
    ("inventory", "stocktakes"): "盘点单",
    ("inventory", "tags"): "商品标签",
    ("inventory", "transactions"): "库存流水",
    ("inventory", "units"): "计量单位",
    ("inventory", "warehouses"): "仓库",
    ("org", "departments"): "部门",
    ("platform", "code-rules"): "编码规则",
    ("platform", "dict"): "业务字典",
    ("platform", "files"): "文件",
    ("purchase", "orders"): "采购订单",
    ("purchase", "receipts"): "采购入库单",
    ("reports", "export"): "报表",
    ("sales", "orders"): "销售订单",
    ("supplier", "attachments"): "供应商附件",
    ("supplier", "contacts"): "供应商联系人",
    ("supplier", "evaluations"): "供应商评价",
    ("supplier", "follow-records"): "供应商跟进记录",
    ("supplier", "suppliers"): "供应商",
    ("supplier", "tags"): "供应商标签",
    ("supply-chain", "alerts"): "库存预警",
    ("supply-chain", "outbound-orders"): "销售出库单",
    ("supply-chain", "purchase-returns"): "采购退货单",
    ("supply-chain", "sales-returns"): "销售退货单",
    ("supply-chain", "trace"): "库存追溯",
    ("supply-chain", "transfer-orders"): "仓库调拨单",
    ("system", "logs"): "操作日志",
}

NESTED_RESOURCE_LABELS = {
    ("erp-auth", "data-permissions", "grants"): "特殊数据授权",
    ("platform", "dict", "items"): "字典项",
    ("platform", "dict", "types"): "字典类型",
    ("purchase", "orders", "attachments"): "采购订单附件",
}

ACTION_LABELS = {
    "add_items": "添加明细",
    "adjust": "调整",
    "allocate": "分配库存",
    "approve": "审核通过",
    "archive": "归档",
    "cancel": "取消",
    "change_password": "修改",
    "clear_data": "清空",
    "close": "关闭",
    "complete": "完成",
    "confirm": "确认",
    "create_outbound": "生成出库单",
    "deactivate": "停用",
    "delete": "删除",
    "disable": "停用",
    "enable": "启用",
    "execute": "执行",
    "export": "导出",
    "generate": "生成",
    "import_data": "导入",
    "init_defaults": "初始化",
    "init_subjects": "初始化",
    "open": "重新打开",
    "post": "过账",
    "reactivate": "重新启用",
    "reapply_version": "重新应用配置到",
    "reject": "审核驳回",
    "remove": "删除",
    "reset_initial_admin_password": "重置初始管理员密码",
    "reset_password": "重置密码",
    "resolve": "处理",
    "retry": "重试",
    "scan": "扫描",
    "ship": "生成出库单",
    "start": "开始",
    "submit": "提交",
    "test": "测试",
    "transfer": "转移",
    "update_items": "录入明细",
    "upload": "上传",
    "upload_attachment": "上传附件到",
    "write_off": "核销",
}

# 少数动作不能用“动作 + 当前资源”准确表达，在这里给出完整业务句子。
ACTION_SUMMARY_OVERRIDES = {
    ("accounting", "periods", "close"): "关闭会计期间（关账）",
    ("accounting", "periods", "open"): "重新打开会计期间（反关账）",
    ("accounting", "subjects", "init_subjects"): "初始化会计科目",
    ("ar-receivable", "receivables", "generate"): "生成应收账款",
    ("inventory", "inventories", "adjust"): "调整库存数量",
    ("inventory", "stocktakes", "add_items"): "添加盘点明细",
    ("inventory", "stocktakes", "update_items"): "录入盘点结果",
    ("platform", "code-rules", "generate"): "生成业务编号",
    ("platform", "code-rules", "init_defaults"): "初始化默认编码规则",
    ("platform", "code-rules", "test"): "测试编码规则",
    ("purchase", "receipts", "complete"): "执行采购入库",
    ("purchase", "orders", "upload_attachment"): "上传采购订单附件",
    ("reports", "export", "export"): "导出经营报表",
    ("sales", "orders", "create_outbound"): "根据销售订单生成出库单",
    ("sales", "orders", "ship"): "根据销售订单生成出库单",
    ("supply-chain", "alerts", "resolve"): "处理库存预警",
    ("supply-chain", "alerts", "scan"): "扫描库存预警",
    ("supply-chain", "outbound-orders", "complete"): "完成销售出库",
    ("supply-chain", "purchase-returns", "complete"): "完成采购退货",
    ("supply-chain", "sales-returns", "complete"): "完成销售退货",
    ("supply-chain", "transfer-orders", "complete"): "完成仓库调拨",
    ("supply-chain", "transfer-orders", "start"): "开始仓库调拨",
}

RESOURCE_MODEL_LABELS = {
    ("accounting", "periods"): ("accounting", "AccountingPeriod"),
    ("accounting", "subjects"): ("accounting", "AccountSubject"),
    ("accounting", "vouchers"): ("accounting", "Voucher"),
    ("ap-payable", "accounts"): ("ap_payable", "APAccount"),
    ("ap-payable", "allocations"): ("ap_payable", "APAllocation"),
    ("ap-payable", "payments"): ("ap_payable", "APPayment"),
    ("ap-payable", "refunds"): ("ap_payable", "SupplierRefund"),
    ("ar-receivable", "receipts"): ("ar_receivable", "Receipt"),
    ("ar-receivable", "receivables"): ("ar_receivable", "Receivable"),
    ("ar-receivable", "refunds"): ("ar_receivable", "CustomerRefund"),
    ("ar-receivable", "write-offs"): ("ar_receivable", "WriteOff"),
    ("crm", "attachments"): ("crm", "CustomerAttachment"),
    ("crm", "contacts"): ("crm", "Contact"),
    ("crm", "customers"): ("crm", "Customer"),
    ("crm", "follow-records"): ("crm", "FollowRecord"),
    ("crm", "tags"): ("crm", "CustomerTag"),
    ("erp-auth", "departments"): ("erp_auth", "ERPDepartment"),
    ("erp-auth", "roles"): ("erp_auth", "ERPRole"),
    ("erp-auth", "users"): ("erp_auth", "ERPUser"),
    ("finance", "cash-accounts"): ("finance", "CashAccount"),
    ("inventory", "attachments"): ("inventory", "ProductAttachment"),
    ("inventory", "categories"): ("inventory", "ProductCategory"),
    ("inventory", "images"): ("inventory", "ProductImage"),
    ("inventory", "inventories"): ("inventory", "Inventory"),
    ("inventory", "products"): ("inventory", "Product"),
    ("inventory", "stocktakes"): ("inventory", "Stocktake"),
    ("inventory", "tags"): ("inventory", "ProductTag"),
    ("inventory", "transactions"): ("inventory", "InventoryTransaction"),
    ("inventory", "units"): ("inventory", "Unit"),
    ("inventory", "warehouses"): ("inventory", "Warehouse"),
    ("platform", "code-rules"): ("platform", "CodeRule"),
    ("platform", "files"): ("platform", "File"),
    ("purchase", "orders"): ("purchase", "PurchaseOrder"),
    ("purchase", "receipts"): ("purchase", "PurchaseReceipt"),
    ("sales", "orders"): ("sales", "SalesOrder"),
    ("supplier", "attachments"): ("supplier", "SupplierAttachment"),
    ("supplier", "contacts"): ("supplier", "SupplierContact"),
    ("supplier", "evaluations"): ("supplier", "SupplierEvaluation"),
    ("supplier", "follow-records"): ("supplier", "SupplierFollowRecord"),
    ("supplier", "suppliers"): ("supplier", "Supplier"),
    ("supplier", "tags"): ("supplier", "SupplierTag"),
    ("supply-chain", "alerts"): ("supply_chain", "InventoryAlert"),
    ("supply-chain", "outbound-orders"): ("supply_chain", "OutboundOrder"),
    ("supply-chain", "purchase-returns"): ("supply_chain", "PurchaseReturnOrder"),
    ("supply-chain", "sales-returns"): ("supply_chain", "SalesReturnOrder"),
    ("supply-chain", "transfer-orders"): ("supply_chain", "TransferOrder"),
}

IGNORED_PARAM_KEYS = {
    "_changes",
    "_changed_fields",
    "_operation_target",
    "csrfmiddlewaretoken",
    "password",
    "old_password",
    "new_password",
    "confirm_password",
    "password_confirm",
}

COMMON_FIELD_LABELS = {
    "access_level": "访问范围",
    "account": "资金账户",
    "address": "地址",
    "amount": "金额",
    "barcode": "条码",
    "brand": "品牌",
    "business_type": "业务类型",
    "city": "城市",
    "code": "编码",
    "comment": "审核意见",
    "contact": "联系人",
    "content": "内容",
    "country": "国家",
    "customer": "客户",
    "date": "日期",
    "department": "部门",
    "dept": "部门",
    "description": "说明",
    "email": "邮箱",
    "enabled": "启用状态",
    "end_date": "结束日期",
    "file": "文件",
    "file_name": "文件名",
    "industry": "行业",
    "items": "商品明细",
    "mobile": "手机",
    "module": "所属模块",
    "name": "名称",
    "order": "单据",
    "permissions": "功能权限",
    "permission_ids": "功能权限",
    "phone": "手机号",
    "product": "商品",
    "province": "省份",
    "quantity": "数量",
    "reason": "原因",
    "remark": "备注",
    "resource_code": "数据资源",
    "resources": "数据权限配置",
    "role": "角色",
    "roles": "角色",
    "role_ids": "角色",
    "short_name": "简称",
    "specification": "规格型号",
    "start_date": "开始日期",
    "status": "状态",
    "supplier": "供应商",
    "tenant": "租户",
    "type": "类型",
    "user": "用户",
    "warehouse": "仓库",
    "website": "网址",
}


def _split_path(path: str) -> list[str]:
    return [segment for segment in (path or "").strip("/").split("/") if segment]


def _normalize_slug(segment: str) -> str:
    return (segment or "").strip().replace("-", "_")


def _resolve_resource(path: str) -> tuple[tuple[str, str] | None, str]:
    segments = _split_path(path)
    if len(segments) < 3:
        return None, "系统操作"
    module_key, resource_key = segments[1], segments[2]
    if len(segments) >= 4:
        nested_label = NESTED_RESOURCE_LABELS.get((module_key, resource_key, segments[3]))
        if nested_label:
            return (module_key, resource_key), nested_label
    if len(segments) >= 5:
        nested_label = NESTED_RESOURCE_LABELS.get((module_key, resource_key, segments[4]))
        if nested_label:
            return (module_key, resource_key), nested_label
    key = (module_key, resource_key)
    label = RESOURCE_LABELS.get(key)
    if label:
        return key, label
    return key, f"{MODULE_LABELS.get(module_key, '系统')}相关数据"


def _resolve_action(resource_key: tuple[str, str] | None, path: str) -> str | None:
    segments = _split_path(path)
    if not segments:
        return None
    action_key = _normalize_slug(segments[-1])
    if action_key in ACTION_LABELS:
        return action_key
    if resource_key and (*resource_key, action_key) in ACTION_SUMMARY_OVERRIDES:
        return action_key
    return None


def _resolve_model(path: str):
    resource_key, _ = _resolve_resource(path)
    app_model = RESOURCE_MODEL_LABELS.get(resource_key)
    if not app_model:
        return None
    app_label, model_name = app_model
    return apps.get_model(app_label, model_name)


def _load_json_object(text: str | None):
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError):
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
    params = _load_json_object(params_text)
    if not params:
        return ""
    labels = _field_label_map(path)
    stored_changes = params.get("_changes")
    if isinstance(stored_changes, list):
        change_summaries = []
        for change in stored_changes:
            if not isinstance(change, dict):
                continue
            field_name = change.get("field")
            if not isinstance(field_name, str) or field_name in IGNORED_PARAM_KEYS:
                continue
            label = labels.get(field_name, "其他内容")
            old_value = change.get("old")
            new_value = change.get("new")
            if old_value is None or old_value == "":
                change_summaries.append(f"{label}改为“{new_value}”")
            else:
                change_summaries.append(f"{label}由“{old_value}”改为“{new_value}”")
        if change_summaries:
            return "，" + "；".join(change_summaries)

    field_labels = []
    stored_changed_fields = params.get("_changed_fields")
    field_names = stored_changed_fields if isinstance(stored_changed_fields, list) else params.keys()
    for key in field_names:
        if not isinstance(key, str):
            continue
        if key in IGNORED_PARAM_KEYS or key == "id":
            continue
        if key.endswith("_ids"):
            base_key = key[:-4]
            label = labels.get(base_key) or labels.get(key) or "关联内容"
            field_labels.append(f"{label}关联")
            continue
        label = labels.get(key)
        if label:
            field_labels.append(label)
        elif isinstance(params.get(key), list):
            field_labels.append("明细内容")
        else:
            field_labels.append("其他内容")
    if not field_labels:
        return ""
    deduped = list(dict.fromkeys(field_labels))
    if len(deduped) <= 3:
        return "，涉及" + "、".join(deduped)
    return "，涉及" + "、".join(deduped[:3]) + f"等{len(deduped)}项内容"


def _operation_target(params_text: str | None) -> str:
    target = _load_json_object(params_text).get("_operation_target")
    if not isinstance(target, (str, int)) or not str(target).strip():
        return ""
    return str(target).strip()[:100]


def _first_error_message(value, labels: dict[str, str]) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            message = _first_error_message(item, labels)
            if message:
                return message
        return ""
    if isinstance(value, dict):
        preferred_keys = ("detail", "message", "error", "non_field_errors")
        for key in preferred_keys:
            if key in value:
                message = _first_error_message(value[key], labels)
                if message:
                    return message
        for key, item in value.items():
            message = _first_error_message(item, labels)
            if message:
                return f"{labels.get(key, '填写内容')}：{message}"
    return ""


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
        return _resolve_resource(obj.path)[1]

    def get_operation_summary(self, obj):
        resource_key, resource_label = _resolve_resource(obj.path)
        action_key = _resolve_action(resource_key, obj.path)
        target = _operation_target(obj.params)
        target_summary = f"：{target}" if target else ""
        if action_key:
            override = ACTION_SUMMARY_OVERRIDES.get((*resource_key, action_key)) if resource_key else None
            summary = override or f"{ACTION_LABELS[action_key]}{resource_label}"
            return f"{summary}{target_summary}"

        if obj.method == "POST":
            action = "新建"
        elif obj.method in {"PUT", "PATCH"}:
            action = "修改"
        elif obj.method == "DELETE":
            action = "删除"
        elif obj.method == "GET":
            action = "查看"
        else:
            action = "处理"
        details = _summarize_changed_fields(obj.path, obj.params) if obj.method in {"POST", "PUT", "PATCH"} else ""
        return f"{action}{resource_label}{target_summary}{details}"

    def get_result_summary(self, obj):
        if 200 <= obj.status_code < 300:
            return "操作已完成"
        reason = _first_error_message(_load_json_object(obj.response), _field_label_map(obj.path))
        if reason:
            return f"未完成：{reason}"
        if 400 <= obj.status_code < 500:
            return "未完成，请检查权限或填写内容"
        return "系统处理失败，请联系管理员"

    def get_technical_summary(self, obj):
        return f"{obj.method.upper()} {obj.path}"
