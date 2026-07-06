from rest_framework_simplejwt.authentication import JWTAuthentication

from .services import TenantService, resolve_user_tenant


class TenantContextMiddleware:
    header_name = "HTTP_X_TENANT_CODE"
    jwt_authenticator = JWTAuthentication()

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.tenant_config = None
        user = self._get_request_user(request)
        if user is not None:
            tenant_code = request.META.get(self.header_name)
            tenant = resolve_user_tenant(user, tenant_code=tenant_code)
            if tenant is not None:
                request.tenant = tenant
                request.tenant_config = TenantService.get_runtime_config(tenant)
        return self.get_response(request)

    def _get_request_user(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return user
        try:
            auth_result = self.jwt_authenticator.authenticate(request)
        except Exception:
            return None
        if not auth_result:
            return None
        user, auth = auth_result
        request.user = user
        request._auth = auth
        return user
