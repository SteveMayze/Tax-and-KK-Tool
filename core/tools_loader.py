"""Test helper: load tools/pdf_inventory.py (the tools folder is not a package)."""
import importlib.util
from pathlib import Path


def load():
    path = Path(__file__).resolve().parent.parent / 'tools' / 'pdf_inventory.py'
    spec = importlib.util.spec_from_file_location('pdf_inventory_tool', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
