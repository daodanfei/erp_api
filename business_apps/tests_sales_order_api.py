from datetime import date

from rest_framework import status
from rest_framework.test import APITestCase

from business_apps.crm.models import Customer
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.inventory.services import InventoryService
from business_apps.sales.models import SalesOrder
from business_apps.sales.services import SalesOrderService
from business_apps.supply_chain.models import OutboundOrder
from core_apps.authentication.models import Permission, Role, User


class SalesOrderApiTest(APITestCase):
    def setUp(self):
        self.update_permission = Permission.objects.create(
            name="编辑订单",
            code="sales:order:update",
            type="BUTTON",
        )
        self.allocate_permission = Permission.objects.create(
            name="锁定库存",
            code="sales:order:allocate",
            type="BUTTON",
        )
        self.ship_permission = Permission.objects.create(
            name="订单发货",
            code="sales:order:ship",
            type="BUTTON",
        )
        self.approve_permission = Permission.objects.create(
            name="审核订单",
            code="sales:order:approve",
            type="BUTTON",
        )
        self.close_permission = Permission.objects.create(
            name="关闭订单",
            code="sales:order:close",
            type="BUTTON",
        )
        self.role = Role.objects.create(name="销售编辑", code="sales_editor")
        self.role.permissions.add(
            self.update_permission,
            self.allocate_permission,
            self.ship_permission,
            self.approve_permission,
            self.close_permission,
        )
        self.user = User.objects.create_user(username="sales_user", password="testpass")
        self.approver = User.objects.create_user(
            username="sales_approver",
            password="testpass",
            is_superuser=True,
            is_staff=True,
        )
        self.user.roles.add(self.role)
        self.approver.roles.add(self.role)
        self.client.force_authenticate(self.user)

        self.customer = Customer.objects.create(
            customer_code="CUS-API-001",
            customer_name="接口测试客户",
            status="ACTIVE",
            credit_limit=100000,
            created_by=self.user,
            owner=self.user,
            dept=self.user.dept,
        )
        self.category = ProductCategory.objects.create(name="销售测试分类")
        self.unit = Unit.objects.create(name="个", code="UNIT-SALES-001")
        self.product = Product.objects.create(
            product_code="PRO-SALES-001",
            name="销售测试商品",
            category=self.category,
            unit=self.unit,
            cost_price=10,
            sale_price=20,
            created_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="WH-SALES-001",
            warehouse_name="销售测试仓库",
        )
        self.viewer_role = Role.objects.create(name="销售查看", code="sales_viewer", data_scope="ALL")
        self.viewer_permission = Permission.objects.create(
            name="查看订单",
            code="sales:order:view",
            type="BUTTON",
        )
        self.viewer_role.permissions.add(self.viewer_permission)
        self.viewer = User.objects.create_user(username="sales_viewer", password="testpass")
        self.viewer.roles.add(self.viewer_role)

    def _create_order(self, remark="原备注"):
        return SalesOrderService.create_order(
            self.customer,
            [
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": 3,
                    "unit_price": 20,
                }
            ],
            self.user,
            remark=remark,
        )

    def test_draft_sales_order_can_be_updated(self):
        order = self._create_order()

        response = self.client.put(
            f"/api/sales/orders/{order.id}/",
            {
                "customer": self.customer.id,
                "remark": "修改后的备注",
                "expected_delivery_date": "2026-07-01T00:00:00.000Z",
                "items": [
                    {
                        "product": self.product.id,
                        "warehouse": self.warehouse.id,
                        "quantity": 5,
                        "unit_price": "21.00",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.remark, "修改后的备注")
        self.assertEqual(order.expected_delivery_date, date(2026, 7, 1))
        self.assertEqual(order.total_quantity, 5)
        self.assertEqual(order.total_amount, 105)

    def test_approved_sales_order_cannot_be_updated(self):
        order = self._create_order()
        SalesOrderService.submit_order(order, self.user)
        SalesOrderService.approve_order(order, self.approver)

        response = self.client.put(
            f"/api/sales/orders/{order.id}/",
            {
                "customer": self.customer.id,
                "remark": "不应生效",
                "items": [
                    {
                        "product": self.product.id,
                        "warehouse": self.warehouse.id,
                        "quantity": 5,
                        "unit_price": "21.00",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有草稿或已驳回状态的订单可以修改", response.data["detail"])
        order.refresh_from_db()
        self.assertEqual(order.remark, "原备注")

    def test_create_outbound_sales_order_creates_outbound_order(self):
        order = self._create_order()
        SalesOrderService.submit_order(order, self.user)
        SalesOrderService.approve_order(order, self.approver)

        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=10,
            transaction_type="PURCHASE_IN",
            operator=self.user,
            remark="初始化库存",
        )
        SalesOrderService.allocate_stock(order, self.user)

        response = self.client.post(
            f"/api/sales/orders/{order.id}/create_outbound/",
            {
                "items": [
                    {
                        "order_item": order.items.first().id,
                        "quantity": 2,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, "ALLOCATED")
        self.assertEqual(order.items.first().shipped_quantity, 0)
        outbound = OutboundOrder.objects.get(sales_order=order)
        self.assertEqual(outbound.status, "DRAFT")
        self.assertEqual(outbound.items.first().quantity, 2)

    def test_close_sales_order_requires_shipped_status(self):
        order = self._create_order()

        response = self.client.post(
            f"/api/sales/orders/{order.id}/close/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有已完成全部发货的订单可以关闭", response.data["detail"])

    def test_submitter_cannot_approve_sales_order(self):
        order = self._create_order()
        SalesOrderService.submit_order(order, self.user)

        response = self.client.post(
            f"/api/sales/orders/{order.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("审核人不能是提交人", response.data["detail"])

    def test_different_user_can_approve_sales_order(self):
        order = self._create_order()
        SalesOrderService.submit_order(order, self.user)
        self.client.force_authenticate(self.approver)

        response = self.client.post(
            f"/api/sales/orders/{order.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, "APPROVED")
        self.assertEqual(order.submitted_by_id, self.user.id)

    def test_action_permissions_are_enforced_granularly(self):
        order = self._create_order()
        SalesOrderService.submit_order(order, self.user)

        self.client.force_authenticate(self.viewer)
        self.assertEqual(
            self.client.post(f"/api/sales/orders/{order.id}/approve/", {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f"/api/sales/orders/{order.id}/allocate/", {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                f"/api/sales/orders/{order.id}/create_outbound/",
                {"items": []},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f"/api/sales/orders/{order.id}/close/", {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_create_outbound_rejects_unallocated_order(self):
        order = self._create_order()
        SalesOrderService.submit_order(order, self.user)
        SalesOrderService.approve_order(order, self.approver)

        response = self.client.post(
            f"/api/sales/orders/{order.id}/create_outbound/",
            {
                "items": [
                    {
                        "order_item": order.items.first().id,
                        "quantity": 1,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("库存锁定后才能生成销售出库申请", response.data["detail"])
