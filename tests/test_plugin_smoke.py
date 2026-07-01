import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_plugin_module_importable() -> None:
    module = importlib.import_module("main")
    assert module is not None


def test_plugin_has_register() -> None:
    module = importlib.import_module("main")
    assert hasattr(module, "SummonPlugin")
