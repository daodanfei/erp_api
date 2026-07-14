from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework import status
from rest_framework.test import APITestCase

from core_apps.authentication.models import Permission, Role, User


class UserApiTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="root",
            password="rootpass123",
            email="root@example.com",
        )
        self.user_menu_permission = Permission.objects.create(
            name="用户管理",
            code="system:user",
            type="MENU",
        )
        self.user_create_permission = Permission.objects.create(
            name="创建用户",
            code="user:create",
            type="BUTTON",
        )
        self.user_update_permission = Permission.objects.create(
            name="编辑用户",
            code="user:update",
            type="BUTTON",
        )
        self.user_delete_permission = Permission.objects.create(
            name="删除用户",
            code="user:delete",
            type="BUTTON",
        )
        self.admin_role = Role.objects.create(name="超级管理员", code="admin", data_scope="ALL")
        self.admin_role.permissions.add(
            self.user_menu_permission,
            self.user_create_permission,
            self.user_update_permission,
            self.user_delete_permission,
        )
        self.admin.roles.add(self.admin_role)
        self.role = Role.objects.create(name="测试角色", code="test_role")
        self.client.force_authenticate(self.admin)

    def test_create_user_can_login_with_password(self):
        create_response = self.client.post(
            "/api/auth/users/",
            {
                "username": "admin2",
                "password": "admin123",
                "first_name": "lzx",
                "role_ids": [self.role.id],
                "status": True,
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        created_user = User.objects.get(username="admin2")
        self.assertTrue(created_user.check_password("admin123"))

        self.client.force_authenticate(user=None)
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": "admin2", "password": "admin123"},
            format="json",
        )

        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", login_response.data)
        self.assertIn("refresh", login_response.data)

    def test_create_user_requires_password(self):
        response = self.client.post(
            "/api/auth/users/",
            {
                "username": "nopassword",
                "first_name": "lzx",
                "role_ids": [self.role.id],
                "status": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)


class PermissionSyncCommandTest(APITestCase):
    def setUp(self):
        self.admin_role = Role.objects.create(name="超级管理员", code="admin", data_scope="ALL")
        self.platform_permission = Permission.objects.create(
            name="角色管理",
            code="system:role",
            type="MENU",
        )
        self.business_permission = Permission.objects.create(
            name="查看财务看板",
            code="finance:dashboard:view",
            type="BUTTON",
        )

    def test_check_permission_sync_reports_missing_platform_admin_permission(self):
        stdout = StringIO()

        with patch(
            "core_apps.authentication.management.commands.check_permission_sync.Command._load_defined_codes",
            return_value={self.platform_permission.code},
        ):
            with self.assertRaises(CommandError):
                call_command("check_permission_sync", stdout=stdout)

        self.assertIn("missing on admin role", stdout.getvalue())
        self.assertIn("system:role", stdout.getvalue())

    def test_check_permission_sync_ignores_business_permissions_for_admin_role(self):
        self.admin_role.permissions.add(self.platform_permission)
        stdout = StringIO()

        with patch(
            "core_apps.authentication.management.commands.check_permission_sync.Command._load_defined_codes",
            return_value={self.platform_permission.code, self.business_permission.code},
        ):
            with patch(
                "core_apps.authentication.management.commands.check_permission_sync.Command._load_platform_admin_codes",
                return_value={self.platform_permission.code},
            ):
                call_command("check_permission_sync", stdout=stdout)

        self.assertIn("Permission sync OK", stdout.getvalue())

    def test_check_permission_sync_reports_unexpected_business_permissions_on_admin_role(self):
        self.admin_role.permissions.add(self.platform_permission, self.business_permission)
        stdout = StringIO()

        with patch(
            "core_apps.authentication.management.commands.check_permission_sync.Command._load_defined_codes",
            return_value={self.platform_permission.code, self.business_permission.code},
        ):
            with patch(
                "core_apps.authentication.management.commands.check_permission_sync.Command._load_platform_admin_codes",
                return_value={self.platform_permission.code},
            ):
                with self.assertRaises(CommandError):
                    call_command("check_permission_sync", stdout=stdout)

        self.assertIn("unexpected on admin role", stdout.getvalue())
        self.assertIn("finance:dashboard:view", stdout.getvalue())

    def test_check_permission_sync_passes_when_admin_role_has_only_platform_permissions(self):
        self.admin_role.permissions.add(self.platform_permission)
        stdout = StringIO()

        with patch(
            "core_apps.authentication.management.commands.check_permission_sync.Command._load_defined_codes",
            return_value={self.platform_permission.code},
        ):
            with patch(
                "core_apps.authentication.management.commands.check_permission_sync.Command._load_platform_admin_codes",
                return_value={self.platform_permission.code},
            ):
                call_command("check_permission_sync", stdout=stdout)

        self.assertIn("Permission sync OK", stdout.getvalue())

    def test_check_permission_sync_apply_also_refreshes_erp_permissions(self):
        self.admin_role.permissions.add(self.platform_permission)
        stdout = StringIO()

        with patch(
            "core_apps.authentication.management.commands.check_permission_sync.Command._load_defined_codes",
            return_value={self.platform_permission.code},
        ), patch(
            "core_apps.authentication.management.commands.check_permission_sync.Command._load_platform_admin_codes",
            return_value={self.platform_permission.code},
        ), patch("seed_menu.seed_data"), patch(
            "core_apps.authentication.management.commands.check_permission_sync.sync_tenant_super_admin_role_permissions",
            return_value=2,
        ) as sync_erp:
            call_command("check_permission_sync", "--apply", stdout=stdout)

        sync_erp.assert_called_once_with()
        self.assertIn("tenant_super_admin_roles=2", stdout.getvalue())


class RoleApiTest(APITestCase):
    def setUp(self):
        self.role_permission = Permission.objects.create(
            name="角色管理",
            code="system:role",
            type="MENU",
        )
        self.operator_role = Role.objects.create(name="角色管理员", code="role_admin", data_scope="ALL")
        self.operator_role.permissions.add(self.role_permission)
        self.operator = User.objects.create_user(username="role_admin", password="testpass")
        self.operator.roles.add(self.operator_role)
        self.client.force_authenticate(self.operator)

    def test_create_role_generates_code(self):
        response = self.client.post(
            "/api/auth/roles/",
            {"name": "Warehouse Manager", "data_scope": "SELF", "status": True, "code": "manual_code"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        role = Role.objects.get(name="Warehouse Manager")
        self.assertEqual(role.code, "warehouse_manager")
        self.assertEqual(response.data["code"], "warehouse_manager")

    def test_create_role_generates_fallback_code_for_non_ascii_name(self):
        response = self.client.post(
            "/api/auth/roles/",
            {"name": "采购经理", "data_scope": "SELF", "status": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        role = Role.objects.get(name="采购经理")
        self.assertEqual(role.code, "role_0001")

    def test_create_role_ignores_client_code_and_keeps_generated_code_unique(self):
        Role.objects.create(name="Existing Manager", code="warehouse_manager")

        response = self.client.post(
            "/api/auth/roles/",
            {"name": "Warehouse Manager", "data_scope": "SELF", "status": True, "code": "manual_code"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        role = Role.objects.get(name="Warehouse Manager")
        self.assertEqual(role.code, "warehouse_manager_2")
