from django.apps import AppConfig

class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_apps.inventory'

    def ready(self):
        import business_apps.inventory.signals
