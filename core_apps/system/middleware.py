import time
import json

from django.core.exceptions import DisallowedHost
from django.http import HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin

from core_apps.erp_auth.models import ERPUser
from core_apps.system.models import OperationLog
from core_apps.system.operation_log import (
    MAX_OPERATION_LOG_CHANGES,
    OPERATION_CHANGED_FIELDS_PARAM,
    OPERATION_CHANGES_PARAM,
    OPERATION_TARGET_PARAM,
    is_sensitive_operation_log_field,
)


MAX_LOGGED_REQUEST_BODY_BYTES = 64 * 1024
MAX_LOGGED_CHANGED_FIELDS = 100
IDENTITY_FIELD_PAIRS = (
    ("product_code", "name"),
    ("customer_code", "customer_name"),
    ("supplier_code", "supplier_name"),
    ("warehouse_code", "warehouse_name"),
    ("code", "name"),
)
IDENTITY_FIELD_NAMES = (
    "order_no",
    "purchase_order_no",
    "receipt_no",
    "receivable_no",
    "ap_no",
    "payment_no",
    "refund_no",
    "write_off_no",
    "voucher_no",
    "stocktake_no",
    "outbound_no",
    "transfer_no",
    "return_no",
    "transaction_no",
    "product_code",
    "customer_code",
    "supplier_code",
    "warehouse_code",
    "customer_name",
    "supplier_name",
    "product_name",
    "warehouse_name",
    "account_name",
    "file_name",
    "username",
    "name",
    "code",
)


