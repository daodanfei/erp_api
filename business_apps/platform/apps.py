from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_apps.platform'
    verbose_name = '平台基础设施'
