from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from business_apps.platform.services import CodeRuleService
from core_apps.erp_auth.compat import build_erp_user_fk_kwargs
from core_apps.erp_auth.models import ERPUser
from core_apps.policies.registry import get_policy

from .models import (
    AccountSubject,
    AccountingPeriod,
    Voucher,
    VoucherLine,
    BusinessPostingLog,
)


class PeriodService:
    @staticmethod
    @transaction.atomic
    def get_or_create_period(business_date, tenant=None):
        last_day = monthrange(business_date.year, business_date.month)[1]
        period, _created = AccountingPeriod.objects.select_for_update().get_or_create(
            tenant=tenant,
            year=business_date.year,
            month=business_date.month,
            defaults={
                "start_date": date(business_date.year, business_date.month, 1),
                "end_date": date(business_date.year, business_date.month, last_day),
                "status": AccountingPeriod.STATUS_OPEN,
            },
        )
        return period

    @staticmethod
    @transaction.atomic
    def ensure_open(business_date, tenant=None):
        period = PeriodService.get_or_create_period(business_date, tenant=tenant)
        if period.status != AccountingPeriod.STATUS_OPEN:
            raise ValueError(f"会计期间 {period} 已关闭，禁止过账")
        return period

    @staticmethod
    @transaction.atomic
    def close_period(period, user):
        policy = get_policy("accounting", user=user)
        if not policy.period_close_enabled():
            raise ValueError("当前配置未启用会计期间关账")
        period = AccountingPeriod.objects.select_for_update().get(id=period.id)
        if period.status == AccountingPeriod.STATUS_CLOSED:
            return period
        period.status = AccountingPeriod.STATUS_CLOSED
        period.closed_at = timezone.now()
        period.closed_by = build_erp_user_fk_kwargs(
            AccountingPeriod,
            user=user,
            field_names=("closed_by",),
        ).get("closed_by")
        period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        return period

    @staticmethod
    @transaction.atomic
    def open_period(period, user=None):
        policy = get_policy("accounting", user=user)
        if not policy.period_close_enabled():
            raise ValueError("当前配置未启用会计期间关账")
        period = AccountingPeriod.objects.select_for_update().get(id=period.id)
        if period.status == AccountingPeriod.STATUS_OPEN:
            return period
        period.status = AccountingPeriod.STATUS_OPEN
        period.closed_at = None
        period.closed_by = None
        period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        return period


class SubjectInitService:
    DEFAULT_SUBJECTS = [
        {"code": "1001", "name": "库存现金", "category": "ASSET", "balance_direction": "DEBIT"},
        {"code": "1002", "name": "银行存款", "category": "ASSET", "balance_direction": "DEBIT"},
        {"code": "1403", "name": "原材料", "category": "ASSET", "balance_direction": "DEBIT"},
        {"code": "1405", "name": "库存商品", "category": "ASSET", "balance_direction": "DEBIT"},
        {"code": "1122", "name": "应收账款", "category": "ASSET", "balance_direction": "DEBIT"},
        {"code": "2202", "name": "应付账款", "category": "LIABILITY", "balance_direction": "CREDIT"},
        {"code": "6001", "name": "主营业务收入", "category": "PNL", "balance_direction": "CREDIT"},
    ]

    @staticmethod
    @transaction.atomic
    def init_subjects(created_by=None, tenant=None):
        if tenant is None and isinstance(created_by, ERPUser):
            tenant = created_by.tenant
        created_by_value = build_erp_user_fk_kwargs(
            AccountSubject,
            user=created_by,
            field_names=("created_by",),
        ).get("created_by")
        created_subjects = []
        for item in SubjectInitService.DEFAULT_SUBJECTS:
            subject, created = AccountSubject.objects.get_or_create(
                tenant=tenant,
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "category": item["category"],
                    "balance_direction": item["balance_direction"],
                    "level": 1,
                    "is_leaf": True,
                    "enabled": True,
                    "created_by": created_by_value,
                },
            )
            if created:
                created_subjects.append(subject)
        return created_subjects

    @staticmethod
    def generate_subject_code(*, tenant=None) -> str:
        tenant_subjects = AccountSubject.objects.filter(tenant=tenant, code__startswith="SUBJ")
        existing_codes = tenant_subjects.values_list("code", flat=True)
        next_sequence = 1
        for code in existing_codes:
            suffix = code.removeprefix("SUBJ")
            if suffix.isdigit():
                next_sequence = max(next_sequence, int(suffix) + 1)
        return f"SUBJ{next_sequence:04d}"


