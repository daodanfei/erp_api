from __future__ import annotations


def module_config_template(
    *,
    features: dict | None = None,
    workflows: dict | None = None,
    field_rules: dict | None = None,
    defaults: dict | None = None,
) -> dict:
    return {
        "features": features or {},
        "workflows": workflows or {},
        "field_rules": field_rules or {},
        "defaults": defaults or {},
    }


MODULE_CONFIGURATION_CATALOG = {
    "platform": module_config_template(
        features={
            "file_center": True,
            # 注意:
            # 1. 字典中心 / 编码规则中心在 ERP 侧是刻意隐藏的，不对租户开放菜单入口。
            # 2. 这里保留配置字段，仅用于兼容历史快照、运行时策略和导出合同结构。
            # 3. 后续如果有人补蓝图编辑器或菜单配置，不要把这两个开关重新暴露为可见菜单。
            "dict_center": False,
            "code_rule_center": False,
        },
    ),
    "inventory": module_config_template(
        features={
            "multi_warehouse": False,
            "batch_tracking": False,
            "serial_number": False,
            "stocktake": True,
            "negative_stock_allowed": False,
            "warehouse_required_on_transaction": False,
        },
        field_rules={
            "inventory_transaction.warehouse": {"visible": False, "required": False, "readonly": True},
            "stocktake.warehouse": {"visible": False, "required": False, "readonly": True},
            "purchase_order_item.warehouse": {"visible": False, "required": False, "readonly": True},
            "sales_order_item.warehouse": {"visible": False, "required": False, "readonly": True},
        },
        defaults={
            "default_warehouse_code": "MAIN",
        },
    ),
    "purchase": module_config_template(
        features={
            "approval": False,
            "partial_receipt": True,
            "purchase_return": True,
            "receipt_auto_ap": False,
            "expected_arrival_required": False,
            "supplier_blacklist_block": True,
        },
        workflows={
            "purchase_order_submit": "auto_approve",
        },
        field_rules={
            "purchase_order.approver": {"visible": False, "required": False, "readonly": True},
            "purchase_order.expected_arrival_date": {"visible": True, "required": False, "readonly": False},
        },
        defaults={
            "default_currency": "CNY",
        },
    ),
    "sales": module_config_template(
        features={
            "approval": False,
            "credit_control": False,
            "partial_shipment": True,
            "outbound_auto_ar": False,
            "customer_blacklist_block": True,
            "price_editable": True,
        },
        workflows={
            "sales_order_submit": "auto_approve",
        },
        field_rules={
            "sales_order.approver": {"visible": False, "required": False, "readonly": True},
            "sales_order_item.warehouse": {"visible": False, "required": False, "readonly": True},
        },
        defaults={
            "default_currency": "CNY",
        },
    ),
    "supplier": module_config_template(
        features={
            "supplier_approval": False,
            "supplier_code_auto_generate": True,
            "supplier_credit_management": False,
            "supplier_rating_enabled": True,
            "supplier_attachment_enabled": True,
            "supplier_owner_transfer_enabled": True,
        },
        field_rules={
            "supplier.tax_rate": {"visible": True, "required": False, "readonly": False},
            "supplier.currency": {"visible": True, "required": False, "readonly": False},
            "supplier.owner": {"visible": True, "required": False, "readonly": False},
            "supplier.credit_days": {"visible": True, "required": False, "readonly": False},
        },
        defaults={
            "default_currency": "CNY",
        },
    ),
    "crm": module_config_template(
        features={
            "customer_approval": False,
            "customer_code_auto_generate": True,
            "credit_limit_enabled": True,
            "follow_record_enabled": True,
            "customer_transfer_enabled": True,
            "customer_attachment_enabled": True,
        },
        field_rules={
            "customer.credit_limit": {"visible": True, "required": False, "readonly": False},
            "customer.credit_days": {"visible": True, "required": False, "readonly": False},
            "customer.owner": {"visible": True, "required": False, "readonly": False},
            "customer.phone": {"visible": True, "required": False, "readonly": False},
            "customer.address": {"visible": True, "required": False, "readonly": False},
        },
    ),
    "supply_chain": module_config_template(
        features={
            "transfer_enabled": True,
            "sales_return_enabled": True,
            "purchase_return_enabled": True,
            "inventory_alert_enabled": True,
            "trace_enabled": True,
            "outbound_requires_allocation": True,
            "transfer_approval": True,
            "return_approval": True,
        },
    ),
    "finance": module_config_template(
        features={
            "multi_cash_account": True,
            "reconciliation_enabled": True,
            "opening_balance_editable": False,
            "cash_flow_analysis_enabled": True,
        },
        field_rules={
            "cash_account.account_type": {"visible": True, "required": False, "readonly": False},
            "cash_account.opening_balance": {"visible": True, "required": False, "readonly": False},
            "cash_account.opening_balance_date": {"visible": True, "required": False, "readonly": False},
        },
        defaults={
            "default_currency": "CNY",
        },
    ),
    "ar_receivable": module_config_template(
        features={
            "auto_create_receivable": True,
            "receipt_approval": True,
            "allow_partial_receipt": True,
            "overdue_tracking": True,
            "customer_reconciliation_enabled": True,
            "writeoff_enabled": True,
        },
    ),
    "ap_payable": module_config_template(
        features={
            "auto_create_payable": True,
            "payment_approval": True,
            "allow_partial_payment": True,
            "supplier_reconciliation_enabled": True,
            "allocation_enabled": True,
            "writeoff_enabled": True,
        },
    ),
    "accounting": module_config_template(
        features={
            "voucher_auto_posting": True,
            "period_close_enabled": True,
            "subject_editable_after_init": True,
            "ar_ap_posting_enabled": False,
            "inventory_posting_enabled": False,
        },
        field_rules={
            "voucher.approver": {"visible": True, "required": False, "readonly": True},
            "voucher.source_document_no": {"visible": True, "required": False, "readonly": True},
        },
    ),
    "reports": module_config_template(
        features={
            "dashboard": True,
            "sales_analysis": True,
            "purchase_analysis": True,
            "inventory_analysis": True,
            "customer_analysis": True,
            "supplier_analysis": True,
            "product_analysis": True,
            "export_center": True,
        },
    ),
}
