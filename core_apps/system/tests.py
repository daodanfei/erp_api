import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from rest_framework.request import Request
from rest_framework.test import APITestCase
from rest_framework.response import Response

from business_apps.inventory.models import Product, ProductCategory, Unit
from business_apps.inventory.serializers import ProductSerializer, UnitSerializer
from business_apps.purchase.models import PurchaseOrder
from business_apps.supplier.models import Supplier
from core_apps.erp_auth.models import ERPPermission, ERPRole, ERPUser
from core_apps.erp_auth.tokens import ERPRefreshToken
from core_apps.tenant.models import Tenant

from .middleware import (
    _extract_error_response,
    _extract_operation_target,
    _mask_sensitive_fields,
    _normalize_logged_path,
    OperationLogMiddleware,
)
from .models import OperationLog
from .operation_log import (
    OperationLogChangeTracker,
    collect_serializer_operation_log_changes,
    set_operation_log_changes,
)
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
        log_permission = ERPPermission.objects.create(name="操作日志", code="system:log")
        log_role = ERPRole.objects.create(tenant=self.tenant, name="日志查看", code="LOG_VIEWER")
        log_role.permissions.add(log_permission)
        self.user.roles.add(log_role)
        permission_patcher = patch(
            "core_apps.erp_auth.services.get_enabled_erp_permission_codes",
            return_value={"system:log"},
        )
        permission_patcher.start()
        self.addCleanup(permission_patcher.stop)
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

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["path"], "/api/inventory/products/5/")
        self.assertEqual(response.data[0]["operator_name"], "api_user")

    def test_logs_endpoint_supports_path_prefix_filter(self):
        response = self.client.get("/api/system/logs/", {"path_prefix": "/api/inventory/products/5/"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["operation_summary"], "修改商品")


class OperationLogMiddlewareTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="log-middleware-tenant", name="Log Middleware Tenant", status="ACTIVE")
        self.user = ERPUser.objects.create_user(tenant=self.tenant, username="middleware_user", password="password")

    def test_normalize_logged_path_maps_create_request_to_detail_path(self):
        class DummyRequest:
            method = "POST"
            path = "/api/crm/customers/"

        response = Response({"id": 15, "customer_name": "测试客户"}, status=201)

        self.assertEqual(_normalize_logged_path(DummyRequest(), response), "/api/crm/customers/15/")

    def test_sensitive_fields_are_masked_recursively(self):
        params = {
            "username": "zhangsan",
            "old_password": "old-secret",
            "profile": {"api_token": "token-value", "name": "张三"},
        }

        self.assertEqual(
            _mask_sensitive_fields(params),
            {
                "username": "zhangsan",
                "old_password": "******",
                "profile": {"api_token": "******", "name": "张三"},
            },
        )

    def test_error_response_keeps_business_reason_for_log_summary(self):
        response = Response({"detail": "当前库存不足，无法完成出库"}, status=400)

        self.assertEqual(_extract_error_response(response), {"detail": "当前库存不足，无法完成出库"})

    def test_operation_target_prefers_business_number_from_response(self):
        class DummyRequest:
            pass

        response = Response({"id": 8, "order_no": "PO20260713001", "status": "APPROVED"}, status=200)

        self.assertEqual(_extract_operation_target(DummyRequest(), response, None), "PO20260713001")

    def test_operation_target_combines_master_data_code_and_name(self):
        class DummyRequest:
            pass

        response = Response({"id": 8, "product_code": "P001", "name": "苹果手机"}, status=200)

        self.assertEqual(_extract_operation_target(DummyRequest(), response, None), "P001（苹果手机）")

    def test_json_put_keeps_changed_fields_after_view_consumes_request(self):
        request = RequestFactory().put(
            "/api/inventory/products/10/",
            data=json.dumps({"name": "西瓜啊", "specification": "大果"}),
            content_type="application/json",
        )
        request.user = self.user
        middleware = OperationLogMiddleware(lambda current_request: Response(status=200))

        middleware.process_view(request, lambda current_request: None, (), {})
        drf_request = Request(request)
        set_operation_log_changes(
            drf_request,
            [{"field": "specification", "old": "中果", "new": "大果"}],
        )
        self.assertEqual(
            request.operation_log_changes,
            [{"field": "specification", "old": "中果", "new": "大果"}],
        )
        response = Response(
            {"id": 10, "product_code": "PRO2026070008", "name": "西瓜啊", "specification": "大果"},
            status=200,
        )
        middleware.process_response(request, response)

        log = OperationLog.objects.get(path="/api/inventory/products/10/")
        self.assertEqual(
            json.loads(log.params),
            {
                "_changes": [{"field": "specification", "old": "中果", "new": "大果"}],
                "_operation_target": "PRO2026070008（西瓜啊）",
            },
        )
        self.assertNotIn("西瓜啊", log.params.replace("PRO2026070008（西瓜啊）", ""))
        self.assertEqual(
            OperationLogSerializer(log).data["operation_summary"],
            "修改商品：PRO2026070008（西瓜啊），规格型号由“中果”改为“大果”",
        )

    def test_full_put_records_only_values_that_really_changed(self):
        unit = Unit.objects.create(tenant=self.tenant, code="UNIT001", name="个", status=True)
        serializer = UnitSerializer(unit, data={"name": "箱", "status": True})
        serializer.is_valid(raise_exception=True)

        self.assertEqual(
            collect_serializer_operation_log_changes(serializer),
            [{"field": "name", "old": "个", "new": "箱"}],
        )

    def test_product_full_put_ignores_unchanged_foreign_keys_and_form_fields(self):
        category = ProductCategory.objects.create(tenant=self.tenant, name="水果")
        unit = Unit.objects.create(tenant=self.tenant, code="UNIT002", name="个", status=True)
        product = Product.objects.create(
            tenant=self.tenant,
            product_code="PRO001",
            name="西瓜",
            barcode="690000000001",
            category=category,
            unit=unit,
            brand="本地",
            specification="大果",
            status="ACTIVE",
            cost_price="10.00",
            sale_price="20.00",
            remark="测试商品",
        )
        product.refresh_from_db()
        serializer = ProductSerializer(
            product,
            data={
                "name": "西瓜",
                "barcode": "690000000001",
                "category": category.id,
                "unit": unit.id,
                "brand": "本地",
                "specification": "大果",
                "status": "ACTIVE",
                "cost_price": "10.00",
                "sale_price": "22.00",
                "remark": "测试商品",
            },
        )
        serializer.is_valid(raise_exception=True)

        self.assertEqual(
            collect_serializer_operation_log_changes(serializer),
            [{"field": "sale_price", "old": "20.00", "new": "22.00"}],
        )

    def test_change_values_use_business_labels_and_ignore_password(self):
        unit = Unit.objects.create(tenant=self.tenant, code="UNIT003", name="个", status=True)
        serializer = UnitSerializer(unit, data={"name": "个", "status": False})
        serializer.is_valid(raise_exception=True)

        self.assertEqual(
            collect_serializer_operation_log_changes(serializer),
            [{"field": "status", "old": "是", "new": "否"}],
        )

        class SerializerWithSensitiveValue:
            instance = unit
            validated_data = {"password": "new-secret", "name": "箱"}

        self.assertEqual(
            collect_serializer_operation_log_changes(SerializerWithSensitiveValue()),
            [{"field": "name", "old": "个", "new": "箱"}],
        )

    def test_service_driven_update_uses_same_lightweight_change_format(self):
        old_category = ProductCategory.objects.create(tenant=self.tenant, name="水果")
        new_category = ProductCategory.objects.create(tenant=self.tenant, name="生鲜")
        unit = Unit.objects.create(tenant=self.tenant, code="UNIT004", name="个", status=True)
        product = Product.objects.create(
            tenant=self.tenant,
            product_code="PRO002",
            name="西瓜",
            category=old_category,
            unit=unit,
            sale_price="20.00",
        )
        product.refresh_from_db()
        request = RequestFactory().put(
            "/api/inventory/products/2/",
            data=json.dumps({"category": new_category.id, "sale_price": "25.00"}),
            content_type="application/json",
        )
        tracker = OperationLogChangeTracker(product, {"category": new_category.id, "sale_price": "25.00"})

        product.category = new_category
        product.sale_price = "25.00"
        changes = tracker.finish(request, product)

        self.assertEqual(
            changes,
            [
                {"field": "category", "old": "水果", "new": "生鲜"},
                {"field": "sale_price", "old": "20.00", "new": "25.00"},
            ],
        )
        self.assertEqual(request.operation_log_changes, changes)

    def test_service_driven_update_ignores_reverse_relations_in_request_payload(self):
        supplier = Supplier.objects.create(
            tenant=self.tenant,
            supplier_code="SUP005",
            supplier_name="测试供应商",
        )
        order = PurchaseOrder.objects.create(
            tenant=self.tenant,
            purchase_order_no="PO005",
            supplier=supplier,
            remark="原备注",
        )

        # Reverse relation fields such as PurchaseOrder.items are represented
        # by ManyToOneRel and intentionally have no ``attname`` attribute.
        tracker = OperationLogChangeTracker(order, {"items": [{"id": 1}], "remark": "新备注"})
        order.remark = "新备注"
        request = RequestFactory().put("/api/purchase/orders/5/", content_type="application/json")

        self.assertEqual(
            tracker.finish(request, order),
            [{"field": "remark", "old": "原备注", "new": "新备注"}],
        )


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

    def test_business_actions_use_explicit_erp_wording(self):
        cases = [
            ("/api/purchase/orders/8/approve/", "审核通过采购订单"),
            ("/api/purchase/orders/8/reject/", "审核驳回采购订单"),
            ("/api/purchase/receipts/6/complete/", "执行采购入库"),
            ("/api/purchase/orders/8/upload_attachment/", "上传采购订单附件"),
            ("/api/inventory/inventories/adjust/", "调整库存数量"),
            ("/api/inventory/stocktakes/3/update_items/", "录入盘点结果"),
            ("/api/sales/orders/2/create_outbound/", "根据销售订单生成出库单"),
            ("/api/supply-chain/transfer-orders/5/complete/", "完成仓库调拨"),
            ("/api/accounting/periods/4/open/", "重新打开会计期间（反关账）"),
            ("/api/platform/code-rules/init-defaults/", "初始化默认编码规则"),
            ("/api/erp-auth/change-password/", "修改登录密码"),
        ]

        for path, expected in cases:
            with self.subTest(path=path):
                log = OperationLog(
                    tenant=self.tenant,
                    erp_user=self.user,
                    path=path,
                    method="POST",
                    params='{"comment":"同意","items":[1]}',
                    status_code=200,
                    execution_time=1,
                )
                self.assertEqual(OperationLogSerializer(log).data["operation_summary"], expected)

    def test_nested_resource_is_described_instead_of_parent_document(self):
        log = OperationLog(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/purchase/orders/8/attachments/12/",
            method="DELETE",
            status_code=204,
            execution_time=1,
        )

        self.assertEqual(OperationLogSerializer(log).data["operation_summary"], "删除采购订单附件")

    def test_failed_operation_includes_business_error_reason(self):
        log = OperationLog(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/supply-chain/outbound-orders/7/complete/",
            method="POST",
            params="{}",
            response='{"detail":"当前库存不足，无法完成出库"}',
            status_code=400,
            execution_time=1,
        )

        data = OperationLogSerializer(log).data

        self.assertEqual(data["operation_summary"], "完成销售出库")
        self.assertEqual(data["result_summary"], "未完成：当前库存不足，无法完成出库")

    def test_unknown_request_field_does_not_expose_programming_name(self):
        log = OperationLog(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/crm/customers/8/",
            method="PATCH",
            params='{"legacy_internal_flag":true}',
            status_code=200,
            execution_time=1,
        )

        summary = OperationLogSerializer(log).data["operation_summary"]

        self.assertEqual(summary, "修改客户，涉及其他内容")
        self.assertNotIn("legacy_internal_flag", summary)

    def test_operation_summary_includes_business_target_snapshot(self):
        log = OperationLog(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/purchase/orders/8/approve/",
            method="POST",
            params='{"comment":"同意","_operation_target":"PO20260713001"}',
            status_code=200,
            execution_time=1,
        )

        summary = OperationLogSerializer(log).data["operation_summary"]

        self.assertEqual(summary, "审核通过采购订单：PO20260713001")
        self.assertNotIn("_operation_target", summary)

    def test_product_change_names_the_exact_product(self):
        log = OperationLog(
            tenant=self.tenant,
            erp_user=self.user,
            path="/api/inventory/products/8/",
            method="PATCH",
            params='{"specification":"256GB","_operation_target":"P001（苹果手机）"}',
            status_code=200,
            execution_time=1,
        )

        summary = OperationLogSerializer(log).data["operation_summary"]

        self.assertEqual(summary, "修改商品：P001（苹果手机），涉及规格型号")