class InvalidHostMiddleware:
    """Reject invalid Host headers without raising a noisy security exception."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            request.get_host()
        except DisallowedHost:
            return HttpResponseBadRequest()
        return self.get_response(request)


def _extract_request_payload(request):
    captured_payload = getattr(request, "operation_log_request_payload", None)
    if captured_payload is not None:
        return captured_payload
    try:
        return json.loads(request.body) if request.body else {}
    except Exception:
        return request.POST.dict()


def _capture_request_payload(request):
    if request.method == "GET":
        return None
    content_type = (request.META.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None
    try:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length > MAX_LOGGED_REQUEST_BODY_BYTES:
        return {}
    try:
        body = request.body
        if len(body) > MAX_LOGGED_REQUEST_BODY_BYTES:
            return {}
        payload = json.loads(body) if body else {}
        return payload if isinstance(payload, (dict, list)) else {}
    except (TypeError, ValueError):
        return {}


def _mask_sensitive_fields(params):
    if isinstance(params, list):
        return [_mask_sensitive_fields(item) for item in params]
    if not isinstance(params, dict):
        return params
    masked = {}
    for key, value in params.items():
        if _is_sensitive_field_name(key):
            masked[key] = "******"
        else:
            masked[key] = _mask_sensitive_fields(value)
    return masked


def _is_sensitive_field_name(field_name):
    return is_sensitive_operation_log_field(field_name)


def _build_operation_log_params(payload, operation_target="", changed_fields=None, changes=None):
    params = {}
    if changes is not None:
        safe_changes = []
        for change in changes[:MAX_OPERATION_LOG_CHANGES]:
            if not isinstance(change, dict):
                continue
            field_name = change.get("field")
            if not field_name or _is_sensitive_field_name(field_name):
                continue
            safe_changes.append({
                "field": str(field_name),
                "old": str(change.get("old", ""))[:100],
                "new": str(change.get("new", ""))[:100],
            })
        if safe_changes:
            params[OPERATION_CHANGES_PARAM] = safe_changes
    elif changed_fields is None and isinstance(payload, dict):
        changed_fields = [
            str(key)
            for key in payload
            if not _is_sensitive_field_name(key) and not str(key).startswith("_")
        ][:MAX_LOGGED_CHANGED_FIELDS]
    elif changed_fields is None and isinstance(payload, list) and payload:
        changed_fields = ["items"]
    if changed_fields:
        params[OPERATION_CHANGED_FIELDS_PARAM] = [str(field_name) for field_name in changed_fields][
            :MAX_LOGGED_CHANGED_FIELDS
        ]
    if operation_target:
        params[OPERATION_TARGET_PARAM] = operation_target
    return params


def _compact_response_value(value, *, depth=0):
    if depth >= 3:
        return "内容较多，已省略"
    if isinstance(value, dict):
        return {
            str(key): _compact_response_value(item, depth=depth + 1)
            for key, item in list(value.items())[:10]
        }
    if isinstance(value, (list, tuple)):
        return [_compact_response_value(item, depth=depth + 1) for item in list(value)[:3]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def _extract_error_response(response):
    if response.status_code < 400:
        return None
    response_data = getattr(response, "data", None)
    if response_data is None:
        return None
    return _mask_sensitive_fields(_compact_response_value(response_data))


def _identity_from_mapping(data):
    if not isinstance(data, dict):
        return ""
    for code_field, name_field in IDENTITY_FIELD_PAIRS:
        code = data.get(code_field)
        name = data.get(name_field)
        if code is not None and name is not None and str(code).strip() and str(name).strip():
            return f"{str(code).strip()}（{str(name).strip()}）"[:100]
    for field_name in IDENTITY_FIELD_NAMES:
        value = data.get(field_name)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:100]
    return ""


def _identity_from_instance(instance):
    if instance is None:
        return ""
    field_names = {field.name for field in instance._meta.fields}
    for code_field, name_field in IDENTITY_FIELD_PAIRS:
        if code_field not in field_names or name_field not in field_names:
            continue
        code = getattr(instance, code_field, None)
        name = getattr(instance, name_field, None)
        if code is not None and name is not None and str(code).strip() and str(name).strip():
            return f"{str(code).strip()}（{str(name).strip()}）"[:100]
    for field_name in IDENTITY_FIELD_NAMES:
        if field_name not in field_names:
            continue
        value = getattr(instance, field_name, None)
        if value is not None and str(value).strip():
            return str(value).strip()[:100]
    return ""


def _extract_operation_target(request, response, user):
    response_target = (
        _identity_from_mapping(getattr(response, "data", None))
        if response.status_code < 400
        else ""
    )
    if response_target:
        return response_target

    view_class = getattr(request, "operation_log_view_class", None)
    view_kwargs = getattr(request, "operation_log_view_kwargs", {})
    object_id = view_kwargs.get("pk") if isinstance(view_kwargs, dict) else None
    queryset = getattr(view_class, "queryset", None)
    model = getattr(queryset, "model", None)
    if model is None or object_id is None:
        return ""
    try:
        object_queryset = model._default_manager.filter(pk=object_id)
        if any(field.name == "tenant" for field in model._meta.fields):
            object_queryset = object_queryset.filter(tenant=user.tenant)
        return _identity_from_instance(object_queryset.first())
    except Exception:
        # 日志补充信息不能影响业务请求本身。
        return ""


def _normalize_logged_path(request, response):
    path = request.path
    if request.method != "POST" or not (200 <= response.status_code < 300):
        return path
    trimmed = path.rstrip("/")
    if not trimmed:
        return path
    if trimmed.split("/")[-1].isdigit():
        return path
    response_data = getattr(response, "data", None)
    if isinstance(response_data, dict):
        object_id = response_data.get("id")
        if object_id is not None:
            return f"{trimmed}/{object_id}/"
    return path


class OperationLogMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        request.start_time = time.time()
        request.operation_log_request_payload = _capture_request_payload(request)
        request.operation_log_view_class = getattr(view_func, "cls", None)
        request.operation_log_view_kwargs = view_kwargs

    def process_response(self, request, response):
        user = getattr(request, "user", None)
        if hasattr(request, 'start_time') and getattr(user, "is_authenticated", False):
            if not isinstance(user, ERPUser):
                return response
            # ERP 端仅记录会产生业务意义的操作，避免把普通浏览行为刷满日志。
            if request.method != 'GET':
                duration = (time.time() - request.start_time) * 1000

                request_payload = _extract_request_payload(request)
                operation_target = _extract_operation_target(request, response, user)
                params = _build_operation_log_params(
                    request_payload,
                    operation_target,
                    changed_fields=getattr(request, "operation_log_changed_fields", None),
                    changes=getattr(request, "operation_log_changes", None),
                )
                error_response = _extract_error_response(response)

                OperationLog.objects.create(
                    tenant=user.tenant,
                    erp_user=user,
                    path=_normalize_logged_path(request, response),
                    method=request.method,
                    params=json.dumps(params, ensure_ascii=False, default=str),
                    response=(
                        json.dumps(error_response, ensure_ascii=False, default=str)
                        if error_response is not None
                        else None
                    ),
                    status_code=response.status_code,
                    ip=self.get_client_ip(request),
                    browser=request.META.get('HTTP_USER_AGENT', ''),
                    execution_time=duration
                )
        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
