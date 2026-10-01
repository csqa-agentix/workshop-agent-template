import pytest

from app.tools.builtin import commands, files
from app.tools.registry import discover


def test_every_builtin_tool_is_discovered():
    names = {fn.__name__ for fn in discover()}
    assert {"list_files", "read_file", "search_text", "write_file", "run_command", "load_skill"} <= names


def test_example_tool_is_off_until_renamed():
    assert "count_words" not in {fn.__name__ for fn in discover()}


def test_an_agent_folder_can_ship_its_own_tools(monkeypatch):
    from app.config import ROOT
    monkeypatch.setenv("AGENT_DIR", str(ROOT / "examples" / "example-triage-report"))
    assert "summarize_csv" in {fn.__name__ for fn in discover()}


def test_read_and_search(workspace):
    assert "Lighthouse" in files.read_file("project_overview.md", max_lines=3)
    assert "12 March" in files.search_text("march", ".")
    assert files.search_text("zzz-not-there") == "No matches."


def test_read_is_capped_and_paged(workspace):
    out = files.read_file("meeting_notes.md", max_lines=2)
    assert "more lines" in out and "start_line=3" in out


def test_write_file_creates_folders(workspace):
    files.write_file("output/a/b.txt", "hi")
    assert (workspace / "output/a/b.txt").read_text() == "hi"


def test_run_command_allow_list_is_by_prefix(workspace, make_agent):
    make_agent("run_command", guardrails='[commands]\nallowed = ["pytest", "git diff"]\n')
    for bad in ("rm -rf /", "curl http://example.com", "python -c 1", "git push", "pytestx", "git"):
        with pytest.raises(ValueError, match="not allowed"):
            commands.run_command(bad)
    assert "exit_code: 0" in commands.run_command("pytest --version")


def test_run_command_refuses_paths_outside_workspace(workspace, make_agent):
    make_agent("run_command", guardrails='[commands]\nallowed = ["pytest"]\n')
    for bad in ("pytest /etc", "pytest ~/x", "pytest ../other", "pytest --rootdir=../x"):
        with pytest.raises(ValueError, match="outside the workspace"):
            commands.run_command(bad)


def test_run_command_is_off_by_default():
    from app.config import load_profile, load_rules
    assert "run_command" not in load_profile()["tools"]["enabled"]
    assert len(load_profile()["tools"]["enabled"]) <= 4          # keep the toolset small
    assert load_rules().allowed_commands == ()                   # …and no command is allowed until you list one


def test_run_command_with_nothing_allowed_explains_what_to_do(workspace):
    with pytest.raises(ValueError, match="guardrails.toml"):
        commands.run_command("pytest --version")


def test_edit_file_shows_a_diff_and_needs_a_unique_match(workspace):
    out = files.edit_file("inventory.csv", "Search page,Marco,in progress,2 March", "Search page,Marco,done,2 March")
    assert "-Search page" in out and "+Search page" in out and "done" in (workspace / "inventory.csv").read_text()
    with pytest.raises(ValueError, match="exactly once"):
        files.edit_file("inventory.csv", "not started", "x")          # appears twice
    with pytest.raises(ValueError, match="exactly once"):
        files.edit_file("inventory.csv", "zzz-missing", "x")
