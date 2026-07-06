import os
from decimal import Decimal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core_project.settings")
django.setup()

from django.utils import timezone

from business_apps.ap_payable.models import APAccount
from business_apps.ar_receivable.models import Receivable
from business_apps.crm.models import Customer
from business_apps.finance.models import CashAccount
from business_apps.inventory.models import (
    Inventory,
    Product,
    ProductCategory,
    Unit,
    Warehouse,
)
from business_apps.inventory.services import UnitService
from business_apps.platform.services import CodeRuleService
from business_apps.purchase.models import PurchaseOrderItem
from business_apps.purchase.services import PurchaseOrderService
from business_apps.sales.services import SalesOrderService
from business_apps.supply_chain.services import OutboundService
from business_apps.supplier.models import Supplier
from core_apps.authentication.models import Role, User
from core_apps.organization.models import Department
from seed_menu import seed_data


PREFIX = "WEB-TEST"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
TESTER_USERNAME = "web_tester"
TESTER_PASSWORD = "test123456"


def ensure_user(username, password, **defaults):
    user, created = User.objects.get_or_create(username=username, defaults=defaults)
    if created or not user.check_password(password):
        user.set_password(password)
    for field, value in defaults.items():
        setattr(user, field, value)
    user.save()
    return user


def ensure_admin_permissions(admin):
    CodeRuleService.init_default_rules(created_by=admin)
    seed_data()
    admin_role = Role.objects.get(code="admin")
    admin.roles.add(admin_role)
    return admin_role


def ensure_master_data(admin, tester):
    dept, _ = Department.objects.get_or_create(
        name=f"{PREFIX} 测试部门",
        defaults={"leader": "QA"},
    )
    tester.dept = dept
    tester.save(update_fields=["dept"])

    supplier, _ = Supplier.objects.update_or_create(
        supplier_code=f"{PREFIX}-SUP",
        defaults={
            "supplier_name": f"{PREFIX} 供应商",
            "status": "ACTIVE",
            "created_by": admin,
            "owner": admin,
            "dept": dept,
        },
    )
    customer, _ = Customer.objects.update_or_create(
        customer_code=f"{PREFIX}-CUS",
        defaults={
            "customer_name": f"{PREFIX} 客户",
            "status": "ACTIVE",
            "credit_limit": Decimal("100000.00"),
            "created_by": admin,
            "owner": admin,
            "dept": dept,
        },
    )
    category, _ = ProductCategory.objects.get_or_create(name=f"{PREFIX} 分类")
    UnitService.init_common_units()
    unit = Unit.objects.get(name="件")
    product, _ = Product.objects.update_or_create(
        product_code=f"{PREFIX}-SKU",
        defaults={
            "name": f"{PREFIX} 商品",
            "category": category,
            "unit": unit,
            "cost_price": Decimal("25.50"),
            "sale_price": Decimal("40.00"),
            "status": "ACTIVE",
            "created_by": admin,
            "dept": dept,
        },
    )
    warehouse, _ = Warehouse.objects.update_or_create(
        warehouse_code=f"{PREFIX}-WH",
        defaults={
            "warehouse_name": f"{PREFIX} 主仓",
            "type": "MAIN",
            "manager": admin,
            "status": True,
        },
    )
    cash_account, _ = CashAccount.objects.update_or_create(
        name=f"{PREFIX} 现金账户",
        defaults={
            "type": "BANK",
            "account_no": f"{PREFIX}-BANK",
            "bank_name": "Web Test Bank",
            "current_balance": Decimal("100000.00"),
            "status": True,
        },
    )
    return {
        "dept": dept,
        "supplier": supplier,
        "customer": customer,
        "category": category,
        "unit": unit,
        "product": product,
        "warehouse": warehouse,
        "cash_account": cash_account,
    }


def create_purchase_flow(master, creator, approver):
    order = PurchaseOrderService.create_order(
        supplier=master["supplier"],
        items_data=[
            {
                "product": master["product"],
                "warehouse": master["warehouse"],
                "quantity": Decimal("10.000"),
                "unit_price": Decimal("25.50"),
            }
        ],
        user=creator,
        remark=f"{PREFIX} 网页测试采购 {timezone.now():%Y-%m-%d %H:%M:%S}",
    )
    PurchaseOrderService.submit_order(order, creator)
    PurchaseOrderService.approve_order(order, approver, "Web test approved")

    po_item = PurchaseOrderItem.objects.get(purchase_order=order, product=master["product"])
    receipt = PurchaseOrderService.create_receipt(
        order=order,
        warehouse=master["warehouse"],
        items_data=[
            {
                "purchase_order_item": po_item,
                "received_quantity": Decimal("10.000"),
            }
        ],
        user=creator,
        remark=f"{PREFIX} 网页测试入库",
    )
    PurchaseOrderService.complete_receipt(receipt, creator)
    order.refresh_from_db()
    receipt.refresh_from_db()
    ap = APAccount.objects.get(source_id=receipt.id, source_type="PURCHASE_RECEIPT")
    return order, receipt, ap


