from __future__ import annotations

from core_apps.policies.base import BasePolicy

from .features import (
    FEATURE_CODE_RULE_CENTER,
    FEATURE_DICT_CENTER,
    FEATURE_FILE_CENTER,
)


class PlatformPolicy(BasePolicy):
    module_key = "platform"

    def file_center_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_FILE_CENTER, default=True)

    def dict_center_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_DICT_CENTER, default=False)

    def code_rule_center_enabled(self) -> bool:
        return self.is_feature_enabled(FEATURE_CODE_RULE_CENTER, default=False)
