from __future__ import annotations

from typing import Any


class BasePolicy:
    module_key: str = ""

    def __init__(self, runtime_config, user=None):
        self.runtime_config = runtime_config
        self.user = user

    def is_module_enabled(self) -> bool:
        return self.runtime_config.is_enabled(self.module_key)

    def is_feature_enabled(self, feature_key: str, default: bool = False) -> bool:
        if not self.is_module_enabled():
            return False
        value = self.runtime_config.is_feature_enabled(self.module_key, feature_key)
        if value is None:
            return default
        return value

    def get_default(self, key: str, default: Any = None) -> Any:
        return self.runtime_config.get_default(key, default=default, module_key=self.module_key)

    def get_workflow(self, workflow_key: str, default: Any = None) -> Any:
        return self.runtime_config.get_workflow(self.module_key, workflow_key, default=default)

    def get_field_rule(self, field_key: str, default: Any = None) -> Any:
        return self.runtime_config.get_field_rule(self.module_key, field_key, default=default)