def create_approved_purchase_order(master, creator, approver):
    order = PurchaseOrderService.create_order(
        supplier=master["supplier"],
        items_data=[
            {
                "product": master["product"],
                "warehouse": master["warehouse"],
                "quantity": Decimal("6.000"),
                "unit_price": Decimal("25.50"),
            }
        ],
        user=creator,
        remark=f"{PREFIX} 待入库采购 {timezone.now():%Y-%m-%d %H:%M:%S}",
    )
    PurchaseOrderService.submit_order(order, creator)
    PurchaseOrderService.approve_order(order, approver, "Web test approved for receipt creation")
    order.refresh_from_db()
    return order


def create_sales_flow(master, creator, approver):
    order = SalesOrderService.create_order(
        customer=master["customer"],
        items_data=[
            {
                "product": master["product"],
                "warehouse": master["warehouse"],
                "quantity": Decimal("4.000"),
                "unit_price": Decimal("40.00"),
            }
        ],
        user=creator,
        remark=f"{PREFIX} 网页测试销售 {timezone.now():%Y-%m-%d %H:%M:%S}",
    )
    SalesOrderService.submit_order(order, creator)
    SalesOrderService.approve_order(order, approver, "Web test approved")
    SalesOrderService.allocate_stock(order, creator)
    order_item = order.items.get()
    outbound_orders = SalesOrderService.ship_order(
        order,
        [{"order_item": order_item, "quantity": Decimal("4.000")}],
        creator,
    )
    for outbound_order in outbound_orders:
        OutboundService.submit_order(outbound_order, creator)
        OutboundService.approve_order(outbound_order, approver)
        OutboundService.complete_order(outbound_order, creator)
    order.refresh_from_db()
    receivable = Receivable.objects.get(sales_order=order)
    return order, outbound_orders, receivable


def create_draft_sales_order(master, creator):
    order = SalesOrderService.create_order(
        customer=master["customer"],
        items_data=[
            {
                "product": master["product"],
                "warehouse": master["warehouse"],
                "quantity": Decimal("2.000"),
                "unit_price": Decimal("40.00"),
            }
        ],
        user=creator,
        remark=f"{PREFIX} 待修改销售 {timezone.now():%Y-%m-%d %H:%M:%S}",
    )
    order.refresh_from_db()
    return order


def main():
    admin = ensure_user(
        ADMIN_USERNAME,
        ADMIN_PASSWORD,
        is_staff=True,
        is_superuser=True,
        status=True,
    )
    tester = ensure_user(TESTER_USERNAME, TESTER_PASSWORD, status=True)
    admin_role = ensure_admin_permissions(admin)
    tester.roles.add(admin_role)
    master = ensure_master_data(admin, tester)

    purchase_order, receipt, ap = create_purchase_flow(master, tester, admin)
    approved_purchase_order = create_approved_purchase_order(master, tester, admin)
    sales_order, outbound_orders, receivable = create_sales_flow(master, tester, admin)
    draft_sales_order = create_draft_sales_order(master, tester)

    inventory = Inventory.objects.get(
        warehouse=master["warehouse"],
        product=master["product"],
    )
    master["product"].refresh_from_db()
    master["customer"].refresh_from_db()

    print("Web inventory flow seed completed.")
    print(f"Login: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    print(f"Tester: {TESTER_USERNAME} / {TESTER_PASSWORD}")
    print(f"Product: {master['product'].product_code} {master['product'].name}")
    print(f"Warehouse: {master['warehouse'].warehouse_code} {master['warehouse'].warehouse_name}")
    print(f"Purchase order: {purchase_order.purchase_order_no} status={purchase_order.status}")
    print(
        "Pending receipt purchase order: "
        f"{approved_purchase_order.purchase_order_no} status={approved_purchase_order.status}"
    )
    print(f"Purchase receipt: {receipt.receipt_no} status={receipt.status}")
    print(f"AP: {ap.ap_no} amount={ap.total_amount} status={ap.status}")
    print(f"Sales order: {sales_order.order_no} status={sales_order.status}")
    print(f"Draft sales order: {draft_sales_order.order_no} status={draft_sales_order.status}")
    print(f"Outbound orders: {', '.join(order.outbound_no for order in outbound_orders)}")
    print(f"AR: {receivable.receivable_no} amount={receivable.amount} status={receivable.status}")
    print(
        "Inventory: "
        f"current={inventory.current_qty} locked={inventory.locked_qty} "
        f"available={inventory.available_qty} product_current={master['product'].current_stock}"
    )
    print(f"Customer balance: {master['customer'].current_balance}")


if __name__ == "__main__":
    main()
