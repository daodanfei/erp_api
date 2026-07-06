from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core_apps.authentication.models import User

from .models import OperationLog


class OperationLogModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="system_api", password="password")

    def test_operation_log_orders_latest_first(self):
        first = OperationLog.objects.create(
            user=self.user,
            path="/api/system/logs/",
            method="GET",
            status_code=200,
            execution_time=1.2,
        )
        second = OperationLog.objects.create(
            user=self.user,
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
        self.user = User.objects.create_user(username="api_user", password="password")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        OperationLog.objects.create(
            user=self.user,
            path="/api/system/logs/",
            method="GET",
            status_code=200,
            execution_time=1.5,
        )

    def test_logs_endpoint_lists_operation_logs(self):
        response = self.client.get("/api/system/logs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["path"], "/api/system/logs/")
