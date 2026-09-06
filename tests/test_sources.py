"""The two records the console reads and never writes."""

import json

from ordane.insight import sources

RELEASES = [
    {
        "release": "Awolnation",
        "release_key": "Awolnation@2020-01-29",
        "env_name": "production",
        "ts": "2020-01-29T00:00:00Z",
        "outcome": "success",
        "version": "—",
        "platform": "2.3.2",
        "platform_upgrade": True,
        "previous_release": "",
        "commit_count": 2755,
        "lead_time_days": None,
    },
    {
        "release": "Beatles",
        "release_key": "Beatles@2020-03-30",
        "env_name": "production",
        "ts": "2020-03-30T00:00:00Z",
        "outcome": "success",
        "platform": "2.3.2-p2",
        "previous_release": "Awolnation",
        "commit_count": 296,
        "lead_time_days": 31.37,
    },
]

PATCHES = [
    {
        "patch": "M2PL-6611",
        "ts": "2026-08-20T00:00:00Z",
        "state": "present",
        "env_name": "production",
        "actor": "backfill",
        "assumed": True,
    },
    {
        "patch": "APSB24-61",
        "ts": "2026-08-21T09:00:00Z",
        "state": "absent",
        "env_name": "production",
        "actor": "ada",
        "hosts_ok": 6,
        "hosts_total": 6,
    },
]


def write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_a_release_is_read_with_its_chain(tmp_path):
    found = sources.read_releases(write(tmp_path / "r.jsonl", RELEASES))
    assert [r.name for r in found] == ["Awolnation", "Beatles"]
    assert found[1].previous == "Awolnation"
    assert found[1].lead_time_days == 31.37


def test_the_reporters_em_dash_is_not_a_version():
    assert sources._clean("—") == ""
    assert sources._clean("2.4.8-p5") == "2.4.8-p5"


def test_two_releases_of_the_same_name_stay_two(tmp_path):
    """This estate has shipped two called Eagle."""
    same = [
        {"release": "Eagle", "release_key": "Eagle@2022-01-01", "ts": "2022-01-01T00:00:00Z"},
        {"release": "Eagle", "release_key": "Eagle@2024-05-05", "ts": "2024-05-05T00:00:00Z"},
    ]
    found = sources.read_releases(write(tmp_path / "r.jsonl", same))
    assert len({r.identity for r in found}) == 2


def test_a_release_with_no_key_gets_one_from_its_date(tmp_path):
    found = sources.read_releases(
        write(tmp_path / "r.jsonl", [{"release": "Nameless", "ts": "2025-02-03T00:00:00Z"}])
    )
    assert found[0].identity == "Nameless@2025-02-03"


def test_a_patch_event_says_whether_anybody_watched_it(tmp_path):
    found = sources.read_patches(write(tmp_path / "p.jsonl", PATCHES))
    assert found[0].assumed and found[0].applied
    assert not found[1].assumed and not found[1].applied
    assert found[1].hosts_total == 6


def test_a_malformed_line_costs_that_line_and_not_the_file(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text('{"patch": "one"}\nnot json\n{"patch": "two"}\n', encoding="utf-8")
    assert [p.patch for p in sources.read_patches(path)] == ["one", "two"]


def test_a_missing_file_is_no_records_rather_than_an_error(tmp_path):
    assert sources.read_releases(tmp_path / "nothing.jsonl") == []
    assert sources.read_patches(tmp_path / "nothing.jsonl") == []


def test_the_csv_is_the_fallback_and_says_so(tmp_path):
    repo = tmp_path / "plane"
    (repo / "docs" / "dora").mkdir(parents=True)
    (repo / "docs" / "dora" / "history.csv").write_text(
        "date,env_name,release,outcome,lead_time_days\n"
        "2020-01-29,production,Awolnation,success,\n"
        "2020-03-30,production,Beatles,success,31.37\n",
        encoding="utf-8",
    )
    found = sources.read(repo)
    assert [r.name for r in found.releases] == ["Awolnation", "Beatles"]
    assert any("carries less" in note for note in found.notes)


def test_the_csv_chain_is_rebuilt_from_the_order_things_happened(tmp_path):
    repo = tmp_path / "plane"
    (repo / "docs" / "dora").mkdir(parents=True)
    (repo / "docs" / "dora" / "history.csv").write_text(
        "date,env_name,release\n2020-03-30,production,Beatles\n2020-01-29,production,Awolnation\n",
        encoding="utf-8",
    )
    found = sources.read_release_csv(repo / "docs" / "dora" / "history.csv")
    assert [r.name for r in found] == ["Awolnation", "Beatles"]
    assert found[1].previous == "Awolnation@2020-01-29"


def test_a_control_plane_with_neither_says_which_it_looked_for(tmp_path):
    found = sources.read(tmp_path)
    assert found.empty
    assert len(found.notes) == 2
