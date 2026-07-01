import json
import os
import tempfile

from main import _load_rules, _save_rules, HELP_TEXT


def test_help_text_not_empty() -> None:
    assert len(HELP_TEXT) > 0
    assert "/at add" in HELP_TEXT
    assert "/at list" in HELP_TEXT


def test_save_and_load_rules() -> None:
    dummy = {
        "123456": {
            "rules": {
                "开黑": {
                    "members": ["111", "222"],
                    "message": "大召唤术",
                    "enabled": True,
                }
            },
            "permission_mode": "everyone",
        }
    }
    _save_rules(dummy)
    loaded = _load_rules()
    assert loaded == dummy
    os.remove(os.path.join("data", "plugins", "astrbot_plugin_summon", "rules.json"))
    os.rmdir(os.path.join("data", "plugins", "astrbot_plugin_summon"))
