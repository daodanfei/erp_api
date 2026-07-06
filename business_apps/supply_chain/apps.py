from django.apps import AppConfig


class SupplyChainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_apps.supply_chain'
    verbose_name = '供应链执行'

    def ready(self):
        import business_apps.supply_chain.signals  # noqa: F401
