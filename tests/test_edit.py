import pytest
import yaml

from ordane.core import edit
from ordane.core.config import ConfigError

INLINE = """# Why the list is empty.
environments:
  allow: []

groups:
  Release: [deploy]
"""

BLOCK = """environments:
  # One name per line, on purpose.
  allow:
    - docker
    - staging

groups:
  Release: [deploy]
"""


def allowed(text):
    return (yaml.safe_load(text).get("environments") or {}).get("allow") or []


def test_an_inline_list_is_replaced_and_the_comment_survives():
    updated = edit.apply(INLINE, ["docker"])
    assert allowed(updated) == ["docker"]
    assert "# Why the list is empty." in updated
    assert "Release: [deploy]" in updated


def test_a_block_list_is_replaced_including_its_items():
    updated = edit.apply(BLOCK, ["production"])
    assert allowed(updated) == ["production"]
    assert "- staging" not in updated
    assert "groups:" in updated


def test_environments_with_no_allow_key_gains_one():
    updated = edit.apply("environments:\n  note: nothing\n", ["docker"])
    assert allowed(updated) == ["docker"]
    assert "note: nothing" in updated


def test_a_file_with_no_environments_block_gains_one():
    updated = edit.apply("groups:\n  Release: [deploy]\n", ["docker"])
    assert allowed(updated) == ["docker"]
    assert "Release: [deploy]" in updated


def test_emptying_the_list_is_how_read_only_is_restored():
    assert allowed(edit.apply(BLOCK, [])) == []


def test_the_indentation_of_the_line_it_replaces_is_kept():
    updated = edit.apply("environments:\n    allow: []\n", ["docker"])
    assert "    allow: [docker]" in updated


def test_writing_it_leaves_a_file_that_still_parses(tmp_path):
    (tmp_path / ".ordane.yml").write_text(INLINE, encoding="utf-8")
    edit.write(tmp_path, ["docker", "staging"])
    assert allowed((tmp_path / ".ordane.yml").read_text()) == ["docker", "staging"]


def test_a_write_that_would_not_take_is_refused_rather_than_applied(tmp_path, monkeypatch):
    path = tmp_path / ".ordane.yml"
    path.write_text(INLINE, encoding="utf-8")
    monkeypatch.setattr(edit, "apply", lambda text, names, key="allow": text)
    with pytest.raises(ConfigError):
        edit.write(tmp_path, ["docker"])
    assert allowed(path.read_text()) == []


# --- environments the file declares outright ---


def test_a_declared_name_list_is_written_beside_the_allow_list():
    updated = edit.apply(INLINE, ["prod", "dr"], key="names")
    parsed = yaml.safe_load(updated)["environments"]
    assert parsed["names"] == ["prod", "dr"]
    assert parsed["allow"] == []
    assert "# Why the list is empty." in updated


# --- objectives ---

WITH_SLOS = """environments:
  allow: [docker]

# Why these are here.
slos:
  - label: Old one
    target: "99%"
    window: 28d

groups:
  Release: [deploy]
"""


def an_objective(label="Cutover succeeds", kind="cutover_success"):
    return {
        "label": label,
        "kind": kind,
        "environments": ["production"],
        "target": "95%",
        "window": "90d",
    }


def test_objectives_replace_the_block_and_leave_the_rest():
    updated = edit.set_slos(WITH_SLOS, [an_objective()])
    parsed = yaml.safe_load(updated)
    assert [s["label"] for s in parsed["slos"]] == ["Cutover succeeds"]
    assert parsed["groups"] == {"Release": ["deploy"]}
    assert parsed["environments"]["allow"] == ["docker"]
    assert "# Why these are here." in updated


def test_a_file_with_no_objectives_gains_a_block():
    updated = edit.set_slos("environments:\n  allow: [docker]\n", [an_objective()])
    assert yaml.safe_load(updated)["slos"][0]["window"] == "90d"


def test_removing_every_objective_leaves_an_empty_list_rather_than_a_stray_key():
    parsed = yaml.safe_load(edit.set_slos(WITH_SLOS, []))
    assert parsed["slos"] == []
    assert parsed["groups"] == {"Release": ["deploy"]}


def test_an_objective_with_no_kind_is_written_with_its_reason():
    entry = {
        "label": "Availability",
        "target": "99.9%",
        "window": "28d",
        "blocked": "needs a probe",
    }
    parsed = yaml.safe_load(edit.set_slos(WITH_SLOS, [entry]))
    assert parsed["slos"][0]["blocked"] == "needs a probe"


def test_a_label_with_a_colon_in_it_survives_the_round_trip():
    entry = {"label": "p95: under 2s", "target": "95%", "window": "28d"}
    parsed = yaml.safe_load(edit.set_slos(WITH_SLOS, [entry]))
    assert parsed["slos"][0]["label"] == "p95: under 2s"


def test_writing_objectives_that_would_not_read_back_is_refused(tmp_path, monkeypatch):
    path = tmp_path / ".ordane.yml"
    path.write_text(WITH_SLOS, encoding="utf-8")
    monkeypatch.setattr(edit, "set_slos", lambda text, entries: text)
    with pytest.raises(ConfigError):
        edit.write_slos(tmp_path, [an_objective(), an_objective("Second")])
    assert "Old one" in path.read_text()
