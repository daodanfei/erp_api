from django.apps import AppConfig


class TenantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core_apps.tenant"

    def ready(self):
        import core_apps.tenant.signals  # noqa: F401
