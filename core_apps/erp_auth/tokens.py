from rest_framework_simplejwt.tokens import RefreshToken


class ERPRefreshToken(RefreshToken):
    @classmethod
    def for_user(cls, user):
        token = super().for_user(user)
        token["user_scope"] = "erp"
        token["tenant_id"] = user.tenant_id
        token["tenant_code"] = user.tenant.code
        token["username"] = user.username
        return token

