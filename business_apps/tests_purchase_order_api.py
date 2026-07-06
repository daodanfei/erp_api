from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from core_apps.authentication.models import Permission, Role, User
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser
from business_apps.inventory.models import Product, ProductCategory, Unit, Warehouse
from business_apps.purchase.models import PurchaseOrder
from business_apps.purchase.services import PurchaseOrderService
from business_apps.platform.services import CodeRuleService
from business_apps.supplier.models import Supplier


class PurchaseOrderApiTest(APITestCase):
    def setUp(self):
        create_permission = Permission.objects.create(name="创建采购订单", code="purchase:order:create", type="BUTTON")
        update_permission = Permission.objects.create(name="修改采购订单", code="purchase:order:update", type="BUTTON")
        delete_permission = Permission.objects.create(name="删除采购订单", code="purchase:order:delete", type="BUTTON")
        role = Role.objects.create(name="采购创建", code="purchase_creator")
        role.permissions.add(create_permission, update_permission, delete_permission)
        self.user = User.objects.create_user(username="buyer", password="testpass")
        self.approver = User.objects.create_user(username="purchase_approver", password="testpass")
        self.user.roles.add(role)
        self.client.force_authenticate(self.user)
        CodeRuleService.init_default_rules(created_by=self.user)

        self.supplier = Supplier.objects.create(
            supplier_code="SUP-API-001",
            supplier_name="接口测试供应商",
            status="ACTIVE",
        )
        self.category = ProductCategory.objects.create(name="接口测试分类")
        self.unit = Unit.objects.create(name="个", code="UNIT-API-001")
        self.product = Product.objects.create(
            product_code="PRO-API-001",
            name="接口测试商品",
            category=self.category,
            unit=self.unit,
            cost_price=10,
            sale_price=12,
            created_by=self.user,
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="WH-API-001",
            warehouse_name="接口测试仓库",
        )

    def _create_completed_order(self):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("5.000"),
                    "unit_price": Decimal("10.00"),
                }
            ],
            user=self.user,
        )
        PurchaseOrderService.submit_order(order, self.user)
        PurchaseOrderService.approve_order(order, self.approver)
        PurchaseOrderService.complete_receipt(
            PurchaseOrderService.create_receipt(
                order=order,
                warehouse=self.warehouse,
                items_data=[
                    {
                        "purchase_order_item": order.items.get(),
                        "received_quantity": Decimal("5.000"),
                    }
                ],
                user=self.user,
            ),
            self.user,
        )
        order.refresh_from_db()
        return order

    def test_create_order_accepts_iso_datetime_expected_arrival_date(self):
        response = self.client.post(
            "/api/purchase/orders/",
            {
                "supplier": self.supplier.id,
                "expected_arrival_date": "2026-06-26T16:00:00.000Z",
                "items": [
                    {
                        "product": self.product.id,
                        "warehouse": self.warehouse.id,
                        "unit_price": "10.00",
                        "quantity": 30,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = PurchaseOrder.objects.get(id=response.data["id"])
        self.assertEqual(order.expected_arrival_date, date(2026, 6, 26))
        self.assertEqual(order.total_quantity, 30)
        self.assertEqual(order.total_amount, 300)

    def test_create_order_rejects_invalid_expected_arrival_date(self):
        response = self.client.post(
            "/api/purchase/orders/",
            {
                "supplier": self.supplier.id,
                "expected_arrival_date": "not-a-date",
                "items": [
                    {
                        "product": self.product.id,
                        "warehouse": self.warehouse.id,
                        "unit_price": "10.00",
                        "quantity": 30,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("预计到货日期格式错误", response.data["detail"])

    def test_completed_purchase_order_cannot_be_updated_or_deleted(self):
        order = self._create_completed_order()

        update_response = self.client.put(
            f"/api/purchase/orders/{order.id}/",
            {
                "supplier": self.supplier.id,
                "remark": "illegal update",
                "items": [
                    {
                        "product": self.product.id,
                        "warehouse": self.warehouse.id,
                        "unit_price": "10.00",
                        "quantity": 5,
                    }
                ],
            },
            format="json",
        )
        delete_response = self.client.delete(f"/api/purchase/orders/{order.id}/")

        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有草稿或已驳回状态的订单可以修改", update_response.data["detail"])
        self.assertEqual(delete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有草稿状态的订单可以删除", delete_response.data["detail"])

    def test_action_permissions_are_enforced_granularly(self):
        order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("2.000"),
                    "unit_price": Decimal("10.00"),
                }
            ],
            user=self.user,
        )
        PurchaseOrderService.submit_order(order, self.user)

        view_permission = Permission.objects.create(name="查看采购订单", code="purchase:order:view", type="BUTTON")
        viewer_role = Role.objects.create(name="采购查看", code="purchase_viewer", data_scope="ALL")
        viewer_role.permissions.add(view_permission)
        viewer = User.objects.create_user(username="purchase_viewer", password="testpass")
        viewer.roles.add(viewer_role)
        self.client.force_authenticate(viewer)

        self.assertEqual(
            self.client.post(f"/api/purchase/orders/{order.id}/approve/", {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f"/api/purchase/orders/{order.id}/cancel/", {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )


class PurchaseReceiptApiTest(APITestCase):
    def setUp(self):
        self.receipt_view_permission = Permission.objects.create(
            name="查看采购入库",
            code="purchase:receipt:view",
            type="BUTTON",
        )
        self.receipt_create_permission = Permission.objects.create(
            name="创建采购入库",
            code="purchase:receipt:create",
            type="BUTTON",
        )
        self.receipt_complete_permission = Permission.objects.create(
            name="执行采购入库",
            code="purchase:receipt:complete",
            type="BUTTON",
        )
        self.receipt_cancel_permission = Permission.objects.create(
            name="取消采购入库",
            code="purchase:receipt:cancel",
            type="BUTTON",
        )
        self.creator_role = Role.objects.create(name="采购入库创建", code="purchase_receipt_creator", data_scope="ALL")
        self.creator_role.permissions.add(self.receipt_view_permission, self.receipt_create_permission)
        self.executor_role = Role.objects.create(name="采购入库执行", code="purchase_receipt_executor", data_scope="ALL")
        self.executor_role.permissions.add(self.receipt_view_permission, self.receipt_complete_permission)
        self.canceller_role = Role.objects.create(name="采购入库取消", code="purchase_receipt_canceller", data_scope="ALL")
        self.canceller_role.permissions.add(self.receipt_view_permission, self.receipt_cancel_permission)

        self.creator = User.objects.create_user(username="receipt_creator", password="testpass")
        self.creator.roles.add(self.creator_role)
        self.executor = User.objects.create_user(username="receipt_executor", password="testpass")
        self.executor.roles.add(self.executor_role)
        self.canceller = User.objects.create_user(username="receipt_canceller", password="testpass")
        self.canceller.roles.add(self.canceller_role)
        CodeRuleService.init_default_rules(created_by=self.creator)

        self.supplier = Supplier.objects.create(
            supplier_code="SUP-API-REC-001",
            supplier_name="入库接口供应商",
            status="ACTIVE",
        )
        self.category = ProductCategory.objects.create(name="入库接口分类")
        self.unit = Unit.objects.create(name="箱", code="UNIT-REC-001")
        self.product = Product.objects.create(
            product_code="PRO-REC-001",
            name="入库接口商品",
            category=self.category,
            unit=self.unit,
            cost_price=10,
            sale_price=12,
            created_by=self.creator,
        )
        self.warehouse = Warehouse.objects.create(
            warehouse_code="WH-REC-001",
            warehouse_name="入库接口仓库",
        )
        self.order = PurchaseOrderService.create_order(
            supplier=self.supplier,
            items_data=[
                {
                    "product": self.product,
                    "warehouse": self.warehouse,
                    "quantity": Decimal("5.000"),
                    "unit_price": Decimal("10.00"),
                }
            ],
            user=self.creator,
        )
        PurchaseOrderService.submit_order(self.order, self.creator)
        PurchaseOrderService.approve_order(self.order, User.objects.create_user(username="receipt_approver", password="testpass"))

    def _apply_runtime_config(self, user, config):
        blueprint = SystemBlueprint.objects.create(key=f"purchase-bp-{Tenant.objects.count()}", name="Purchase Policy", created_by=user)
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=user,
        )
        tenant = Tenant.objects.create(code=f"purchase-tenant-{Tenant.objects.count()}", name="Purchase Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(tenant=tenant, blueprint_version=version, config_json=config)
        return tenant

    def _build_purchase_config(self, *, partial_receipt=True):
        return {
            "basic": {"name": "purchase_policy", "industry": "trade", "mode": "saas"},
            "enabled_modules": ["inventory", "purchase"],
            "module_configs": {
                "inventory": {
                    "features": {"multi_warehouse": True},
                    "workflows": {},
                    "field_rules": {},
                    "defaults": {},
                },
                "purchase": {
                    "features": {
                        "approval": True,
                        "partial_receipt": partial_receipt,
                    },
                    "workflows": {"purchase_order_submit": "manual_approve"},
                    "field_rules": {},
                    "defaults": {},
                },
            },
        }

    def _create_receipt(self):
        self.client.force_authenticate(self.creator)
        response = self.client.post(
            "/api/purchase/receipts/",
            {
                "purchase_order": self.order.id,
                "warehouse": self.warehouse.id,
                "items": [
                    {
                        "purchase_order_item": self.order.items.get().id,
                        "received_quantity": "2.000",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data["id"]

    def test_receipt_actions_require_specific_permissions(self):
        receipt_id = self._create_receipt()

        self.client.force_authenticate(self.creator)
        self.assertEqual(
            self.client.post(f"/api/purchase/receipts/{receipt_id}/complete/", {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(self.executor)
        self.assertEqual(
            self.client.post(f"/api/purchase/receipts/{receipt_id}/complete/", {}, format="json").status_code,
            status.HTTP_200_OK,
        )

    def test_completed_receipt_cannot_be_completed_or_cancelled_again(self):
        receipt_id = self._create_receipt()

        self.client.force_authenticate(self.executor)
        complete_response = self.client.post(
            f"/api/purchase/receipts/{receipt_id}/complete/",
            {},
            format="json",
        )
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)

        repeat_complete = self.client.post(
            f"/api/purchase/receipts/{receipt_id}/complete/",
            {},
            format="json",
        )
        self.assertEqual(repeat_complete.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有草稿状态的入库单可以执行入库", repeat_complete.data["detail"])

        self.client.force_authenticate(self.canceller)
        cancel_response = self.client.post(
            f"/api/purchase/receipts/{receipt_id}/cancel/",
            {},
            format="json",
        )
        self.assertEqual(cancel_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("仅允许取消未执行入库的草稿入库单", cancel_response.data["detail"])

    def test_receipt_create_rejects_partial_quantities_when_policy_disabled(self):
        self._apply_runtime_config(self.creator, self._build_purchase_config(partial_receipt=False))
        self.client.force_authenticate(self.creator)

        response = self.client.post(
            "/api/purchase/receipts/",
            {
                "purchase_order": self.order.id,
                "warehouse": self.warehouse.id,
                "items": [
                    {
                        "purchase_order_item": self.order.items.get().id,
                        "received_quantity": "2.000",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("当前配置不允许部分入库", response.data["detail"])
