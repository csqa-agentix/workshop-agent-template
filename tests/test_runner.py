"""The shared runner: workspace copy, diff, result.json, outputs, tool-count rules."""
import asyncio
import json

from app.llm_client import ScriptedLLM
from app.runner import extract_json, run_once
from app.workspace import diff_workspaces, prepare_workspace


def test_run_leaves_originals_untouched_and_publishes_outputs(workspace):
    before = (workspace / "inventory.csv").read_text()
    outcome = asyncio.run(run_once("brief me", offline=True, quiet=True))
    assert outcome.status == "completed"
    assert (workspace / "inventory.csv").read_text() == before
    assert not (workspace / "output" / "briefing.md").exists()                     # the original workspace stays clean
    assert (outcome.run_dir / "output" / "briefing.md").exists()                    # deliverables land in runs/<id>/output/
    result = json.loads(outcome.result_path.read_text())
    assert result["status"] == "completed" and result["guardrail_blocks"] == 1
    assert result["outputs"] == ["output/briefing.md"] and result["tools_used"]["read_file"] == 3
    assert "Why it stopped" in outcome.report_path.read_text()


def test_edits_are_shown_as_a_diff(workspace, make_agent):
    make_agent("read_file", "edit_file", guardrails='[files]\nwritable = ["inventory.csv"]\n')    # this agent may edit exactly one file
    llm = ScriptedLLM([{"calls": [{"tool": "edit_file", "args": {"path": "inventory.csv",
                                   "old_text": "Search page,Marco,in progress,2 March", "new_text": "Search page,Marco,done,2 March"}},
                                  {"tool": "edit_file", "args": {"path": "meeting_notes.md", "old_text": "Open", "new_text": "Closed"}}]},
                       {"say": "Edited."}])
    outcome = asyncio.run(run_once("fix it", quiet=True, llm=llm))
    assert "-Search page,Marco,in progress" in outcome.changes and "+Search page,Marco,done" in outcome.changes
    assert "meeting_notes.md" not in outcome.changes                                # the second edit was blocked
    assert "done" not in (workspace / "inventory.csv").read_text().split("Search page")[1].split("\n")[0]   # original untouched
    assert "changes.diff" in {p.name for p in outcome.run_dir.iterdir()}
    assert json.loads(outcome.result_path.read_text())["files_changed"] == ["inventory.csv"]


def test_structured_json_in_the_answer_is_captured():
    assert extract_json('Done.\n```json\n{"verdict": "escalate", "confidence": "low"}\n```') == {"verdict": "escalate", "confidence": "low"}
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("no json here") is None
    assert extract_json("```json\n[1,2]\n```") is None


def test_workspace_copy_skips_heavy_folders_and_diff_ignores_output(tmp_path):
    src = tmp_path / "src"
    (src / "node_modules" / "x").mkdir(parents=True)
    (src / "node_modules" / "x" / "big.js").write_text("x")
    (src / "a.txt").write_text("one\n")
    work = prepare_workspace(src, tmp_path / "work")
    assert not (work / "node_modules").exists() and (work / "a.txt").exists()
    (work / "a.txt").write_text("two\n")
    (work / "output" / "report.md").write_text("ignored")
    (work / "new.txt").write_text("new\n")
    diff = diff_workspaces(src, work)
    assert "-one" in diff and "+two" in diff and "new.txt" in diff and "report.md" not in diff


def test_too_many_tools_is_flagged(workspace, make_agent, capsys):
    make_agent("list_files", "read_file", "search_text", "write_file", "edit_file")
    asyncio.run(run_once("brief me", offline=True))
    assert "configured limit is 4" in capsys.readouterr().out


def test_unknown_tool_in_agent_toml_is_a_clear_error(workspace, make_agent):
    import pytest
    make_agent("list_files", "no_such_tool")
    with pytest.raises(SystemExit, match="no_such_tool"):
        asyncio.run(run_once("x", offline=True, quiet=True))
