from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase


class TenantScopeGuardTest(SimpleTestCase):
    TARGET_FILES = [
        Path("backend/business_apps/ap_payable/views.py"),
        Path("backend/business_apps/ar_receivable/views.py"),
        Path("backend/business_apps/accounting/views.py"),
        Path("backend/business_apps/finance/views.py"),
        Path("backend/business_apps/inventory/views.py"),
        Path("backend/business_apps/purchase/views.py"),
        Path("backend/business_apps/reports/views.py"),
        Path("backend/business_apps/sales/views.py"),
        Path("backend/business_apps/supplier/views.py"),
        Path("backend/business_apps/supply_chain/views.py"),
        Path("backend/business_apps/inventory/policies.py"),
        Path("backend/core_apps/erp_auth/views.py"),
        Path("backend/core_apps/tenant/views.py"),
    ]

    def test_request_entrypoints_do_not_use_raw_objects_get(self):
        pattern = re.compile(r"\.objects\.get\(")
        repo_root = Path(__file__).resolve().parents[2]
        violations: list[str] = []

        for relative_path in self.TARGET_FILES:
            path = repo_root / relative_path
            if not path.exists():
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not pattern.search(line):
                    continue
                if "tenant=" in line or "created_by=" in line:
                    continue
                violations.append(f"{relative_path}:{line_no}: {line.strip()}")

        self.assertEqual(
            violations,
            [],
            "Raw `.objects.get(...)` calls remain in request entrypoints:\n" + "\n".join(violations),
        )
