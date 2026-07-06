from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import ERPUser


class ERPJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        if validated_token.get("user_scope") != "erp":
            return None

        return self.get_user(validated_token), validated_token

    def get_user(self, validated_token):
        user_id = validated_token.get("user_id")
        if not user_id:
            raise exceptions.AuthenticationFailed("ERP token missing user_id", code="token_not_valid")

        try:
            user = ERPUser.objects.select_related("tenant").prefetch_related("roles").get(pk=user_id)
        except ERPUser.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("ERP user not found", code="user_not_found") from exc

        if not user.status:
            raise exceptions.AuthenticationFailed("ERP user inactive", code="user_inactive")
        if user.tenant.status != "ACTIVE":
            raise exceptions.AuthenticationFailed("Tenant inactive", code="tenant_inactive")
        if user.tenant_id != validated_token.get("tenant_id"):
            raise exceptions.AuthenticationFailed("Tenant mismatch", code="tenant_mismatch")
        return user