class VoucherService:
    @staticmethod
    def _resolve_tenant(operator=None, tenant=None):
        if tenant is not None:
            return tenant
        if isinstance(operator, ERPUser):
            return operator.tenant
        return None

    @staticmethod
    def _normalize_amount(amount):
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        return value.quantize(Decimal("0.01"))

    @staticmethod
    def _load_subject(subject_code, tenant=None):
        try:
            return AccountSubject.objects.get(code=subject_code, enabled=True, tenant=tenant)
        except AccountSubject.DoesNotExist as exc:
            raise ValueError(f"缺少会计科目 {subject_code}，请先初始化基础科目") from exc

    @staticmethod
    def _resolve_cash_subject_code(cash_account):
        if not cash_account:
            return "1002"
        account_type = getattr(cash_account, "account_type", None) or getattr(cash_account, "type", None)
        return "1001" if account_type == "CASH" else "1002"

    @staticmethod
    @transaction.atomic
    def create_voucher(
        *,
        voucher_date,
        voucher_type,
        abstract,
        source_type,
        source_id,
        source_document_no,
        line_specs,
        operator=None,
        tenant=None,
    ):
        tenant = VoucherService._resolve_tenant(operator=operator, tenant=tenant)
        period = PeriodService.ensure_open(voucher_date, tenant=tenant)
        voucher = Voucher.objects.create(
            tenant=tenant,
            voucher_no=CodeRuleService.generate("ACCOUNTING_VOUCHER"),
            voucher_date=voucher_date,
            period=period,
            voucher_type=voucher_type,
            abstract=abstract,
            source_type=source_type,
            source_id=source_id,
            source_document_no=source_document_no,
            posted_at=timezone.now(),
            status=Voucher.STATUS_POSTED,
            **build_erp_user_fk_kwargs(
                Voucher,
                user=operator,
                field_names=("posted_by",),
            ),
        )

        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        lines = []
        for index, spec in enumerate(line_specs, start=1):
            subject = VoucherService._load_subject(spec["subject_code"], tenant=tenant)
            debit_amount = VoucherService._normalize_amount(spec.get("debit_amount", 0))
            credit_amount = VoucherService._normalize_amount(spec.get("credit_amount", 0))
            if debit_amount <= 0 and credit_amount <= 0:
                raise ValueError("凭证明细借贷金额不能同时为0")
            lines.append(
                VoucherLine(
                    tenant=tenant,
                    voucher=voucher,
                    line_no=index,
                    subject=subject,
                    summary=spec["summary"],
                    debit_amount=debit_amount,
                    credit_amount=credit_amount,
                    business_type=spec.get("business_type"),
                    business_id=spec.get("business_id"),
                )
            )
            total_debit += debit_amount
            total_credit += credit_amount

        total_debit = total_debit.quantize(Decimal("0.01"))
        total_credit = total_credit.quantize(Decimal("0.01"))
        if total_debit != total_credit:
            raise ValueError(f"凭证借贷不平衡：借 {total_debit}，贷 {total_credit}")

        VoucherLine.objects.bulk_create(lines)
        voucher.total_debit = total_debit
        voucher.total_credit = total_credit
        voucher.save(update_fields=["total_debit", "total_credit", "updated_at"])
        return voucher

    @staticmethod
    def build_purchase_receipt_lines(receipt, amount):
        summary = f"采购入库确认应付 {receipt.receipt_no}"
        return [
            {
                "subject_code": "1405",
                "summary": summary,
                "debit_amount": amount,
                "business_type": "PURCHASE_RECEIPT",
                "business_id": receipt.id,
            },
            {
                "subject_code": "2202",
                "summary": summary,
                "credit_amount": amount,
                "business_type": "PURCHASE_RECEIPT",
                "business_id": receipt.id,
            },
        ]

    @staticmethod
    def build_sales_outbound_lines(order, amount):
        summary = f"销售出库确认应收 {order.outbound_no}"
        return [
            {
                "subject_code": "1122",
                "summary": summary,
                "debit_amount": amount,
                "business_type": "OUTBOUND_ORDER",
                "business_id": order.id,
            },
            {
                "subject_code": "6001",
                "summary": summary,
                "credit_amount": amount,
                "business_type": "OUTBOUND_ORDER",
                "business_id": order.id,
            },
        ]

    @staticmethod
    def build_receipt_lines(receipt):
        summary = f"收款执行 {receipt.receipt_no}"
        cash_subject_code = VoucherService._resolve_cash_subject_code(receipt.cash_account)
        return [
            {
                "subject_code": cash_subject_code,
                "summary": summary,
                "debit_amount": receipt.amount,
                "business_type": "AR_RECEIPT",
                "business_id": receipt.id,
            },
            {
                "subject_code": "1122",
                "summary": summary,
                "credit_amount": receipt.amount,
                "business_type": "AR_RECEIPT",
                "business_id": receipt.id,
            },
        ]

    @staticmethod
    def build_payment_lines(payment):
        summary = f"付款执行 {payment.payment_no}"
        cash_subject_code = VoucherService._resolve_cash_subject_code(payment.cash_account)
        return [
            {
                "subject_code": "2202",
                "summary": summary,
                "debit_amount": payment.payment_amount,
                "business_type": "AP_PAYMENT",
                "business_id": payment.id,
            },
            {
                "subject_code": cash_subject_code,
                "summary": summary,
                "credit_amount": payment.payment_amount,
                "business_type": "AP_PAYMENT",
                "business_id": payment.id,
            },
        ]

    @staticmethod
    def build_customer_refund_lines(refund):
        summary = f"客户退款 {refund.refund_no}"
        cash_subject_code = VoucherService._resolve_cash_subject_code(refund.cash_account)
        return [
            {
                "subject_code": "1122",
                "summary": summary,
                "debit_amount": refund.refund_amount,
                "business_type": "AR_REFUND",
                "business_id": refund.id,
            },
            {
                "subject_code": cash_subject_code,
                "summary": summary,
                "credit_amount": refund.refund_amount,
                "business_type": "AR_REFUND",
                "business_id": refund.id,
            },
        ]

    @staticmethod
    def build_supplier_refund_lines(refund):
        summary = f"供应商退款 {refund.refund_no}"
        cash_subject_code = VoucherService._resolve_cash_subject_code(refund.cash_account)
        return [
            {
                "subject_code": cash_subject_code,
                "summary": summary,
                "debit_amount": refund.refund_amount,
                "business_type": "AP_SUPPLIER_REFUND",
                "business_id": refund.id,
            },
            {
                "subject_code": "2202",
                "summary": summary,
                "credit_amount": refund.refund_amount,
                "business_type": "AP_SUPPLIER_REFUND",
                "business_id": refund.id,
            },
        ]

    @staticmethod
    def build_sales_return_lines(return_order, amount):
        summary = f"销售退货 {return_order.return_no}"
        return [
            {
                "subject_code": "6001",
                "summary": summary,
                "debit_amount": amount,
                "business_type": "SALES_RETURN_ORDER",
                "business_id": return_order.id,
            },
            {
                "subject_code": "1122",
                "summary": summary,
                "credit_amount": amount,
                "business_type": "SALES_RETURN_ORDER",
                "business_id": return_order.id,
            },
        ]

    @staticmethod
    def build_purchase_return_lines(return_order, amount):
        summary = f"采购退货 {return_order.return_no}"
        return [
            {
                "subject_code": "2202",
                "summary": summary,
                "debit_amount": amount,
                "business_type": "PURCHASE_RETURN_ORDER",
                "business_id": return_order.id,
            },
            {
                "subject_code": "1405",
                "summary": summary,
                "credit_amount": amount,
                "business_type": "PURCHASE_RETURN_ORDER",
                "business_id": return_order.id,
            },
        ]


