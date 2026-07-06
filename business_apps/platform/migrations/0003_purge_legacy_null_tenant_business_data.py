from django.db import migrations


def purge_legacy_null_tenant_business_data(apps, schema_editor):
    delete_order = [
        ("accounting", "VoucherLine"),
        ("accounting", "BusinessPostingLog"),
        ("ap_payable", "APAllocation"),
        ("ap_payable", "APOperationLog"),
        ("ap_payable", "SupplierCreditNote"),
        ("ar_receivable", "WriteOff"),
        ("finance", "CashAccountTransaction"),
        ("supply_chain", "InventoryAlert"),
        ("supply_chain", "OutboundOrderItem"),
        ("supply_chain", "TransferOrderItem"),
        ("supply_chain", "SalesReturnOrderItem"),
        ("supply_chain", "PurchaseReturnOrderItem"),
        ("purchase", "PurchaseAttachment"),
        ("purchase", "PurchaseReceiptItem"),
        ("purchase", "PurchaseApprovalLog"),
        ("purchase", "PurchaseChangeLog"),
        ("sales", "ShipmentItem"),
        ("sales", "OrderApprovalLog"),
        ("sales", "OrderChangeLog"),
        ("sales", "OrderAttachment"),
        ("sales", "SalesExecutionLog"),
        ("inventory", "StocktakeItem"),
        ("inventory", "InventoryTransaction"),
        ("inventory", "Inventory"),
        ("inventory", "ProductImage"),
        ("inventory", "ProductAttachment"),
        ("crm", "Contact"),
        ("crm", "FollowRecord"),
        ("crm", "CustomerAttachment"),
        ("crm", "TransferLog"),
        ("supplier", "SupplierContact"),
        ("supplier", "SupplierFollowRecord"),
        ("supplier", "SupplierAttachment"),
        ("supplier", "SupplierEvaluation"),
        ("supplier", "SupplierTransferLog"),
        ("accounting", "Voucher"),
        ("accounting", "AccountingPeriod"),
        ("accounting", "AccountSubject"),
        ("ap_payable", "APPayment"),
        ("ap_payable", "APAccount"),
        ("ar_receivable", "Receipt"),
        ("ar_receivable", "Receivable"),
        ("finance", "FinanceExportTask"),
        ("finance", "FinancialSnapshot"),
        ("finance", "CashAccount"),
        ("supply_chain", "OutboundOrder"),
        ("supply_chain", "TransferOrder"),
        ("supply_chain", "SalesReturnOrder"),
        ("supply_chain", "PurchaseReturnOrder"),
        ("purchase", "PurchaseReceipt"),
        ("purchase", "PurchaseOrderItem"),
        ("purchase", "PurchaseOrder"),
        ("sales", "Shipment"),
        ("sales", "SalesOrderItem"),
        ("sales", "SalesOrder"),
        ("inventory", "Stocktake"),
        ("inventory", "ProductTag"),
        ("inventory", "Product"),
        ("inventory", "Warehouse"),
        ("inventory", "Unit"),
        ("inventory", "ProductCategory"),
        ("crm", "CustomerTag"),
        ("crm", "Customer"),
        ("supplier", "SupplierTag"),
        ("supplier", "Supplier"),
    ]

    for app_label, model_name in delete_order:
        model = apps.get_model(app_label, model_name)
        if any(field.name == "tenant" for field in model._meta.fields):
            model.objects.filter(tenant__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0002_alter_coderule_current_date_key_and_more"),
        ("accounting", "0003_accountingperiod_tenant_accountsubject_tenant_and_more"),
        ("ap_payable", "0008_apaccount_tenant_apallocation_tenant_and_more"),
        ("ar_receivable", "0009_receipt_tenant_receivable_tenant_writeoff_tenant"),
        ("crm", "0005_contact_tenant_customer_tenant_and_more"),
        ("finance", "0003_cashaccount_tenant_cashaccounttransaction_tenant_and_more"),
        ("inventory", "0007_inventory_tenant_inventorytransaction_tenant_and_more"),
        ("purchase", "0007_purchaseattachment_tenant"),
        ("sales", "0005_orderapprovallog_tenant_orderattachment_tenant_and_more"),
        ("supplier", "0005_supplier_tenant_supplierattachment_tenant_and_more"),
        ("supply_chain", "0007_inventoryalert_tenant_outboundorder_tenant_and_more"),
    ]

    operations = [
        migrations.RunPython(
            purge_legacy_null_tenant_business_data,
            migrations.RunPython.noop,
        ),
    ]
