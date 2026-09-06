"""The console against control planes it has never seen.

The dialect this was written for is one of three, and none of the three is
required: a repository with no `help` target at all still has the `##`
comments the convention is built on.
"""

from pathlib import Path

from ordane.core import catalog as catalog_module
from ordane.core import config as config_module
from ordane.core import starter

BLOCK_HELP = """help:
\t@echo "Environments (a directory under inventory/):"
\t@echo "  docker"
\t@echo ""
\t@echo "Targets:"
\t@echo "  deploy: build and deploy"
"""

COLUMN_HELP = """.DEFAULT_GOAL := help
help: ## Show this help
\t@echo "  lint            Run ansible-lint"
\t@echo "  deploy          Deploy the application"

lint: ## Run ansible-lint
\t@true

deploy: ## Deploy the application
\t@ansible-playbook -i inventories/$(env) deploy.yml
"""

COMMENTS_ONLY = """build: ## Build the artefact
\t@true

release: ## Publish it
\t@true
"""


def a_repo(tmp_path: Path, makefile: str, name: str = "plane", config: str = "") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / "Makefile").write_text(makefile, encoding="utf-8")
    if config:
        (repo / ".ordane.yml").write_text(config, encoding="utf-8")
    return repo


def build(repo: Path):
    return catalog_module.build(repo, config_module.load(repo))


def test_the_block_dialect_is_still_read_first(tmp_path):
    catalog = build(a_repo(tmp_path, BLOCK_HELP))
    assert [t.name for t in catalog.targets] == ["deploy"]
    assert catalog.discovery.targets == "make-help-block"
    assert catalog.discovery.environments == "make-help"


def test_a_two_column_help_target_is_read_when_there_is_no_block(tmp_path):
    repo = a_repo(tmp_path, COLUMN_HELP)
    (repo / "inventories" / "prod").mkdir(parents=True)
    (repo / "inventories" / "staging").mkdir(parents=True)
    catalog = build(repo)
    assert {t.name for t in catalog.targets} == {"lint", "deploy"}
    assert catalog.discovery.targets == "make-help-columns"
    assert [e.name for e in catalog.environments] == ["prod", "staging"]
    assert catalog.discovery.environments == "directories"


def test_a_repository_with_no_help_target_falls_back_to_its_own_comments(tmp_path):
    catalog = build(a_repo(tmp_path, COMMENTS_ONLY))
    assert {t.name for t in catalog.targets} == {"build", "release"}
    assert catalog.discovery.targets == "makefile-comments"


def test_a_control_plane_with_no_environments_gets_one_stand_in(tmp_path):
    catalog = build(a_repo(tmp_path, COMMENTS_ONLY))
    assert [e.name for e in catalog.environments] == [catalog_module.SYNTHETIC_ENVIRONMENT]
    assert catalog.environments[0].synthetic
    assert catalog.discovery.environments == "none"


def test_the_stand_in_still_has_to_be_allowed_before_anything_runs(tmp_path):
    catalog = build(a_repo(tmp_path, COMMENTS_ONLY))
    assert not catalog.launchable_environments
    allowed = build(a_repo(tmp_path, COMMENTS_ONLY, "two", "environments:\n  allow: [default]\n"))
    assert [e.name for e in allowed.launchable_environments] == ["default"]


def test_a_run_against_the_stand_in_assigns_no_variable(tmp_path):
    from ordane.core.command import for_target

    catalog = build(a_repo(tmp_path, COMMENTS_ONLY, "one", "environments:\n  allow: [default]\n"))
    built = for_target(
        target=catalog.target("build"),
        environment="default",
        params={},
        config=config_module.Config(),
    )
    assert built.argv == ["make", "build"]


def test_colour_in_the_help_output_does_not_stop_it_being_read(tmp_path):
    coloured = COLUMN_HELP.replace(
        '"  lint            Run ansible-lint"',
        '"  \\033[36mlint\\033[0m            Run ansible-lint"',
    )
    catalog = build(a_repo(tmp_path, coloured))
    assert "lint" in {t.name for t in catalog.targets}


def test_a_repository_with_nothing_readable_says_so(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    try:
        build(repo)
    except catalog_module.CatalogError as exc:
        assert "no targets" in str(exc) or "make help" in str(exc)
    else:
        raise AssertionError("a repository with no targets was read as though it had some")


# --- the starter file ---


def test_the_starter_detects_the_variable_the_makefile_actually_reads(tmp_path):
    assert starter.environment_variable(a_repo(tmp_path, COLUMN_HELP)) == "env"


def test_the_starter_falls_back_to_the_default_name(tmp_path):
    assert starter.environment_variable(a_repo(tmp_path, COMMENTS_ONLY)) == "environment"


def test_the_starter_names_what_it_found_and_allows_nothing(tmp_path):
    repo = a_repo(tmp_path, COLUMN_HELP)
    (repo / "inventories" / "prod").mkdir(parents=True)
    text = starter.render(repo, build(repo))
    assert "allow: []" in text
    assert "#   - prod" in text
    assert "environment_var: env" in text
    assert config_module.load(_written(repo, text)).allow_environments == []


def _written(repo: Path, text: str) -> Path:
    (repo / ".ordane.yml").write_text(text, encoding="utf-8")
    return repo


def test_the_starter_refuses_to_replace_a_file_it_did_not_write(tmp_path):
    repo = a_repo(tmp_path, COMMENTS_ONLY, config="environments:\n  allow: [default]\n")
    try:
        starter.write(repo, build(repo))
    except starter.StarterExists:
        pass
    else:
        raise AssertionError("an existing configuration was overwritten")
    assert "allow: [default]" in (repo / ".ordane.yml").read_text()
