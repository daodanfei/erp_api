from django.test import SimpleTestCase
from rest_framework import serializers

from .validators import validate_blueprint_config


class ConfigurationValidationTest(SimpleTestCase):
    def test_validate_blueprint_config_accepts_stable_shape(self):
        result = validate_blueprint_config(
            {
                "basic": {
                    "name": "small_trade_erp",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["inventory"],
                "module_configs": {
                    "inventory": {
                        "features": {"multi_warehouse": False},
                        "workflows": {},
                        "field_rules": {
                            "inventory_transaction.warehouse": {
                                "visible": False,
                                "required": False,
                                "readonly": True,
                            }
                        },
                        "defaults": {"default_warehouse_code": "MAIN"},
                    }
                },
            }
        )

        self.assertEqual(result["basic"]["name"], "small_trade_erp")
        self.assertIn("inventory", result["enabled_modules"])

    def test_validate_blueprint_config_rejects_missing_basic(self):
        with self.assertRaises(serializers.ValidationError):
            validate_blueprint_config(
                {
                    "enabled_modules": ["inventory"],
                    "module_configs": {},
                }
            )

    def test_validate_blueprint_config_rejects_duplicate_enabled_modules(self):
        with self.assertRaises(serializers.ValidationError):
            validate_blueprint_config(
                {
                    "basic": {
                        "name": "small_trade_erp",
                        "industry": "trade",
                        "mode": "saas",
                    },
                    "enabled_modules": ["inventory", "inventory"],
                    "module_configs": {},
                }
            )

    def test_validate_blueprint_config_rejects_invalid_field_rule_shape(self):
        with self.assertRaises(serializers.ValidationError):
            validate_blueprint_config(
                {
                    "basic": {
                        "name": "small_trade_erp",
                        "industry": "trade",
                        "mode": "saas",
                    },
                    "enabled_modules": ["inventory"],
                    "module_configs": {
                        "inventory": {
                            "features": {},
                            "workflows": {},
                            "field_rules": {
                                "inventory_transaction.warehouse": {
                                    "visible": "no",
                                }
                            },
                            "defaults": {},
                        }
                    },
                }
            )

    def test_validate_blueprint_config_fills_missing_module_config_for_enabled_module(self):
        result = validate_blueprint_config(
            {
                "basic": {
                    "name": "small_trade_erp",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["inventory"],
                "module_configs": {},
            }
        )

        self.assertIn("inventory", result["module_configs"])
        self.assertIn("multi_warehouse", result["module_configs"]["inventory"]["features"])
        self.assertEqual(result["module_configs"]["inventory"]["defaults"]["default_warehouse_code"], "MAIN")

    def test_validate_blueprint_config_merges_known_module_template_sections(self):
        result = validate_blueprint_config(
            {
                "basic": {
                    "name": "extended_trade_erp",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["purchase", "sales"],
                "module_configs": {
                    "purchase": {
                        "features": {"approval": True},
                        "workflows": {"purchase_order_submit": "manual_approve"},
                        "field_rules": {},
                        "defaults": {},
                    },
                    "sales": {
                        "features": {"credit_control": True},
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {},
                    },
                },
            }
        )

        self.assertIn("purchase_return", result["module_configs"]["purchase"]["features"])
        self.assertIn("purchase_order.expected_arrival_date", result["module_configs"]["purchase"]["field_rules"])
        self.assertIn("outbound_auto_ar", result["module_configs"]["sales"]["features"])

    def test_validate_blueprint_config_turns_off_features_when_required_modules_are_missing(self):
        result = validate_blueprint_config(
            {
                "basic": {
                    "name": "dependency_trimmed_erp",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["platform", "inventory", "sales", "purchase", "accounting"],
                "module_configs": {
                    "sales": {
                        "features": {
                            "outbound_auto_ar": True,
                            "credit_control": True,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_currency": "CNY"},
                    },
                    "purchase": {
                        "features": {
                            "receipt_auto_ap": True,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {"default_currency": "CNY"},
                    },
                    "accounting": {
                        "features": {
                            "ar_ap_posting_enabled": True,
                            "inventory_posting_enabled": True,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {},
                    },
                },
            }
        )

        self.assertFalse(result["module_configs"]["sales"]["features"]["outbound_auto_ar"])
        self.assertFalse(result["module_configs"]["sales"]["features"]["credit_control"])
        self.assertFalse(result["module_configs"]["purchase"]["features"]["receipt_auto_ap"])
        self.assertFalse(result["module_configs"]["accounting"]["features"]["ar_ap_posting_enabled"])
        self.assertTrue(result["module_configs"]["accounting"]["features"]["inventory_posting_enabled"])

    def test_validate_blueprint_config_fills_platform_and_reports_templates(self):
        result = validate_blueprint_config(
            {
                "basic": {
                    "name": "full_suite_erp",
                    "industry": "trade",
                    "mode": "saas",
                },
                "enabled_modules": ["platform", "reports"],
                "module_configs": {
                    "reports": {
                        "features": {
                            "dashboard": False,
                        },
                        "workflows": {},
                        "field_rules": {},
                        "defaults": {},
                    }
                },
            }
        )

        self.assertTrue(result["module_configs"]["platform"]["features"]["file_center"])
        self.assertFalse(result["module_configs"]["platform"]["features"]["dict_center"])
        self.assertFalse(result["module_configs"]["platform"]["features"]["code_rule_center"])
        self.assertFalse(result["module_configs"]["reports"]["features"]["dashboard"])
        self.assertIn("sales_analysis", result["module_configs"]["reports"]["features"])
