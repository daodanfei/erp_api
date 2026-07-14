from django.test import SimpleTestCase

from business_apps.inventory.module import MODULE as INVENTORY_MODULE
from business_apps.inventory.views import InventoryViewSet, ProductCategoryViewSet, UnitViewSet
from business_apps.supply_chain.module import MODULE as SUPPLY_CHAIN_MODULE
from business_apps.supply_chain.views import InventoryAlertViewSet


class ListActionPermissionContractTest(SimpleTestCase):
    def test_inventory_list_action_permissions_match_viewsets(self):
        permission_codes = {permission["code"] for permission in INVENTORY_MODULE.permissions}
        expected_codes = {
            "inventory:category:view",
            "inventory:category:create",
            "inventory:category:update",
            "inventory:category:delete",
            "inventory:unit:view",
            "inventory:unit:create",
            "inventory:unit:update",
            "inventory:unit:delete",
            "inventory:inventory:adjust",
        }

        self.assertTrue(expected_codes.issubset(permission_codes))
        self.assertEqual(ProductCategoryViewSet.permission_map["destroy"], "inventory:category:delete")
        self.assertEqual(UnitViewSet.permission_map["partial_update"], "inventory:unit:update")
        self.assertEqual(InventoryViewSet.permission_map["adjust"], "inventory:inventory:adjust")

    def test_alert_scan_uses_declared_action_permission(self):
        permission_codes = {permission["code"] for permission in SUPPLY_CHAIN_MODULE.permissions}

        self.assertIn("supply_chain:alert:scan", permission_codes)
        self.assertEqual(InventoryAlertViewSet.permission_map["scan"], "supply_chain:alert:scan")
