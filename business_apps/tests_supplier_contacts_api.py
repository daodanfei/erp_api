from types import SimpleNamespace
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from business_apps.supplier.models import Supplier, SupplierContact
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant


class SupplierContactPermissionApiTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="supplier-contact-tenant", name="Supplier Contact Tenant", status="ACTIVE")
        self.dept = ERPDepartment.objects.create(tenant=self.tenant, name="采购部")
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="supplier_contact_user",
            password="password",
            dept=self.dept,
            must_change_password=False,
        )
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code="SUP-001",
            supplier_name="测试供应商",
            owner=self.user,
            dept=self.dept,
            created_by=self.user,
            status="ACTIVE",
        )
        self.contact = SupplierContact.objects.create(
            tenant=self.tenant,
            supplier=self.supplier,
            name="原联系人",
            mobile="13800000000",
            is_primary=True,
            sort=0,
        )
        self.client.force_authenticate(self.user)

    def _runtime_config(self):
        return SimpleNamespace(is_enabled=lambda module_key: module_key == "supplier")

    def _permission_patch(self, allowed_codes: set[str]):
        return patch(
            "core_apps.common.permissions.has_erp_role_permission",
            side_effect=lambda user, code: code in allowed_codes,
        )

    def test_create_contact_requires_create_permission(self):
        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"supplier:supplier:view"}):
                forbidden = self.client.post(
                    "/api/supplier/contacts/",
                    {"supplier": self.supplier.id, "name": "新联系人", "mobile": "13900000000", "sort": 1},
                    format="json",
                )
                self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

            with self._permission_patch({"supplier:supplier:view", "supplier:contact:create"}):
                allowed = self.client.post(
                    "/api/supplier/contacts/",
                    {"supplier": self.supplier.id, "name": "新联系人", "mobile": "13900000000", "sort": 1},
                    format="json",
                )
                self.assertEqual(allowed.status_code, status.HTTP_201_CREATED, allowed.data)
                self.assertTrue(SupplierContact.objects.filter(supplier=self.supplier, name="新联系人").exists())

    def test_update_contact_requires_update_permission(self):
        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"supplier:supplier:view"}):
                forbidden = self.client.put(
                    f"/api/supplier/contacts/{self.contact.id}/",
                    {"supplier": self.supplier.id, "name": "已修改联系人", "mobile": "13700000000", "is_primary": False, "sort": 2},
                    format="json",
                )
                self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

            with self._permission_patch({"supplier:supplier:view", "supplier:contact:update"}):
                allowed = self.client.put(
                    f"/api/supplier/contacts/{self.contact.id}/",
                    {"supplier": self.supplier.id, "name": "已修改联系人", "mobile": "13700000000", "is_primary": False, "sort": 2},
                    format="json",
                )
                self.assertEqual(allowed.status_code, status.HTTP_200_OK, allowed.data)
                self.contact.refresh_from_db()
                self.assertEqual(self.contact.name, "已修改联系人")

    def test_delete_contact_requires_delete_permission(self):
        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"supplier:supplier:view"}):
                forbidden = self.client.delete(f"/api/supplier/contacts/{self.contact.id}/")
                self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
                self.assertTrue(SupplierContact.objects.filter(pk=self.contact.id).exists())

            with self._permission_patch({"supplier:supplier:view", "supplier:contact:delete"}):
                allowed = self.client.delete(f"/api/supplier/contacts/{self.contact.id}/")
                self.assertEqual(allowed.status_code, status.HTTP_204_NO_CONTENT, allowed.data)
                self.assertFalse(SupplierContact.objects.filter(pk=self.contact.id).exists())
