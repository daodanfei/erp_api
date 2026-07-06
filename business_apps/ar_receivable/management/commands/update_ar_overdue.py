from django.core.management.base import BaseCommand
from django.utils import timezone

from business_apps.ar_receivable.models import Receivable


class Command(BaseCommand):
    help = '扫描当前逾期应收账款数量'

    def handle(self, *args, **options):
        today = timezone.now().date()
        count = Receivable.objects.filter(
            is_deleted=False,
            due_date__lt=today,
            status__in=['UNPAID', 'PARTIAL_PAID'],
        ).count()
        self.stdout.write(self.style.SUCCESS(f'当前逾期应收记录 {count} 条'))
