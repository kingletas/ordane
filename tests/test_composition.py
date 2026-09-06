"""What a playbook pulls in, and how much of it is decided at run time.

Ansible already composes; nothing here builds a second system. The distinction
that matters is static against dynamic: an `import_` is resolved before the
run starts, an `include_` while it goes: because a preview can be sure of the
first and is guessing about the second.
"""

from ordane.core import composition

# The shapes the real control plane uses, including the fully-qualified names
# and the `{ role: x }` mapping form.
REAL = """
- name: Start the build process
  hosts: all
  roles:
    - { role: ansible-role-packaging }
  tasks:
    - name: Preflight
      ansible.builtin.include_tasks: tasks/release-preflight.yml
    - name: "DORA: record the cutover start"
      ansible.builtin.include_tasks: tasks/dora-event.yml
      vars:
        dora_phase: cutover.started
    - name: "DORA: record maintenance mode on"
      ansible.builtin.include_tasks: tasks/dora-event.yml

- name: Deploy
  hosts: web
  roles:
    - ansible-role-deploy
    - { role: ansible-role-magento-deploy }
  tasks:
    - ansible.builtin.import_tasks: tasks/common.yml

- ansible.builtin.import_playbook: verify-deploy.yml
"""


def test_it_reads_what_the_playbook_names():
    read = composition.parse(REAL)
    assert read.known
    named = {one.name: one for one in read.pieces}
    assert set(named) == {
        "ansible-role-packaging",
        "tasks/release-preflight.yml",
        "tasks/dora-event.yml",
        "ansible-role-deploy",
        "ansible-role-magento-deploy",
        "tasks/common.yml",
        "verify-deploy.yml",
    }
    assert named["tasks/dora-event.yml"].times == 2


def test_an_import_is_static_and_an_include_is_not():
    named = {one.name: one for one in composition.parse(REAL).pieces}
    assert named["tasks/common.yml"].static
    assert named["verify-deploy.yml"].static
    assert named["ansible-role-deploy"].static
    assert not named["tasks/dora-event.yml"].static


def test_both_role_forms_are_read():
    """`- name` and `- { role: name }` are the same thing written two ways."""
    named = {one.name for one in composition.parse(REAL).pieces if one.kind == "role"}
    assert named == {"ansible-role-packaging", "ansible-role-deploy", "ansible-role-magento-deploy"}


def test_the_caveat_names_what_a_preview_cannot_promise():
    caveat = composition.parse(REAL).caveat
    assert "chosen while the run goes" in caveat
    assert "tasks/dora-event.yml" in caveat


def test_a_playbook_that_decides_nothing_at_run_time_has_no_caveat():
    only_static = "- hosts: all\n  tasks:\n    - ansible.builtin.import_tasks: tasks/a.yml\n"
    read = composition.parse(only_static)
    assert read.known
    assert read.caveat == ""
    assert read.dynamic == ()


def test_a_name_that_is_a_variable_is_marked_rather_than_resolved():
    """Resolving it would be inventing the answer."""
    read = composition.parse('- hosts: all\n  tasks:\n    - include_tasks: "{{ item }}.yml"\n')
    assert read.pieces[0].unresolved
    assert read.unresolved


def test_include_vars_is_not_a_step():
    """Variables are not something a playbook does, and listing them says it is."""
    text = "- hosts: all\n  tasks:\n    - ansible.builtin.include_vars: all.yml\n"
    read = composition.parse(text)
    assert read.pieces == ()


def test_a_role_written_under_include_role_is_found():
    text = (
        "- hosts: all\n  tasks:\n    - name: Do it\n"
        "      ansible.builtin.include_role:\n        name: ansible-role-warm\n"
    )
    assert [one.name for one in composition.parse(text).pieces] == ["ansible-role-warm"]


def test_a_commented_out_include_is_not_a_piece():
    assert composition.parse("#    - import_tasks: tasks/old.yml\n").pieces == ()


def test_nothing_readable_says_so_rather_than_claiming_an_empty_playbook(tmp_path):
    assert "does not name a playbook" in composition.read(tmp_path, "").error
    assert "could not be read" in composition.read(tmp_path, "missing.yml").error


def test_a_playbook_outside_the_control_plane_is_refused(tmp_path):
    assert "outside" in composition.read(tmp_path, "../../etc/passwd").error
