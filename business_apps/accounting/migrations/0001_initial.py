import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


def seed_accounting_defaults(apps, schema_editor):
    AccountSubject = apps.get_model("accounting", "AccountSubject")
    CodeRule = apps.get_model("platform", "CodeRule")

    subjects = [
        ("1001", "库存现金", "ASSET", "DEBIT"),
        ("1002", "银行存款", "ASSET", "DEBIT"),
        ("1403", "原材料", "ASSET", "DEBIT"),
        ("1405", "库存商品", "ASSET", "DEBIT"),
        ("1122", "应收账款", "ASSET", "DEBIT"),
        ("2202", "应付账款", "LIABILITY", "CREDIT"),
        ("6001", "主营业务收入", "PNL", "CREDIT"),
    ]
    for code, name, category, balance_direction in subjects:
        AccountSubject.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "balance_direction": balance_direction,
                "level": 1,
                "is_leaf": True,
                "enabled": True,
            },
        )

    CodeRule.objects.get_or_create(
        rule_code="ACCOUNTING_VOUCHER",
        defaults={
            "rule_name": "会计凭证",
            "prefix": "V",
            "date_format": "%Y%m%d",
            "sequence_length": 4,
            "current_sequence": 0,
            "current_date_key": "",
            "reset_type": "DAY",
            "status": "ACTIVE",
        },
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform", "0002_alter_coderule_current_date_key_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountSubject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True, verbose_name="科目编码")),
                ("name", models.CharField(max_length=100, verbose_name="科目名称")),
                ("category", models.CharField(choices=[("ASSET", "资产"), ("LIABILITY", "负债"), ("EQUITY", "权益"), ("COST", "成本"), ("PNL", "损益")], max_length=20, verbose_name="科目类别")),
                ("balance_direction", models.CharField(choices=[("DEBIT", "借"), ("CREDIT", "贷")], max_length=10, verbose_name="余额方向")),
                ("level", models.PositiveIntegerField(default=1, verbose_name="级次")),
                ("is_leaf", models.BooleanField(default=True, verbose_name="末级科目")),
                ("enabled", models.BooleanField(default=True, verbose_name="是否启用")),
                ("remark", models.TextField(blank=True, null=True, verbose_name="备注")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_account_subjects", to=settings.AUTH_USER_MODEL)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="accounting.accountsubject", verbose_name="上级科目")),
            ],
            options={
                "verbose_name": "会计科目",
                "verbose_name_plural": "会计科目",
                "ordering": ["code"],
            },
        ),
        migrations.CreateModel(
            name="AccountingPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveIntegerField(verbose_name="年度")),
                ("month", models.PositiveIntegerField(verbose_name="期间")),
                ("start_date", models.DateField(verbose_name="开始日期")),
                ("end_date", models.DateField(verbose_name="结束日期")),
                ("status", models.CharField(choices=[("OPEN", "打开"), ("CLOSED", "关闭")], default="OPEN", max_length=10)),
                ("closed_at", models.DateTimeField(blank=True, null=True, verbose_name="关闭时间")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="closed_accounting_periods", to=settings.AUTH_USER_MODEL, verbose_name="关闭人")),
            ],
            options={
                "verbose_name": "会计期间",
                "verbose_name_plural": "会计期间",
                "ordering": ["-year", "-month"],
                "unique_together": {("year", "month")},
            },
        ),
        migrations.CreateModel(
            name="Voucher",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("voucher_no", models.CharField(max_length=50, unique=True, verbose_name="凭证号")),
                ("voucher_date", models.DateField(verbose_name="凭证日期")),
                ("voucher_type", models.CharField(max_length=30, verbose_name="凭证类型")),
                ("abstract", models.CharField(max_length=255, verbose_name="摘要")),
                ("source_type", models.CharField(max_length=50, verbose_name="来源单据类型")),
                ("source_id", models.IntegerField(verbose_name="来源单据ID")),
                ("source_document_no", models.CharField(max_length=100, verbose_name="来源单号")),
                ("total_debit", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18)),
                ("total_credit", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18)),
                ("status", models.CharField(choices=[("DRAFT", "草稿"), ("POSTED", "已过账")], default="POSTED", max_length=10)),
                ("posted_at", models.DateTimeField(blank=True, null=True, verbose_name="过账时间")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("period", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="vouchers", to="accounting.accountingperiod", verbose_name="会计期间")),
                ("posted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="posted_vouchers", to=settings.AUTH_USER_MODEL, verbose_name="过账人")),
            ],
            options={
                "verbose_name": "会计凭证",
                "verbose_name_plural": "会计凭证",
                "ordering": ["-voucher_date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="BusinessPostingLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=50, verbose_name="过账事件")),
                ("business_type", models.CharField(max_length=50, verbose_name="业务类型")),
                ("business_id", models.IntegerField(verbose_name="业务ID")),
                ("business_document_no", models.CharField(max_length=100, verbose_name="业务单号")),
                ("status", models.CharField(choices=[("SUCCESS", "成功"), ("FAILED", "失败")], default="SUCCESS", max_length=10)),
                ("error_message", models.TextField(blank=True, null=True, verbose_name="错误信息")),
                ("payload", models.JSONField(blank=True, default=dict, verbose_name="过账载荷")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_posting_logs", to=settings.AUTH_USER_MODEL)),
                ("voucher", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="posting_logs", to="accounting.voucher", verbose_name="凭证")),
            ],
            options={
                "verbose_name": "业务过账日志",
                "verbose_name_plural": "业务过账日志",
                "ordering": ["-created_at"],
                "unique_together": {("event_type", "business_type", "business_id")},
            },
        ),
        migrations.CreateModel(
            name="VoucherLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("line_no", models.PositiveIntegerField(verbose_name="行号")),
                ("summary", models.CharField(max_length=255, verbose_name="行摘要")),
                ("debit_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18)),
                ("credit_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18)),
                ("business_type", models.CharField(blank=True, max_length=50, null=True, verbose_name="业务类型")),
                ("business_id", models.IntegerField(blank=True, null=True, verbose_name="业务ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="voucher_lines", to="accounting.accountsubject", verbose_name="会计科目")),
                ("voucher", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="accounting.voucher", verbose_name="凭证")),
            ],
            options={
                "verbose_name": "凭证明细",
                "verbose_name_plural": "凭证明细",
                "ordering": ["voucher_id", "line_no"],
                "unique_together": {("voucher", "line_no")},
            },
        ),
        migrations.AddIndex(
            model_name="accountsubject",
            index=models.Index(fields=["code"], name="accounting_a_code_13aadb_idx"),
        ),
        migrations.AddIndex(
            model_name="accountsubject",
            index=models.Index(fields=["category"], name="accounting_a_categor_317bc5_idx"),
        ),
        migrations.AddIndex(
            model_name="accountsubject",
            index=models.Index(fields=["enabled"], name="accounting_a_enabled_242454_idx"),
        ),
        migrations.AddIndex(
            model_name="accountingperiod",
            index=models.Index(fields=["year", "month"], name="accounting_a_year_7d2b4e_idx"),
        ),
        migrations.AddIndex(
            model_name="accountingperiod",
            index=models.Index(fields=["start_date", "end_date"], name="accounting_a_start_d05542_idx"),
        ),
        migrations.AddIndex(
            model_name="accountingperiod",
            index=models.Index(fields=["status"], name="accounting_a_status_7c2e83_idx"),
        ),
        migrations.AddIndex(
            model_name="voucher",
            index=models.Index(fields=["voucher_no"], name="accounting_v_voucher_4afacf_idx"),
        ),
        migrations.AddIndex(
            model_name="voucher",
            index=models.Index(fields=["voucher_date"], name="accounting_v_voucher_9cbd84_idx"),
        ),
        migrations.AddIndex(
            model_name="voucher",
            index=models.Index(fields=["source_type", "source_id"], name="accounting_v_source__b457e7_idx"),
        ),
        migrations.AddIndex(
            model_name="voucher",
            index=models.Index(fields=["voucher_type"], name="accounting_v_voucher_12594a_idx"),
        ),
        migrations.AddIndex(
            model_name="voucherline",
            index=models.Index(fields=["subject"], name="accounting_v_subject_ce0d25_idx"),
        ),
        migrations.AddIndex(
            model_name="voucherline",
            index=models.Index(fields=["business_type", "business_id"], name="accounting_v_busines_3726d1_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspostinglog",
            index=models.Index(fields=["event_type"], name="accounting_b_event_t_c7672f_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspostinglog",
            index=models.Index(fields=["business_type", "business_id"], name="accounting_b_busines_458e1b_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspostinglog",
            index=models.Index(fields=["business_document_no"], name="accounting_b_busines_155208_idx"),
        ),
        migrations.RunPython(seed_accounting_defaults, migrations.RunPython.noop),
    ]
