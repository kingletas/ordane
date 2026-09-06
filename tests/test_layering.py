"""The layers are a rule, not a folder arrangement.

A directory called `core` proves nothing. These are the checks that make the
names true: what each layer may import, and that the engine can be imported on
a machine with no toolkit and no web framework on it at all.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "ordane"

# Read bottom to top: each layer may import the ones above it and nothing else.
ALLOWED = {
    "presentation": set(),
    "core": {"presentation"},
    "record": {"presentation", "core"},
    "insight": {"presentation", "core", "record"},
    "desktop": {"presentation", "core", "record", "insight"},
    "web": {"presentation", "core", "record", "insight", "web"},
    "terminal": {"presentation", "core", "record", "insight"},
}

# What the engine must never need. A front end may import any of them.
FRONT_END_ONLY = ("gi", "fastapi", "uvicorn", "starlette", "jinja2")

ENGINE = ("presentation", "core", "record", "insight")


def modules_in(layer: str):
    return sorted((PACKAGE / layer).rglob("*.py"))


def imported_layers(path: Path) -> set[str]:
    """Which sibling layers this file reaches into, by reading its imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    own = path.relative_to(PACKAGE).parts[0]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module:
            found.add(node.module.split(".")[0])
        if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module is None:
            found.update(alias.name for alias in node.names)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("ordane."):
                    found.add(alias.name.split(".")[1])
    return {name for name in found if name in ALLOWED and name != own}


def test_every_layer_imports_only_what_it_is_allowed_to():
    for layer, allowed in ALLOWED.items():
        for path in modules_in(layer):
            reached = imported_layers(path)
            forbidden = reached - allowed
            assert not forbidden, (
                f"{path.relative_to(ROOT)} imports {sorted(forbidden)}; "
                f"`{layer}` may only import {sorted(allowed) or 'nothing'}"
            )


def test_presentation_depends_on_nothing_in_this_package():
    for path in modules_in("presentation"):
        assert not imported_layers(path), f"{path.name} reaches out of presentation"


def test_the_engine_imports_no_toolkit_and_no_web_framework():
    """In a fresh interpreter: importing a module twice in one session hides this."""
    program = (
        "import sys, importlib\n"
        f"for layer in {ENGINE!r}:\n"
        "    for name in ('catalog','config','allowlist','command','search','doctor','recent',\n"
        "                 'store','runner','summary','dora','redact','metrics','health',\n"
        "                 'language','text','ansi'):\n"
        "        try:\n"
        "            importlib.import_module(f'ordane.{layer}.{name}')\n"
        "        except ModuleNotFoundError:\n"
        "            continue\n"
        f"leaked = [m for m in {FRONT_END_ONLY!r} if m in sys.modules]\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True, cwd=ROOT
    )
    leaked = result.stdout.strip()
    assert not leaked, f"importing the engine pulled in {leaked}"


def test_the_desktop_package_is_the_only_place_gtk_is_named():
    for layer in ENGINE + ("web", "terminal"):
        for path in modules_in(layer):
            text = path.read_text(encoding="utf-8")
            assert "gi.repository" not in text, f"{path.relative_to(ROOT)} names GTK"


def test_every_layer_says_what_it_is_for():
    for layer in ALLOWED:
        init = PACKAGE / layer / "__init__.py"
        assert init.is_file(), f"{layer} has no __init__.py"
        assert ast.get_docstring(ast.parse(init.read_text(encoding="utf-8"))), (
            f"{layer}/__init__.py does not say what the layer is for"
        )


# --- and the suite itself, which is what CI actually runs -------------------


def test_the_unit_suite_runs_with_no_toolkit_installed():
    """`make check` proves the engine needs no GTK, so one test file importing a
    widget breaks that job.

    Every test module is imported in a fresh interpreter where `gi` cannot be found.
    A rule about which names a test may mention would be wrong in both directions.
    """
    program = (
        "import sys, importlib, pathlib\n"
        "class NoToolkit:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name == 'gi' or name.startswith('gi.') else None\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'gi' or name.startswith('gi.'):\n"
        "            raise ModuleNotFoundError(f'no {name} here')\n"
        "        return None\n"
        "sys.meta_path.insert(0, NoToolkit())\n"
        "sys.path.insert(0, 'tests')\n"
        "broken = []\n"
        "for path in sorted(pathlib.Path('tests').glob('test_*.py')):\n"
        "    try:\n"
        "        importlib.import_module(path.stem)\n"
        "    except ModuleNotFoundError as exc:\n"
        "        if 'gi' in str(exc):\n"
        "            broken.append(f'{path.name}: {exc}')\n"
        # BaseException, not Exception: `pytest.importorskip` raises pytest's
        # own Skipped, which does not inherit from Exception. A file that skips
        # itself when there is no toolkit is doing the right thing, and letting
        # that kill the probe made this fail with a traceback about subprocess.
        "    except BaseException:\n"
        "        pass\n"
        "print('; '.join(broken))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True, cwd=ROOT
    )
    broken = result.stdout.strip()
    assert not broken, f"these need a toolkit the check job does not install: {broken}"
