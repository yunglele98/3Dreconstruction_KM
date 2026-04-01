"""
Pytest conftest.py — fixes import resolution for scripts/ directory.

Problem: A ghost scripts/__init__.py (mount-sync artifact) makes Python treat
scripts/ as a package. This breaks bare imports like `from enrich_skeletons import ...`
when sys.path includes scripts/, because Python resolves `scripts` as a package
first and won't search inside it for top-level module names.

Solution: For every .py file in scripts/, register it as a top-level module in
sys.modules so that `from enrich_skeletons import enrich_file` works regardless
of whether scripts/ is seen as a package.
"""
import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _register_script_modules():
    """Pre-register all scripts/*.py as importable top-level modules."""
    if not SCRIPTS_DIR.is_dir():
        return

    # Ensure scripts/ is on sys.path for package-style imports too
    scripts_str = str(SCRIPTS_DIR)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)

    # Also ensure project root is on path
    root_str = str(SCRIPTS_DIR.parent)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    for py_file in sorted(SCRIPTS_DIR.glob("*.py")):
        mod_name = py_file.stem
        if mod_name == "__init__" or mod_name.startswith("_"):
            continue
        # Skip if already imported
        if mod_name in sys.modules:
            continue
        try:
            spec = importlib.util.spec_from_file_location(mod_name, str(py_file))
            if spec and spec.loader:
                # Register a lazy loader — don't actually execute the module yet
                # Just make it findable
                sys.modules[mod_name] = importlib.util.module_from_spec(spec)
                # We do NOT call spec.loader.exec_module() here — that happens
                # on first attribute access. But for pytest collection we need
                # the module to be importable, so we exec it now.
                try:
                    spec.loader.exec_module(sys.modules[mod_name])
                except Exception:
                    # If a script fails to import (e.g. needs bpy), remove it
                    # so the normal import error surfaces at test time
                    del sys.modules[mod_name]
        except Exception:
            pass


_register_script_modules()
