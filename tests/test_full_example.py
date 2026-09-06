"""The reference configuration, checked against the code that reads it.

An example is documentation, and documentation drifts. This one is loaded like
any control plane's file, and every key the loader looks for has to appear in
it, so a key added without being documented fails here rather than being
discovered by somebody who needed it.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import yaml

from ordane.core import config as config_module

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "ordane.full.yml"
LOADER = ROOT / "src" / "ordane" / "core" / "config.py"


def keys_the_loader_reads() -> set[str]:
    """Every `raw.get("...")` in the loader, read from its own source."""
    tree = ast.parse(LOADER.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or getattr(node.func, "attr", "") != "get":
            continue
        target = getattr(node.func, "value", None)
        if isinstance(target, ast.Name) and target.id == "raw" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def test_the_example_is_valid_yaml():
    assert isinstance(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")), dict)


def test_the_example_loads_as_a_configuration(tmp_path):
    """Not merely parseable: accepted by the loader, refusals and all."""
    shutil.copy(EXAMPLE, tmp_path / config_module.CONFIG_NAME)
    config = config_module.load(tmp_path)
    assert config.control_plane
    assert config.allow_environments
    assert config.targets


def test_it_documents_every_key_the_loader_reads():
    documented = set(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))
    missing = sorted(keys_the_loader_reads() - documented)
    assert missing == [], f"undocumented configuration key(s): {', '.join(missing)}"


def test_it_invents_no_key_the_loader_ignores():
    """A documented key nothing reads is worse than an undocumented one: it
    looks like it works."""
    documented = set(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))
    invented = sorted(documented - keys_the_loader_reads())
    assert invented == [], f"documented but never read: {', '.join(invented)}"


def test_the_key_scan_actually_finds_keys():
    """A scan that returns nothing would make both checks above vacuous."""
    found = keys_the_loader_reads()
    assert len(found) > 10
    assert "environments" in found and "targets" in found


def test_the_example_declares_what_it_refuses():
    """The two refusals are the ones somebody will otherwise try.

    Asserted on the substance rather than on a phrase: pinning a test to exact
    wording makes the prose unrewritable without a false failure.
    """
    text = EXAMPLE.read_text(encoding="utf-8").lower()
    assert "ansible_config is refused" in text
    assert "nothing runs until" in text
