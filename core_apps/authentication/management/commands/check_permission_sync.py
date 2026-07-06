from django.core.management.base import BaseCommand, CommandError

from core_apps.authentication.models import Permission, Role

import seed_menu


class Command(BaseCommand):
    help = "检查模块 manifest 中定义的权限是否已同步到数据库，并确认 admin 角色仅拥有平台权限。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="发现缺失时自动执行 seed_menu.seed_data() 聚合同步模块权限。",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        report = self._collect_report()

        if self._is_synced(report):
            self.stdout.write(self.style.SUCCESS(self._format_success(report)))
            return

        self.stdout.write(self.style.WARNING(self._format_report(report)))

        if not apply_changes:
            raise CommandError("模块 manifest 与数据库权限不同步，请执行 `python manage.py check_permission_sync --apply`。")

        self.stdout.write("Applying permission sync via seed_menu.seed_data() ...")
        seed_menu.seed_data()
        refreshed = self._collect_report()

        if not self._is_synced(refreshed):
            self.stdout.write(self.style.WARNING(self._format_report(refreshed)))
            raise CommandError("自动同步后仍存在权限差异，请检查模块 manifest 和数据库状态。")

        self.stdout.write(self.style.SUCCESS(self._format_success(refreshed)))

    def _collect_report(self):
        defined_codes = self._load_defined_codes()
        platform_admin_codes = self._load_platform_admin_codes()
        db_codes = set(Permission.objects.values_list("code", flat=True))

        admin_role = Role.objects.filter(code="admin").first()
        admin_codes = (
            set(admin_role.permissions.values_list("code", flat=True))
            if admin_role
            else set()
        )

        missing_in_db = sorted(defined_codes - db_codes)
        extra_in_db = sorted(db_codes - defined_codes)
        missing_on_admin_role = sorted(platform_admin_codes - admin_codes) if admin_role else sorted(platform_admin_codes)
        unexpected_on_admin_role = sorted(admin_codes - platform_admin_codes) if admin_role else []

        return {
            "defined_count": len(defined_codes),
            "platform_admin_count": len(platform_admin_codes),
            "db_count": len(db_codes),
            "admin_count": len(admin_codes),
            "admin_role_exists": admin_role is not None,
            "missing_in_db": missing_in_db,
            "extra_in_db": extra_in_db,
            "missing_on_admin_role": missing_on_admin_role,
            "unexpected_on_admin_role": unexpected_on_admin_role,
        }

    def _load_defined_codes(self):
        return seed_menu.get_defined_permission_codes()

    def _load_platform_admin_codes(self):
        return seed_menu.get_platform_admin_permission_codes()

    def _is_synced(self, report):
        return (
            report["admin_role_exists"]
            and not report["missing_in_db"]
            and not report["missing_on_admin_role"]
            and not report["unexpected_on_admin_role"]
        )

    def _format_success(self, report):
        return (
            "Permission sync OK. "
            f"defined={report['defined_count']}, "
            f"platform_admin={report['platform_admin_count']}, "
            f"db={report['db_count']}, "
            f"admin_role_permissions={report['admin_count']}."
        )

    def _format_report(self, report):
        lines = [
            "Permission sync check failed:",
            f"- defined in module manifests: {report['defined_count']}",
            f"- platform admin permission codes: {report['platform_admin_count']}",
            f"- permissions in db: {report['db_count']}",
            f"- permissions on admin role: {report['admin_count']}",
        ]
        if not report["admin_role_exists"]:
            lines.append("- admin role is missing")
        if report["missing_in_db"]:
            lines.append(
                "- missing in db: " + ", ".join(report["missing_in_db"])
            )
        if report["missing_on_admin_role"]:
            lines.append(
                "- missing on admin role: " + ", ".join(report["missing_on_admin_role"])
            )
        if report["unexpected_on_admin_role"]:
            lines.append(
                "- unexpected on admin role: " + ", ".join(report["unexpected_on_admin_role"])
            )
        if report["extra_in_db"]:
            lines.append(
                "- extra in db but not defined in module manifests: "
                + ", ".join(report["extra_in_db"])
            )
        return "\n".join(lines)
