from types import SimpleNamespace
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from business_apps.crm.models import Contact, Customer
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant


class CRMContactPermissionApiTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="crm-contact-tenant", name="CRM Contact Tenant", status="ACTIVE")
        self.dept = ERPDepartment.objects.create(tenant=self.tenant, name="销售部")
        self.user = ERPUser.objects.create_user(
            tenant=self.tenant,
            username="crm_contact_user",
            password="password",
            dept=self.dept,
            must_change_password=False,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            customer_code="CRM-CUST-001",
            customer_name="测试客户",
            owner=self.user,
            dept=self.dept,
            created_by=self.user,
            status="ACTIVE",
        )
        self.contact = Contact.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            name="原联系人",
            mobile="13800000000",
            is_primary=True,
        )
        self.client.force_authenticate(self.user)

    def _runtime_config(self):
        return SimpleNamespace(is_enabled=lambda module_key: module_key == "crm")

    def _permission_patch(self, allowed_codes: set[str]):
        return patch(
            "core_apps.common.permissions.has_erp_role_permission",
            side_effect=lambda user, code: code in allowed_codes,
        )

    def test_create_contact_requires_create_permission(self):
        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"crm:customer:view"}):
                forbidden = self.client.post(
                    "/api/crm/contacts/",
                    {
                        "customer": self.customer.id,
                        "name": "新联系人",
                        "mobile": "13900000000",
                    },
                    format="json",
                )
                self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

            with self._permission_patch({"crm:customer:view", "crm:contact:create"}):
                allowed = self.client.post(
                    "/api/crm/contacts/",
                    {
                        "customer": self.customer.id,
                        "name": "新联系人",
                        "mobile": "13900000000",
                    },
                    format="json",
                )
                self.assertEqual(allowed.status_code, status.HTTP_201_CREATED, allowed.data)
                self.assertTrue(Contact.objects.filter(customer=self.customer, name="新联系人").exists())

    def test_customer_search_filters_by_name_phone_and_code(self):
        Customer.objects.create(
            tenant=self.tenant,
            customer_code="CRM-CUST-SEARCH-002",
            customer_name="另一个客户",
            customer_level="B",
            phone="13912345678",
            owner=self.user,
            dept=self.dept,
            created_by=self.user,
            status="ACTIVE",
        )

        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"crm:customer:view"}):
                by_name = self.client.get("/api/crm/customers/", {"search": "测试客户"})
                by_phone = self.client.get("/api/crm/customers/", {"search": "139123"})
                by_code = self.client.get("/api/crm/customers/", {"search": "SEARCH-002"})
                by_level = self.client.get("/api/crm/customers/", {"customer_level": "B"})

        self.assertEqual(by_name.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in by_name.data], [self.customer.id])
        self.assertEqual([row["customer_name"] for row in by_phone.data], ["另一个客户"])
        self.assertEqual([row["customer_name"] for row in by_code.data], ["另一个客户"])
        self.assertEqual([row["customer_name"] for row in by_level.data], ["另一个客户"])

    def test_update_contact_requires_update_permission(self):
        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"crm:customer:view"}):
                forbidden = self.client.put(
                    f"/api/crm/contacts/{self.contact.id}/",
                    {
                        "customer": self.customer.id,
                        "name": "已修改联系人",
                        "mobile": "13700000000",
                        "is_primary": False,
                    },
                    format="json",
                )
                self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

            with self._permission_patch({"crm:customer:view", "crm:contact:update"}):
                allowed = self.client.put(
                    f"/api/crm/contacts/{self.contact.id}/",
                    {
                        "customer": self.customer.id,
                        "name": "已修改联系人",
                        "mobile": "13700000000",
                        "is_primary": False,
                    },
                    format="json",
                )
                self.assertEqual(allowed.status_code, status.HTTP_200_OK, allowed.data)
                self.contact.refresh_from_db()
                self.assertEqual(self.contact.name, "已修改联系人")

    def test_delete_contact_requires_delete_permission(self):
        with patch("core_apps.common.permissions.TenantService.get_runtime_config", return_value=self._runtime_config()):
            with self._permission_patch({"crm:customer:view"}):
                forbidden = self.client.delete(f"/api/crm/contacts/{self.contact.id}/")
                self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
                self.assertTrue(Contact.objects.filter(pk=self.contact.id).exists())

            with self._permission_patch({"crm:customer:view", "crm:contact:delete"}):
                allowed = self.client.delete(f"/api/crm/contacts/{self.contact.id}/")
                self.assertEqual(allowed.status_code, status.HTTP_204_NO_CONTENT, allowed.data)
                self.assertFalse(Contact.objects.filter(pk=self.contact.id).exists())
