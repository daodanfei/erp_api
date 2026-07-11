from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework.response import Response

from core_apps.erp_auth.models import ERPUser
from core_apps.erp_auth.tokens import ERPRefreshToken
from core_apps.tenant.models import Tenant

from .middleware import _normalize_logged_path
from .models import OperationLog
from .serializers import OperationLogSerializer


class OperationLogModelTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="log-model-tenant", name="Log Model Tenant", status="ACTIVE")
        self.user = ERPUser.objects.create_user(tenant=self.tenant, username="system_api", password="password")

    def test_operation_log_orders_latest_first(self):
        first = OperationLog.objects.create(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/system/logs/",
            method="GET",
            status_code=200,
            execution_time=1.2,
        )
        second = OperationLog.objects.create(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/system/logs/",
            method="POST",
            status_code=201,
            execution_time=3.4,
        )

        logs = list(OperationLog.objects.all())
        self.assertEqual(logs[0].id, second.id)
        self.assertEqual(logs[1].id, first.id)


class OperationLogApiTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="log-api-tenant", name="Log Api Tenant", status="ACTIVE")
        self.user = ERPUser.objects.create_user(tenant=self.tenant, username="api_user", password="password")
        token = ERPRefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.other_tenant = Tenant.objects.create(code="log-other-tenant", name="Log Other Tenant", status="ACTIVE")
        self.other_user = ERPUser.objects.create_user(
            tenant=self.other_tenant,
            username="other_user",
            password="password",
        )
        OperationLog.objects.create(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/inventory/products/5/",
            method="PATCH",
            status_code=200,
            execution_time=1.5,
        )
        OperationLog.objects.create(
            tenant=self.other_tenant,
            erp_user=self.other_user,
            path="/api/inventory/products/5/",
            method="PATCH",
            status_code=200,
            execution_time=2.0,
        )

    def test_logs_endpoint_lists_only_current_tenant_logs(self):
        response = self.client.get("/api/system/logs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["path"], "/api/inventory/products/5/")
        self.assertEqual(response.data[0]["operator_name"], "api_user")

    def test_logs_endpoint_supports_path_prefix_filter(self):
        response = self.client.get("/api/system/logs/", {"path_prefix": "/api/inventory/products/5/"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["operation_summary"], "修改商品")


class OperationLogMiddlewareTest(TestCase):
    def test_normalize_logged_path_maps_create_request_to_detail_path(self):
        class DummyRequest:
            method = "POST"
            path = "/api/crm/customers/"

        response = Response({"id": 15, "customer_name": "测试客户"}, status=201)

        self.assertEqual(_normalize_logged_path(DummyRequest(), response), "/api/crm/customers/15/")


class OperationLogSerializerTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="log-serializer-tenant", name="Log Serializer Tenant", status="ACTIVE")
        self.user = ERPUser.objects.create_user(tenant=self.tenant, username="serializer_user", password="password")

    def test_operation_summary_includes_changed_customer_fields(self):
        log = OperationLog.objects.create(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/crm/customers/8/",
            method="PATCH",
            params='{"customer_name":"华北客户","phone":"13800000000","email":"a@example.com"}',
            status_code=200,
            execution_time=8.5,
        )

        data = OperationLogSerializer(log).data

        self.assertEqual(data["operation_summary"], "修改客户，涉及客户名称、手机号、邮箱")
