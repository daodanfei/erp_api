from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from business_apps.inventory.models import Inventory, Product, ProductCategory, Unit, Warehouse
from business_apps.inventory.services import InventoryService
from business_apps.supply_chain.models import OutboundOrder, TransferOrder
from business_apps.supply_chain.services import OutboundService, TransferService
from core_apps.blueprints.models import SystemBlueprint, SystemBlueprintVersion
from core_apps.authentication.models import Permission, Role, User
from core_apps.tenant.models import Tenant, TenantConfigSnapshot, TenantUser


def build_supply_chain_config(*, transfer_approval=True):
    return {
        "basic": {"name": "supply_chain_policy", "industry": "trade", "mode": "saas"},
        "enabled_modules": ["supply_chain"],
        "module_configs": {
            "supply_chain": {
                "features": {
                    "transfer_enabled": True,
                    "sales_return_enabled": True,
                    "purchase_return_enabled": True,
                    "inventory_alert_enabled": True,
                    "trace_enabled": True,
                    "outbound_requires_allocation": True,
                    "transfer_approval": transfer_approval,
                    "return_approval": True,
                },
                "workflows": {},
                "field_rules": {},
                "defaults": {},
            }
        },
    }


class TransferOrderApiTest(APITestCase):
    def setUp(self):
        self.update_permission = Permission.objects.create(
            name="编辑调拨单",
            code="supply_chain:transfer:update",
            type="BUTTON",
        )
        self.create_permission = Permission.objects.create(
            name="创建调拨单",
            code="supply_chain:transfer:create",
            type="BUTTON",
        )
        self.submit_permission = Permission.objects.create(
            name="提交审核",
            code="supply_chain:transfer:submit",
            type="BUTTON",
        )
        self.approve_permission = Permission.objects.create(
            name="审核调拨单",
            code="supply_chain:transfer:approve",
            type="BUTTON",
        )
        self.start_permission = Permission.objects.create(
            name="调出确认",
            code="supply_chain:transfer:start",
            type="BUTTON",
        )
        self.complete_permission = Permission.objects.create(
            name="调入确认",
            code="supply_chain:transfer:complete",
            type="BUTTON",
        )
        self.role = Role.objects.create(name="调拨编辑", code="transfer_editor")
        self.role.permissions.add(
            self.update_permission,
            self.create_permission,
            self.submit_permission,
            self.approve_permission,
            self.start_permission,
            self.complete_permission,
        )
        self.user = User.objects.create_user(username="transfer_user", password="testpass", is_superuser=True, is_staff=True)
        self.user.roles.add(self.role)
        self.approver = User.objects.create_user(username="transfer_approver", password="testpass", is_superuser=True, is_staff=True)
        self.outbound_operator = User.objects.create_user(username="transfer_outbound", password="testpass", is_superuser=True, is_staff=True)
        self.inbound_operator = User.objects.create_user(username="transfer_inbound", password="testpass", is_superuser=True, is_staff=True)
        self.approver.roles.add(self.role)
        self.outbound_operator.roles.add(self.role)
        self.inbound_operator.roles.add(self.role)
        self.client.force_authenticate(self.user)

        self.category = ProductCategory.objects.create(name="调拨测试分类")
        self.unit = Unit.objects.create(name="个", code="UNIT-TR-001")
        self.product = Product.objects.create(
            product_code="PRO-TR-001",
            name="调拨测试商品",
            category=self.category,
            unit=self.unit,
            cost_price=10,
            sale_price=20,
            created_by=self.user,
        )
        self.from_wh = Warehouse.objects.create(warehouse_code="WH-TR-001", warehouse_name="调出仓库")
        self.to_wh = Warehouse.objects.create(warehouse_code="WH-TR-002", warehouse_name="调入仓库")
        self.other_wh = Warehouse.objects.create(warehouse_code="WH-TR-003", warehouse_name="第三仓库")

    def _apply_runtime_config(self, user, config):
        blueprint = SystemBlueprint.objects.create(key=f"supply-bp-{Tenant.objects.count()}", name="Supply Policy", created_by=user)
        version = SystemBlueprintVersion.objects.create(
            blueprint=blueprint,
            version="v1",
            config_json=config,
            created_by=user,
        )
        tenant = Tenant.objects.create(code=f"supply-tenant-{Tenant.objects.count()}", name="Supply Tenant", status="ACTIVE")
        TenantUser.objects.create(tenant=tenant, user=user, is_default=True, is_owner=True)
        TenantConfigSnapshot.objects.create(tenant=tenant, blueprint_version=version, config_json=config)
        return tenant

    def _create_transfer(self):
        return TransferService.create_order(
            self.from_wh,
            self.to_wh,
            [
                {
                    "product": self.product,
                    "quantity": Decimal("3.000"),
                    "remark": "原始备注",
                }
            ],
            self.user,
            remark="初始调拨单",
        )

    def test_draft_transfer_order_can_be_updated(self):
        order = self._create_transfer()

        response = self.client.put(
            f"/api/supply-chain/transfer-orders/{order.id}/",
            {
                "from_warehouse": self.other_wh.id,
                "to_warehouse": self.to_wh.id,
                "remark": "修改后的备注",
                "items": [
                    {
                        "product": self.product.id,
                        "quantity": "5.000",
                        "remark": "修改明细",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.from_warehouse_id, self.other_wh.id)
        self.assertEqual(order.remark, "修改后的备注")
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().quantity, Decimal("5.000"))

    def test_in_transit_transfer_order_cannot_be_updated(self):
        order = self._create_transfer()
        TransferService.submit_order(order, self.user)
        TransferService.approve_order(order, self.approver)
        InventoryService.change_stock(
            warehouse=self.from_wh,
            product=self.product,
            quantity=Decimal("3.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.user,
            remark="seed transfer stock",
        )
        TransferService.start_transfer(order, self.user)

        response = self.client.put(
            f"/api/supply-chain/transfer-orders/{order.id}/",
            {
                "from_warehouse": self.other_wh.id,
                "to_warehouse": self.to_wh.id,
                "remark": "不应生效",
                "items": [
                    {
                        "product": self.product.id,
                        "quantity": "5.000",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有草稿状态的调拨单可以编辑", response.data["detail"])

    def test_transfer_review_and_execution_flow_enforces_user_separation(self):
        order = self._create_transfer()

        submit_response = self.client.post(f"/api/supply-chain/transfer-orders/{order.id}/submit/")
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, "PENDING_APPROVAL")
        self.assertEqual(order.submitted_by_id, self.user.id)

        approve_self_response = self.client.post(f"/api/supply-chain/transfer-orders/{order.id}/approve/")
        self.assertEqual(approve_self_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("审核人不能是提交人或创建人", approve_self_response.data["detail"])

        TransferService.approve_order(order, self.approver)
        order.refresh_from_db()
        self.assertEqual(order.status, "APPROVED")
        self.assertEqual(order.approved_by_id, self.approver.id)

        InventoryService.change_stock(
            warehouse=self.from_wh,
            product=self.product,
            quantity=Decimal("3.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.user,
            remark="seed transfer stock",
        )

        start_response = self.client.post(f"/api/supply-chain/transfer-orders/{order.id}/start/")
        self.assertEqual(start_response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, "IN_TRANSIT")
        self.assertEqual(order.outbound_confirmed_by_id, self.user.id)

        self.client.force_authenticate(self.inbound_operator)
        complete_response = self.client.post(f"/api/supply-chain/transfer-orders/{order.id}/complete/")
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, "COMPLETED")
        self.assertEqual(order.inbound_confirmed_by_id, self.inbound_operator.id)

        from_inventory = Inventory.objects.get(warehouse=self.from_wh, product=self.product)
        to_inventory = Inventory.objects.get(warehouse=self.to_wh, product=self.product)
        self.assertEqual(from_inventory.current_qty, Decimal("0"))
        self.assertEqual(to_inventory.current_qty, Decimal("3.000"))

    def test_transfer_submit_auto_approves_when_policy_disabled(self):
        self._apply_runtime_config(self.user, build_supply_chain_config(transfer_approval=False))
        order = self._create_transfer()

        submit_response = self.client.post(f"/api/supply-chain/transfer-orders/{order.id}/submit/")

        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        self.assertEqual(submit_response.data["status"], "approved")
        order.refresh_from_db()
        self.assertEqual(order.status, "APPROVED")
        self.assertEqual(order.approved_by_id, self.user.id)


class OutboundOrderApiTest(APITestCase):
    def setUp(self):
        permissions = [
            Permission.objects.create(name="创建出库单", code="supply_chain:outbound:create", type="BUTTON"),
            Permission.objects.create(name="编辑出库单", code="supply_chain:outbound:update", type="BUTTON"),
            Permission.objects.create(name="审核出库单", code="supply_chain:outbound:approve", type="BUTTON"),
            Permission.objects.create(name="执行出库单", code="supply_chain:outbound:complete", type="BUTTON"),
        ]
        self.role = Role.objects.create(name="出库操作", code="outbound_operator")
        self.role.permissions.add(*permissions)

        self.creator = User.objects.create_user(username="outbound_creator", password="testpass", is_superuser=True, is_staff=True)
        self.approver = User.objects.create_user(username="outbound_approver", password="testpass", is_superuser=True, is_staff=True)
        self.creator.roles.add(self.role)
        self.approver.roles.add(self.role)
        self.client.force_authenticate(self.creator)

        self.category = ProductCategory.objects.create(name="出库测试分类")
        self.unit = Unit.objects.create(name="个", code="UNIT-OB-001")
        self.product = Product.objects.create(
            product_code="PRO-OB-001",
            name="出库测试商品",
            category=self.category,
            unit=self.unit,
            cost_price=Decimal("10"),
            sale_price=Decimal("20"),
            created_by=self.creator,
        )
        self.warehouse = Warehouse.objects.create(warehouse_code="WH-OB-001", warehouse_name="出库仓库")
        InventoryService.change_stock(
            warehouse=self.warehouse,
            product=self.product,
            quantity=Decimal("5.000"),
            transaction_type="MANUAL_ADJUST",
            operator=self.creator,
            remark="seed outbound stock",
        )
        self.order = OutboundService.create_order(
            sales_order=None,
            warehouse=self.warehouse,
            items_data=[{"product": self.product, "quantity": Decimal("2.000")}],
            user=self.creator,
            remark="待审批出库",
        )

    def test_outbound_requires_approval_before_execution(self):
        submit_response = self.client.post(f"/api/supply-chain/outbound-orders/{self.order.id}/submit/")
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)

        complete_response = self.client.post(f"/api/supply-chain/outbound-orders/{self.order.id}/complete/")
        self.assertEqual(complete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("只有已审核状态的出库单可以执行", complete_response.data["detail"])

        self.order.refresh_from_db()
        inventory = Inventory.objects.get(warehouse=self.warehouse, product=self.product)
        self.assertEqual(self.order.status, "PENDING")
        self.assertEqual(self.order.submitted_by_id, self.creator.id)
        self.assertEqual(inventory.current_qty, Decimal("5.000"))

        self.client.force_authenticate(self.approver)
        approve_response = self.client.post(f"/api/supply-chain/outbound-orders/{self.order.id}/approve/")
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)

        complete_response = self.client.post(f"/api/supply-chain/outbound-orders/{self.order.id}/complete/")
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)

        self.order.refresh_from_db()
        inventory.refresh_from_db()
        self.assertEqual(self.order.status, "COMPLETED")
        self.assertEqual(self.order.approved_by_id, self.approver.id)
        self.assertEqual(inventory.current_qty, Decimal("3.000"))
