from django.core.management.base import BaseCommand

from business_apps.inventory.models import Unit
from business_apps.inventory.services import UnitService


class Command(BaseCommand):
    help = "初始化常用计量单位"

    def handle(self, *args, **options):
        before_count = Unit.objects.count()
        created_units = UnitService.init_common_units()
        after_count = Unit.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"常用计量单位初始化完成：新增 {len(created_units)} 个，当前共 {after_count} 个。"
            )
        )
        if before_count == after_count and not created_units:
            self.stdout.write("常用计量单位已存在，无需重复创建。")
