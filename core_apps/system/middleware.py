import time
import json

from django.utils.deprecation import MiddlewareMixin

from core_apps.erp_auth.models import ERPUser
from core_apps.system.models import OperationLog


def _extract_request_payload(request):
    try:
        return json.loads(request.body) if request.body else {}
    except Exception:
        return request.POST.dict()


def _mask_sensitive_fields(params):
    if not isinstance(params, dict):
        return params
    masked = dict(params)
    if "password" in masked:
        masked["password"] = "******"
    return masked


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

    def process_response(self, request, response):
        user = getattr(request, "user", None)
        if hasattr(request, 'start_time') and getattr(user, "is_authenticated", False):
            if not isinstance(user, ERPUser):
                return response
            # ERP 端仅记录会产生业务意义的操作，避免把普通浏览行为刷满日志。
            if request.method != 'GET':
                duration = (time.time() - request.start_time) * 1000

                params = _mask_sensitive_fields(_extract_request_payload(request))

                OperationLog.objects.create(
                    tenant=user.tenant,
                    erp_user=user,
                    path=_normalize_logged_path(request, response),
                    method=request.method,
                    params=json.dumps(params, ensure_ascii=False, default=str),
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
