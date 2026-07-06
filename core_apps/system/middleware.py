import time
import json
from django.utils.deprecation import MiddlewareMixin
from core_apps.authentication.models import User as PlatformUser
from core_apps.system.models import OperationLog

class OperationLogMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        request.start_time = time.time()

    def process_response(self, request, response):
        user = getattr(request, "user", None)
        if hasattr(request, 'start_time') and getattr(user, "is_authenticated", False):
            if not isinstance(user, PlatformUser):
                return response
            # Only log non-GET requests or specific paths if needed
            if request.method != 'GET' or '/api/system/' in request.path:
                duration = (time.time() - request.start_time) * 1000
                
                try:
                    params = json.loads(request.body) if request.body else {}
                except:
                    params = request.POST.dict()

                # Sensitive data masking
                if 'password' in params:
                    params['password'] = '******'

                OperationLog.objects.create(
                    user=user,
                    path=request.path,
                    method=request.method,
                    params=json.dumps(params),
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
