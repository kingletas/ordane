"""The read-only store clients, and every way they can fail.

Nothing here talks to a real store: what is being tested is that a failure
becomes a sentence rather than an exception in a view.
"""

from ordane.insight import estate, stores

CSV = """#datatype,string,long,dateTime:RFC3339,double
#group,false,false,false,false
#default,_result,,,
,result,table,_time,_value
,,0,2021-01-01T00:00:00Z,10
,,0,2022-01-01T00:00:00Z,12
"""


def test_nothing_configured_is_not_an_error_it_is_a_sentence():
    empty = stores.Stores()
    assert not empty.any
    assert "no InfluxDB configured" in empty.flux("x").error
    assert "no Neo4j configured" in empty.cypher("x").error


def test_a_store_is_configured_only_when_both_halves_are():
    assert not stores.Stores(influx_url="http://x").has_influx
    assert not stores.Stores(influx_token="t").has_influx
    assert stores.Stores(influx_url="http://x", influx_token="t").has_influx


def test_the_environment_supplies_it_and_absence_leaves_it_unconfigured():
    configured = stores.configured(
        {
            "ORDANE_INFLUX_URL": "http://box:8086",
            "ORDANE_INFLUX_TOKEN": "t",
            "ORDANE_NEO4J_PASSWORD": "p",
        }
    )
    assert configured.has_influx
    assert not configured.has_neo4j, "a url is still missing"
    assert configured.influx_org == "estate", "the default stands when nothing says otherwise"


def test_influxs_annotated_csv_becomes_rows_without_its_bookkeeping():
    rows = stores._annotated_csv(CSV)
    assert rows == [
        {"_time": "2021-01-01T00:00:00Z", "_value": "10"},
        {"_time": "2022-01-01T00:00:00Z", "_value": "12"},
    ]


def test_a_csv_with_only_annotations_is_no_rows_rather_than_a_crash():
    assert stores._annotated_csv("#datatype,string\n#group,false\n") == []


def test_neo4js_json_becomes_rows():
    answer = {
        "results": [{"columns": ["kind", "n"], "data": [{"row": ["Patch", 202]}]}],
        "errors": [],
    }
    assert stores._neo4j_rows(answer) == [{"kind": "Patch", "n": 202}]


def test_a_query_neo4j_refuses_comes_back_as_its_own_message(monkeypatch):
    monkeypatch.setattr(
        stores,
        "_post",
        lambda *_a, **_k: ('{"results": [], "errors": [{"message": "Invalid input"}]}', ""),
    )
    answer = stores.Stores(neo4j_url="http://x", neo4j_password="p").cypher("nonsense")
    assert not answer.ok
    assert "Invalid input" in answer.error


def test_a_store_that_cannot_be_reached_says_that_rather_than_raising(monkeypatch):
    monkeypatch.setattr(stores, "_post", lambda *_a, **_k: ("", "cannot reach it: refused"))
    answer = stores.Stores(influx_url="http://x", influx_token="t").flux("x")
    assert not answer.ok
    assert "cannot reach" in answer.error


def test_an_answer_can_be_read_a_column_at_a_time():
    answer = stores.Answer(rows=[{"n": 1}, {"n": 2}])
    assert answer.column("n") == [1, 2]


# --- the panels ---


def test_every_panel_names_a_store_and_says_why_it_is_here():
    for panel in estate.panels():
        assert panel.store in (estate.FROM_INFLUX, estate.FROM_NEO4J)
        assert panel.why.endswith(".")
        assert panel.columns


def test_the_bucket_reaches_the_flux_that_reads_it():
    influx = [p for p in estate.panels("elsewhere") if p.store == estate.FROM_INFLUX]
    assert influx
    assert all('bucket: "elsewhere"' in p.query for p in influx)


def test_a_bucket_name_cannot_close_the_string_it_is_written_into():
    assert '"' not in estate.bucket('runs" |> drop()')


def test_a_panel_that_cannot_be_answered_carries_the_reason_not_an_exception():
    result = estate.ask(stores.Stores(), estate.panels()[0])
    assert not result.ok
    assert "no InfluxDB configured" in result.error


def test_a_store_that_answers_with_nothing_is_empty_rather_than_broken(monkeypatch):
    monkeypatch.setattr(stores, "_post", lambda *_a, **_k: ("", ""))
    result = estate.ask(stores.Stores(influx_url="http://x", influx_token="t"), estate.panels()[0])
    assert result.ok and result.empty


# --- the settings file, which is what made the view findable ---


def test_a_file_the_operator_wrote_configures_it(tmp_path):
    path = tmp_path / "stores.env"
    path.write_text(
        "ORDANE_INFLUX_URL=http://box:8086\n"
        "ORDANE_INFLUX_TOKEN=t\n"
        "ORDANE_NEO4J_URL=http://box:7474\n"
        "ORDANE_NEO4J_PASSWORD=p\n",
        encoding="utf-8",
    )
    configured = stores.configured({}, path)
    assert configured.has_influx and configured.has_neo4j


def test_the_environment_wins_over_the_file(tmp_path):
    path = tmp_path / "stores.env"
    path.write_text("ORDANE_INFLUX_URL=http://from-file\n", encoding="utf-8")
    configured = stores.configured({"ORDANE_INFLUX_URL": "http://from-env"}, path)
    assert configured.influx_url == "http://from-env"


def test_comments_blank_lines_and_quotes_are_handled(tmp_path):
    path = tmp_path / "stores.env"
    path.write_text(
        '# a comment\n\nORDANE_INFLUX_URL="http://quoted:8086"\nnonsense\n',
        encoding="utf-8",
    )
    assert stores.read_settings_file(path)["ORDANE_INFLUX_URL"] == "http://quoted:8086"


def test_nothing_in_the_file_is_evaluated(tmp_path):
    """A file of values, not a script. Treating it as one would be a way to run
    something by editing a configuration file."""
    path = tmp_path / "stores.env"
    path.write_text("ORDANE_INFLUX_TOKEN=$(id -u)\n", encoding="utf-8")
    read = stores.read_settings_file(path)["ORDANE_INFLUX_TOKEN"]
    assert read.startswith("$(") and read.endswith(")")


def test_a_missing_file_is_no_settings_rather_than_an_error(tmp_path):
    assert stores.read_settings_file(tmp_path / "nothing") == {}


def test_the_template_names_every_setting_that_is_read():
    for name in (
        "INFLUX_URL",
        "INFLUX_TOKEN",
        "INFLUX_ORG",
        "INFLUX_BUCKET",
        "NEO4J_URL",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
    ):
        assert f"{stores.PREFIX}{name}" in stores.TEMPLATE


def test_the_template_carries_no_value_for_a_credential():
    for line in stores.TEMPLATE.splitlines():
        if line.startswith(f"{stores.PREFIX}") and ("TOKEN" in line or "PASSWORD" in line):
            assert line.endswith("="), "the template must not ship a credential"


def test_the_settings_file_goes_where_xdg_says(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert stores.settings_path() == tmp_path / "ordane" / "stores.env"