class PostingService:
    EVENT_PURCHASE_RECEIPT = "PURCHASE_RECEIPT_CONFIRMED"
    EVENT_SALES_OUTBOUND = "SALES_OUTBOUND_CONFIRMED"
    EVENT_RECEIPT_EXECUTED = "RECEIPT_EXECUTED"
    EVENT_PAYMENT_EXECUTED = "PAYMENT_EXECUTED"
    EVENT_SALES_RETURN = "SALES_RETURN_COMPLETED"
    EVENT_PURCHASE_RETURN = "PURCHASE_RETURN_COMPLETED"
    EVENT_CUSTOMER_REFUND = "CUSTOMER_REFUND_EXECUTED"
    EVENT_SUPPLIER_REFUND = "SUPPLIER_REFUND_EXECUTED"

    @staticmethod
    def _sum_outbound_amount(order):
        result = order.items.aggregate(total=Sum("amount"))["total"]
        amount = result or Decimal("0")
        return VoucherService._normalize_amount(amount)

    @staticmethod
    def _sum_purchase_receipt_amount(receipt, receipt_event=None):
        if receipt_event:
            return VoucherService._normalize_amount(receipt_event["total_amount"])
        total = Decimal("0")
        for item in receipt.items.select_related("purchase_order_item").all():
            total += Decimal(str(item.received_quantity)) * Decimal(str(item.purchase_order_item.unit_price))
        return VoucherService._normalize_amount(total)

    @staticmethod
    def _sum_sales_return_amount(return_order):
        from business_apps.supply_chain.services import SalesReturnService

        total = Decimal("0")
        allocations_by_item = SalesReturnService.build_sales_order_item_allocations(
            return_order,
            exclude_return_order_id=return_order.id,
        )
        for item in return_order.items.all():
            allocations = allocations_by_item.get(item.id, [])
            if allocations:
                for sales_item, allocated_quantity in allocations:
                    total += Decimal(str(allocated_quantity)) * Decimal(str(sales_item.unit_price))
            else:
                total += Decimal(str(item.quantity)) * Decimal(str(item.product.sale_price or Decimal("0")))
        return VoucherService._normalize_amount(total)

    @staticmethod
    def _sum_purchase_return_amount(return_order):
        from business_apps.supply_chain.services import PurchaseReturnService

        total = Decimal("0")
        allocations_by_item = PurchaseReturnService.build_purchase_order_item_allocations(return_order)
        for item in return_order.items.all():
            allocations = allocations_by_item.get(item.id, [])
            if allocations:
                for purchase_item, allocated_quantity in allocations:
                    total += Decimal(str(allocated_quantity)) * Decimal(str(purchase_item.unit_price))
            else:
                total += Decimal(str(item.quantity)) * Decimal(str(item.product.cost_price or Decimal("0")))
        return VoucherService._normalize_amount(total)

    @staticmethod
    @transaction.atomic
    def _post_once(
        *,
        event_type,
        business_type,
        business_id,
        business_document_no,
        payload,
        voucher_factory,
        operator=None,
        tenant=None,
    ):
        log = (
            BusinessPostingLog.objects.select_for_update()
            .filter(event_type=event_type, business_type=business_type, business_id=business_id, tenant=tenant)
            .first()
        )
        if log and log.voucher_id:
            return log.voucher, log

        voucher = voucher_factory()
        if log:
            log.voucher = voucher
            log.status = BusinessPostingLog.STATUS_SUCCESS
            log.error_message = ""
            log.payload = payload
            log.created_by = build_erp_user_fk_kwargs(
                BusinessPostingLog,
                user=operator,
                field_names=("created_by",),
            ).get("created_by")
            log.save(update_fields=["voucher", "status", "error_message", "payload", "created_by"])
            return voucher, log

        log = BusinessPostingLog.objects.create(
            tenant=tenant,
            event_type=event_type,
            business_type=business_type,
            business_id=business_id,
            business_document_no=business_document_no,
            voucher=voucher,
            status=BusinessPostingLog.STATUS_SUCCESS,
            payload=payload,
            **build_erp_user_fk_kwargs(
                BusinessPostingLog,
                user=operator,
                field_names=("created_by",),
            ),
        )
        return voucher, log

    @staticmethod
    @transaction.atomic
    def post_purchase_receipt(receipt, operator=None, receipt_event=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.inventory_posting_enabled():
            return None
        amount = PostingService._sum_purchase_receipt_amount(receipt, receipt_event=receipt_event)
        if amount <= 0:
            raise ValueError("采购入库过账金额必须大于0")
        voucher_date = receipt.received_at.date() if receipt.received_at else timezone.localdate()
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "PURCHASE_RECEIPT",
            "source_id": receipt.id,
        }
        return PostingService._post_once(
            tenant=receipt.tenant,
            event_type=PostingService.EVENT_PURCHASE_RECEIPT,
            business_type="PURCHASE_RECEIPT",
            business_id=receipt.id,
            business_document_no=receipt.receipt_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="PURCHASE_RECEIPT",
                abstract=f"采购入库确认应付 {receipt.receipt_no}",
                source_type="PURCHASE_RECEIPT",
                source_id=receipt.id,
                source_document_no=receipt.receipt_no,
                line_specs=VoucherService.build_purchase_receipt_lines(receipt, amount),
                operator=operator,
                tenant=receipt.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_sales_outbound(order, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.inventory_posting_enabled():
            return None
        amount = PostingService._sum_outbound_amount(order)
        if amount <= 0:
            raise ValueError("销售出库过账金额必须大于0")
        voucher_date = order.completed_at.date() if order.completed_at else timezone.localdate()
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "OUTBOUND_ORDER",
            "source_id": order.id,
        }
        return PostingService._post_once(
            tenant=order.tenant,
            event_type=PostingService.EVENT_SALES_OUTBOUND,
            business_type="OUTBOUND_ORDER",
            business_id=order.id,
            business_document_no=order.outbound_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="SALES_OUTBOUND",
                abstract=f"销售出库确认应收 {order.outbound_no}",
                source_type="OUTBOUND_ORDER",
                source_id=order.id,
                source_document_no=order.outbound_no,
                line_specs=VoucherService.build_sales_outbound_lines(order, amount),
                operator=operator,
                tenant=order.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_receipt_execution(receipt, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.ar_ap_posting_enabled():
            return None
        amount = VoucherService._normalize_amount(receipt.amount)
        if amount <= 0:
            raise ValueError("收款过账金额必须大于0")
        voucher_date = receipt.receipt_date
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "AR_RECEIPT",
            "source_id": receipt.id,
        }
        return PostingService._post_once(
            tenant=receipt.tenant,
            event_type=PostingService.EVENT_RECEIPT_EXECUTED,
            business_type="AR_RECEIPT",
            business_id=receipt.id,
            business_document_no=receipt.receipt_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="AR_RECEIPT",
                abstract=f"收款执行 {receipt.receipt_no}",
                source_type="AR_RECEIPT",
                source_id=receipt.id,
                source_document_no=receipt.receipt_no,
                line_specs=VoucherService.build_receipt_lines(receipt),
                operator=operator,
                tenant=receipt.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_payment_execution(payment, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.ar_ap_posting_enabled():
            return None
        amount = VoucherService._normalize_amount(payment.payment_amount)
        if amount <= 0:
            raise ValueError("付款过账金额必须大于0")
        voucher_date = payment.payment_date
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "AP_PAYMENT",
            "source_id": payment.id,
        }
        return PostingService._post_once(
            tenant=payment.tenant,
            event_type=PostingService.EVENT_PAYMENT_EXECUTED,
            business_type="AP_PAYMENT",
            business_id=payment.id,
            business_document_no=payment.payment_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="AP_PAYMENT",
                abstract=f"付款执行 {payment.payment_no}",
                source_type="AP_PAYMENT",
                source_id=payment.id,
                source_document_no=payment.payment_no,
                line_specs=VoucherService.build_payment_lines(payment),
                operator=operator,
                tenant=payment.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_customer_refund_execution(refund, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.ar_ap_posting_enabled():
            return None
        amount = VoucherService._normalize_amount(refund.refund_amount)
        if amount <= 0:
            raise ValueError("客户退款过账金额必须大于0")
        voucher_date = refund.refund_date
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "AR_REFUND",
            "source_id": refund.id,
        }
        return PostingService._post_once(
            tenant=refund.tenant,
            event_type=PostingService.EVENT_CUSTOMER_REFUND,
            business_type="AR_REFUND",
            business_id=refund.id,
            business_document_no=refund.refund_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="AR_REFUND",
                abstract=f"客户退款 {refund.refund_no}",
                source_type="AR_REFUND",
                source_id=refund.id,
                source_document_no=refund.refund_no,
                line_specs=VoucherService.build_customer_refund_lines(refund),
                operator=operator,
                tenant=refund.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_supplier_refund_execution(refund, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.ar_ap_posting_enabled():
            return None
        amount = VoucherService._normalize_amount(refund.refund_amount)
        if amount <= 0:
            raise ValueError("供应商退款过账金额必须大于0")
        voucher_date = refund.refund_date
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "AP_SUPPLIER_REFUND",
            "source_id": refund.id,
        }
        return PostingService._post_once(
            tenant=refund.tenant,
            event_type=PostingService.EVENT_SUPPLIER_REFUND,
            business_type="AP_SUPPLIER_REFUND",
            business_id=refund.id,
            business_document_no=refund.refund_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="AP_SUPPLIER_REFUND",
                abstract=f"供应商退款 {refund.refund_no}",
                source_type="AP_SUPPLIER_REFUND",
                source_id=refund.id,
                source_document_no=refund.refund_no,
                line_specs=VoucherService.build_supplier_refund_lines(refund),
                operator=operator,
                tenant=refund.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_sales_return(return_order, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.inventory_posting_enabled():
            return None
        amount = PostingService._sum_sales_return_amount(return_order)
        if amount <= 0:
            raise ValueError("销售退货过账金额必须大于0")
        voucher_date = return_order.completed_at.date() if return_order.completed_at else timezone.localdate()
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "SALES_RETURN_ORDER",
            "source_id": return_order.id,
        }
        return PostingService._post_once(
            tenant=return_order.tenant,
            event_type=PostingService.EVENT_SALES_RETURN,
            business_type="SALES_RETURN_ORDER",
            business_id=return_order.id,
            business_document_no=return_order.return_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="SALES_RETURN",
                abstract=f"销售退货 {return_order.return_no}",
                source_type="SALES_RETURN_ORDER",
                source_id=return_order.id,
                source_document_no=return_order.return_no,
                line_specs=VoucherService.build_sales_return_lines(return_order, amount),
                operator=operator,
                tenant=return_order.tenant,
            ),
        )[0]

    @staticmethod
    @transaction.atomic
    def post_purchase_return(return_order, operator=None):
        policy = get_policy("accounting", user=operator)
        if not policy.voucher_auto_posting_enabled() or not policy.inventory_posting_enabled():
            return None
        amount = PostingService._sum_purchase_return_amount(return_order)
        if amount <= 0:
            raise ValueError("采购退货过账金额必须大于0")
        voucher_date = return_order.completed_at.date() if return_order.completed_at else timezone.localdate()
        payload = {
            "amount": str(amount),
            "voucher_date": voucher_date.isoformat(),
            "source_type": "PURCHASE_RETURN_ORDER",
            "source_id": return_order.id,
        }
        return PostingService._post_once(
            tenant=return_order.tenant,
            event_type=PostingService.EVENT_PURCHASE_RETURN,
            business_type="PURCHASE_RETURN_ORDER",
            business_id=return_order.id,
            business_document_no=return_order.return_no,
            payload=payload,
            operator=operator,
            voucher_factory=lambda: VoucherService.create_voucher(
                voucher_date=voucher_date,
                voucher_type="PURCHASE_RETURN",
                abstract=f"采购退货 {return_order.return_no}",
                source_type="PURCHASE_RETURN_ORDER",
                source_id=return_order.id,
                source_document_no=return_order.return_no,
                line_specs=VoucherService.build_purchase_return_lines(return_order, amount),
                operator=operator,
                tenant=return_order.tenant,
            ),
        )[0]
