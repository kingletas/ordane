import pytest
from fastapi.testclient import TestClient

from ordane.web.app import Settings, create_app

MAKEFILE = """\
.DEFAULT_GOAL := help
help:
\t@echo "Usage: make <target> environment=<env>"
\t@echo ""
\t@echo "Environments:"
\t@echo "  docker"
\t@echo "  production"
\t@echo ""
\t@echo "Targets:"
\t@echo "  ping: check that every host answers"
\t@echo "  boom: fail on purpose"
\t@echo ""

ping:
\t@echo "pong from $(environment)"

boom:
\t@exit 3
"""

CONFIG = """\
environments:
  allow: [docker]
groups:
  Fleet: [ping]
"""

ORIGIN = {"Host": "127.0.0.1:8710", "Origin": "http://127.0.0.1:8710"}


@pytest.fixture
def client(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(MAKEFILE)
    (repo / ".ordane.yml").write_text(CONFIG)
    settings = Settings(
        repo=repo,
        port=8710,
        state_dir=tmp_path / "state",
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
    )
    return TestClient(create_app(settings), headers={"Host": "127.0.0.1:8710"})


@pytest.mark.parametrize("path", ["/", "/actions", "/playbooks", "/runs", "/environments"])
def test_every_page_renders(client, path):
    assert client.get(path).status_code == 200


def test_the_catalog_reaches_the_actions_page(client):
    body = client.get("/actions").text
    assert "ping" in body
    assert "check that every host answers" in body


def test_a_cross_origin_post_is_refused(client):
    response = client.post(
        "/launch/ping",
        data={"environment": "docker"},
        headers={"Host": "127.0.0.1:8710", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_a_post_to_a_non_loopback_host_is_refused(client):
    response = client.post(
        "/launch/ping",
        data={"environment": "docker"},
        headers={"Host": "attacker.test:8710", "Origin": "http://127.0.0.1:8710"},
    )
    assert response.status_code == 403


def test_an_environment_outside_the_allow_list_is_refused_in_the_form(client):
    response = client.post("/launch/ping", data={"environment": "production"}, headers=ORIGIN)
    assert response.status_code == 200
    assert "not in the allow list" in response.text


def test_a_successful_run_is_recorded_with_its_exit_code(client):
    response = client.post(
        "/launch/ping", data={"environment": "docker"}, headers=ORIGIN, follow_redirects=False
    )
    assert response.status_code == 303
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    _settle(client, run_id)
    detail = client.get(f"/runs/{run_id}").text
    assert "succeeded" in detail
    assert "pong from docker" in detail


def test_a_failing_run_is_recorded_as_failed(client):
    response = client.post(
        "/launch/boom", data={"environment": "docker"}, headers=ORIGIN, follow_redirects=False
    )
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    _settle(client, run_id)
    assert "failed" in client.get(f"/runs/{run_id}").text


def test_an_unknown_target_is_reported_rather_than_crashing(client):
    assert "unknown target" in client.get("/launch/nope").text


def _settle(client, run_id, tries=100):
    import time

    for _ in range(tries):
        if "running" not in client.get(f"/runs/{run_id}").text:
            return
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} never finished")
