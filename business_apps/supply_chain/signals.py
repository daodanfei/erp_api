from django.db.models.signals import post_save
from django.dispatch import receiver
from business_apps.inventory.models import InventoryTransaction
from .services import InventoryAlertService


@receiver(post_save, sender=InventoryTransaction)
def on_inventory_transaction_created(sender, instance, created, **kwargs):
    """库存流水创建后，自动触发预警扫描"""
    if created:
        try:
            InventoryAlertService.check_and_create_alerts()
        except Exception:
            # 预警扫描失败不影响主业务流程
            pass
