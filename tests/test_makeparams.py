"""A Makefile already says what its recipes need, so the console reads it.

Every case here is the shape a real control plane writes: an example line above
the recipe, a `test -n` guard inside it, a guard in the script the recipe calls,
and a help line that says `requires x=` without giving a value.
"""

from __future__ import annotations

from pathlib import Path

from ordane.core import makeparams


def a_repo(tmp_path: Path, makefile: str, **scripts: str) -> Path:
    (tmp_path / "Makefile").write_text(makefile)
    for name, body in scripts.items():
        path = tmp_path / "bin" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return tmp_path


def test_an_example_line_names_the_parameters(tmp_path):
    repo = a_repo(
        tmp_path,
        """
## magento: run a Magento CLI command
# make magento environment=production cmd="indexer:reindex"
magento:
\t@ansible admin -a "${cmd}"
""",
    )
    found = makeparams.read(repo)
    assert list(found["magento"]) == ["cmd"]
    assert found["magento"]["cmd"].example == "indexer:reindex"


def test_the_environment_is_never_offered_as_a_parameter(tmp_path):
    """It has its own chooser, and the console assigns it."""
    repo = a_repo(
        tmp_path,
        """
# make deploy environment=production branch_name=main
deploy:
\t@./bin/deploy
""",
    )
    assert list(makeparams.read(repo)["deploy"]) == ["branch_name"]


def test_a_recipe_that_refuses_an_empty_value_makes_it_required(tmp_path):
    repo = a_repo(
        tmp_path,
        """
# make clear-url environment=production url="^/womens.html"
clear-url:
\t@test -n "${url}" || { echo 'ERROR: url= is required'; exit 1; }
\t@ansible varnish -a 'ban ${url}'
""",
    )
    assert makeparams.read(repo)["clear-url"]["url"].required


def test_a_parameter_with_no_guard_stays_optional(tmp_path):
    repo = a_repo(
        tmp_path,
        """
# make create environment=staging branch_name=main
create:
\t@./bin/create
""",
    )
    assert not makeparams.read(repo)["create"]["branch_name"].required


def test_a_guard_inside_the_script_the_recipe_calls_counts(tmp_path):
    """The recipe is one line; the refusal is in the script beside it."""
    repo = a_repo(
        tmp_path,
        """
# make apply-patch environment=production patch=M2PL-6611 state=present
apply-patch:
\t@${ROOT_DIR}/bin/apply-patch
""",
        **{
            "apply-patch": """#!/bin/bash
if [ -z "${patch:-}" ]; then echo "ERROR: patch= is required" >&2; exit 1; fi
if [ "${state:-}" != "present" ] && [ "${state:-}" != "absent" ]; then exit 1; fi
"""
        },
    )
    found = makeparams.read(repo)["apply-patch"]
    assert found["patch"].required
    assert found["state"].required


def test_a_help_line_saying_requires_names_it_without_a_value(tmp_path):
    repo = a_repo(
        tmp_path,
        """
## complete-deployment: cut over to a built release (requires release_name=)
# make complete-deployment environment=production release_name="20260819_1755600000"
complete-deployment:
\t@./bin/maintenance
""",
    )
    found = makeparams.read(repo)["complete-deployment"]
    assert found["release_name"].required
    assert found["release_name"].example == "20260819_1755600000"


def test_a_help_line_alone_never_supplies_a_bracket_as_the_example(tmp_path):
    """`(requires release_name=)` names the field; the `)` is not a value."""
    repo = a_repo(
        tmp_path,
        """
## complete-deployment: cut over to a built release (requires release_name=)
complete-deployment:
\t@./bin/maintenance
""",
    )
    assert makeparams.read(repo)["complete-deployment"]["release_name"].example == ""


def test_a_profile_variable_is_not_offered_as_a_field(tmp_path):
    """A recipe reads plenty the deployment supplies; only what is documented counts."""
    repo = a_repo(
        tmp_path,
        """
## ping: check that every host answers
ping:
\t@ansible all -i ${inventory} -m ping
\t@echo ${owner} ${group} ${release_folder}
""",
    )
    assert "ping" not in makeparams.read(repo)


def test_fragments_one_folder_down_are_read(tmp_path):
    """`include $(ROOT_DIR)/Makefiles/*.mk` is where a real one keeps them."""
    (tmp_path / "Makefile").write_text("include Makefiles/*.mk\n")
    (tmp_path / "Makefiles").mkdir()
    (tmp_path / "Makefiles" / "tools.mk").write_text(
        '# make magento environment=production cmd="cache:flush"\n'
        "magento:\n"
        '\t@test -n "${cmd}" || exit 1\n'
    )
    assert makeparams.read(tmp_path)["magento"]["cmd"].required


def test_a_makefile_that_documents_nothing_returns_nothing(tmp_path):
    repo = a_repo(tmp_path, "## check: syntax-check\ncheck:\n\t@./bin/check\n")
    assert makeparams.read(repo) == {}


def test_a_declared_parameter_wins_over_the_documented_one(tmp_path):
    """Declaring `choices_from` is how a free-text field becomes a list."""
    from ordane.core import catalog, config

    a_repo(
        tmp_path,
        """
Targets:
  apply-patch: apply or revert a patch
# make apply-patch environment=docker patch=M2PL-6611 state=present
apply-patch:
\t@test -n "${patch}" || exit 1
""",
    )
    (tmp_path / ".ordane.yml").write_text(
        "environments:\n"
        "  allow: [docker]\n"
        "  names: [docker]\n"
        "targets:\n"
        "  apply-patch:\n"
        "    params:\n"
        "      state:\n"
        "        required: true\n"
        "        choices: [present, absent]\n"
    )
    found = catalog._params_for("apply-patch", config.load(tmp_path), makeparams.read(tmp_path))
    assert found["patch"].required, "the documented one survived"
    assert found["state"].choices == ["present", "absent"], "the declared one won"
