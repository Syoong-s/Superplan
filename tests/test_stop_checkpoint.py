#!/usr/bin/env python3
"""Regression tests for Superplan checkpoint acceptance at Stop boundaries."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = Path(
    os.environ.get(
        "SUPERPLAN_CONTROLLER_UNDER_TEST",
        REPOSITORY_ROOT / "skills" / "superplan" / "scripts" / "superplan.py",
    )
).resolve()


# ==========================================
# Function: Load the controller under test from its plugin path
# Method: Use an importlib file specification without modifying sys.path
# ==========================================
def load_controller() -> ModuleType:
    specification = importlib.util.spec_from_file_location("superplan_controller", CONTROLLER_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Unable to load controller: {CONTROLLER_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


CONTROLLER = load_controller()


class StopCheckpointTests(unittest.TestCase):
    """Exercise Stop decisions with changed, manual, and stale checkpoints."""

    # ==========================================
    # Function: Create an isolated active Superplan workspace
    # Method: Initialize real templates inside a temporary directory
    # ==========================================
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.workspace = Path(self.temporary_directory.name)
        self.plan_dir = CONTROLLER.initialize_plan(self.workspace, "Stop checkpoint test")
        self.session_id = "session-test"
        self.transcript_path = self.workspace / "transcript.jsonl"
        self.transcript_path.write_text(
            '{"role":"assistant","content":"checkpoint recovery evidence"}\n',
            encoding="utf-8",
        )
        CONTROLLER.bind_plan_to_session(
            self.plan_dir,
            host="codex",
            session_id=self.session_id,
            reset_session_state=False,
        )

    # ==========================================
    # Function: Invoke one lifecycle hook and capture its protocol output
    # Method: Route a realistic payload through the controller's public hook dispatcher
    # ==========================================
    def run_hook(
        self,
        event: str,
        *,
        turn_id: str,
        stop_hook_active: bool = False,
        tool_command: str | None = None,
        tool_name: str = "Bash",
        tool_input: dict[str, object] | None = None,
        tool_response: object = None,
        source: str = "resume",
    ) -> str:
        payload: dict[str, object] = {
            "cwd": str(self.workspace),
            "hook_event_name": event,
            "host": "codex",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "transcript_path": str(self.transcript_path),
        }
        if event == "Stop":
            payload["stop_hook_active"] = stop_hook_active
            payload["last_assistant_message"] = "Final response candidate"
        if event == "PostToolUse":
            payload.update(
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input or {"command": tool_command or "echo substantive-work"},
                    "tool_response": {"output": "ok"} if tool_response is None else tool_response,
                }
            )
        if event == "SessionStart":
            payload["source"] = source
        if event == "UserPromptSubmit":
            payload["prompt"] = "Continue the task"

        output = io.StringIO()
        with redirect_stdout(output):
            CONTROLLER.handle_hook(payload)
        return output.getvalue().strip()

    # ==========================================
    # Function: Make both required semantic checkpoint files materially different
    # Method: Append one LF-terminated test marker to each file
    # ==========================================
    def update_required_files(self) -> None:
        for name in sorted(CONTROLLER.REQUIRED_CHECKPOINT_FILES):
            path = self.plan_dir / name
            path.write_text(path.read_text(encoding="utf-8") + "\nTest update.\n", encoding="utf-8")

    # ==========================================
    # Function: Record the current hashes through the plain checkpoint CLI path
    # Method: Call the controller operation with no turn identifier and discard its status line
    # ==========================================
    def record_plain_checkpoint(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = CONTROLLER.record_manual_checkpoint(
                self.workspace,
                self.plan_dir.name,
                turn_id=None,
                reconciled=False,
            )
        self.assertEqual(result, 0)

    # ==========================================
    # Function: Simulate PostToolUse for the Agent-issued plain checkpoint command
    # Method: Send the exact controller command shape with the host turn identifier
    # ==========================================
    def stamp_plain_checkpoint_turn(self, turn_id: str) -> None:
        command = f'python3 "{CONTROLLER_PATH}" checkpoint'
        self.assertEqual(
            self.run_hook("PostToolUse", turn_id=turn_id, tool_command=command),
            "",
        )

    # ==========================================
    # Function: Verify direct planning-file edits are accepted without continuation
    # Method: Change required files and invoke Stop once
    # ==========================================
    def test_changed_files_make_stop_silent(self) -> None:
        self.update_required_files()

        self.assertEqual(self.run_hook("Stop", turn_id="turn-changed"), "")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "stop")
        self.assertEqual(state["last_checkpoint_turn_id"], "turn-changed")

    # ==========================================
    # Function: Verify a current-turn plain checkpoint does not create hook feedback
    # Method: Record hashes, stamp the host turn, and stop without further tools
    # ==========================================
    def test_current_turn_manual_checkpoint_makes_stop_silent(self) -> None:
        self.update_required_files()
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-manual")

        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "manual")
        self.assertEqual(state["last_checkpoint_turn_id"], "turn-manual")
        self.assertTrue(state["manual_checkpoint_required_files_changed"])
        self.assertEqual(self.run_hook("Stop", turn_id="turn-manual"), "")

    # ==========================================
    # Function: Verify a redundant plain checkpoint preserves an automatic checkpoint
    # Method: Accept changed files automatically, then invoke the no-change CLI path
    # ==========================================
    def test_redundant_manual_checkpoint_preserves_automatic_origin(self) -> None:
        self.update_required_files()
        state = CONTROLLER.normalize_state(CONTROLLER.load_state(self.plan_dir))
        CONTROLLER.accept_checkpoint(
            self.plan_dir,
            state,
            turn_id="turn-auto",
            transcript_path=None,
            boundary="midturn-checkpoint",
            origin="midturn",
        )

        self.record_plain_checkpoint()
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "midturn")
        self.assertEqual(state["last_checkpoint_turn_id"], "turn-auto")
        self.assertEqual(self.run_hook("Stop", turn_id="turn-auto"), "")

    # ==========================================
    # Function: Verify a stale manual checkpoint can use low-risk deferred recovery
    # Method: Change findings only, record the partial checkpoint, then inspect saved recovery state
    # ==========================================
    def test_manual_checkpoint_without_required_updates_defers(self) -> None:
        findings = self.plan_dir / "findings.md"
        findings.write_text(
            findings.read_text(encoding="utf-8") + "\nFinding only.\n",
            encoding="utf-8",
        )
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-findings")

        state = CONTROLLER.load_state(self.plan_dir)
        self.assertFalse(state["manual_checkpoint_required_files_changed"])
        self.assertEqual(self.run_hook("Stop", turn_id="turn-findings"), "")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["recovery"]["boundary"], "stop-deferred")
        self.assertEqual(state["adaptive"]["pending_reason"], "stop-deferred")

    # ==========================================
    # Function: Verify a previous-turn manual checkpoint is not treated as current
    # Method: Stamp the earlier turn and require deferred reconciliation for the next turn
    # ==========================================
    def test_previous_turn_manual_checkpoint_defers(self) -> None:
        self.update_required_files()
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-old")

        self.assertEqual(self.run_hook("Stop", turn_id="turn-new"), "")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["recovery"]["boundary"], "stop-deferred")

    # ==========================================
    # Function: Verify a no-op checkpoint cannot rebind old manual state to a new turn
    # Method: Preserve old turn metadata and defer the still-stale next turn
    # ==========================================
    def test_noop_manual_checkpoint_does_not_rebind_previous_turn(self) -> None:
        self.update_required_files()
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-old")

        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-new")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_turn_id"], "turn-old")
        self.assertFalse(state["manual_checkpoint_required_files_changed"])

        self.assertEqual(self.run_hook("Stop", turn_id="turn-new"), "")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["recovery"]["boundary"], "stop-deferred")

    # ==========================================
    # Function: Verify work after a manual checkpoint invalidates its silent acceptance
    # Method: Count one substantive PostToolUse event before Stop
    # ==========================================
    def test_substantive_tool_after_manual_checkpoint_still_blocks(self) -> None:
        self.update_required_files()
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-work")
        self.run_hook(
            "PostToolUse",
            turn_id="turn-work",
            tool_command="echo substantive-work",
        )

        response = json.loads(self.run_hook("Stop", turn_id="turn-work"))
        self.assertEqual(response["decision"], "block")

    # ==========================================
    # Function: Verify genuinely stale state requests exactly one continuation
    # Method: Invoke an initial Stop and then its stop_hook_active retry
    # ==========================================
    def test_stale_checkpoint_blocks_once_then_fails_open(self) -> None:
        self.run_hook(
            "PostToolUse",
            turn_id="turn-stale",
            tool_command="echo substantive-work",
        )
        first = json.loads(self.run_hook("Stop", turn_id="turn-stale"))
        self.assertEqual(first["decision"], "block")

        second = json.loads(
            self.run_hook(
                "Stop",
                turn_id="turn-stale",
                stop_hook_active=True,
            )
        )
        self.assertNotIn("decision", second)
        self.assertIn("forced continuation", second["systemMessage"])

    # ==========================================
    # Function: Verify a successful Stop continuation remains a clean checkpoint
    # Method: Block once, update both files, auto-accept, then invoke the active Stop retry
    # ==========================================
    def test_successful_stop_continuation_does_not_record_unsynced_recovery(self) -> None:
        self.run_hook(
            "PostToolUse",
            turn_id="turn-reconciled",
            tool_command="echo substantive-work",
        )
        first = json.loads(self.run_hook("Stop", turn_id="turn-reconciled"))
        self.assertEqual(first["decision"], "block")

        self.update_required_files()
        self.assertEqual(
            self.run_hook(
                "PostToolUse",
                turn_id="turn-reconciled",
                tool_name="apply_patch",
                tool_input={"command": "planning file patch"},
                tool_response={"ok": True},
            ),
            "",
        )
        self.assertEqual(
            self.run_hook(
                "Stop",
                turn_id="turn-reconciled",
                stop_hook_active=True,
            ),
            "",
        )
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "stop")
        self.assertEqual(state["last_boundary"], "stop-checkpoint")
        self.assertIsNone(state["recovery"])

    # ==========================================
    # Function: Verify model guidance prevents redundant plain checkpoints
    # Method: Inspect mid-turn, user-submit, and Stop continuation messages
    # ==========================================
    def test_guidance_reserves_plain_checkpoint_for_hookless_fallback(self) -> None:
        checkpoint_message = CONTROLLER.checkpoint_prompt(self.plan_dir, "test pressure")
        self.assertIn("do not run the plain `superplan.py checkpoint`", checkpoint_message)

        user_submit = json.loads(self.run_hook("UserPromptSubmit", turn_id="turn-guidance"))
        additional_context = user_submit["hookSpecificOutput"]["additionalContext"]
        self.assertIn("do not run the plain `superplan.py checkpoint`", additional_context)

        self.run_hook(
            "PostToolUse",
            turn_id="turn-guidance",
            tool_command="echo substantive-work",
        )
        stop_response = json.loads(self.run_hook("Stop", turn_id="turn-guidance"))
        self.assertIn("Do not run the plain `superplan.py checkpoint`", stop_response["reason"])

    # ==========================================
    # Function: Verify native planning after task completion stays silent
    # Method: Accept a task-complete checkpoint, count update_plan as zero Stop-effective work, then stop
    # ==========================================
    def test_task_complete_followed_by_native_plan_update_is_silent(self) -> None:
        state = CONTROLLER.normalize_state(CONTROLLER.load_state(self.plan_dir))
        CONTROLLER.accept_checkpoint(
            self.plan_dir,
            state,
            turn_id="turn-complete",
            transcript_path=str(self.transcript_path),
            boundary="task-complete",
            origin="task-complete",
        )
        self.run_hook(
            "PostToolUse",
            turn_id="turn-complete",
            tool_name="update_plan",
            tool_input={"plan": [{"step": "done", "status": "completed"}]},
            tool_response={"ok": True},
        )

        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["adaptive"]["tool_calls"], 1)
        self.assertEqual(state["adaptive"]["stop_effective_tools"], 0.0)
        self.assertEqual(self.run_hook("Stop", turn_id="turn-complete"), "")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_boundary"], "stop-housekeeping-tolerated")
        self.assertIsNone(state["recovery"])

    # ==========================================
    # Function: Verify a small read defers instead of generating a continuation
    # Method: Count one quarter effective tool, save a dedicated tail, and inspect pending state
    # ==========================================
    def test_small_read_saves_deferred_stop_recovery(self) -> None:
        self.run_hook(
            "PostToolUse",
            turn_id="turn-read",
            tool_command="git status",
            tool_response="clean",
        )

        self.assertEqual(self.run_hook("Stop", turn_id="turn-read"), "")
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["adaptive"]["stop_effective_tools"], 0.25)
        self.assertEqual(state["adaptive"]["pending_reason"], "stop-deferred")
        recovery = state["recovery"]
        self.assertEqual(recovery["boundary"], "stop-deferred")
        tail_path = self.plan_dir / recovery["tail"]["path"]
        self.assertTrue(tail_path.is_file())
        self.assertIn("bounded deferred Stop transcript tail", tail_path.read_text(encoding="utf-8"))

    # ==========================================
    # Function: Verify the next prompt and resumed session request reconciliation
    # Method: Create deferred state and inspect both lifecycle contexts for the saved tail
    # ==========================================
    def test_next_prompt_and_session_resume_restore_deferred_context(self) -> None:
        self.run_hook("PostToolUse", turn_id="turn-read", tool_command="git status")
        self.assertEqual(self.run_hook("Stop", turn_id="turn-read"), "")

        prompt_output = json.loads(self.run_hook("UserPromptSubmit", turn_id="turn-next"))
        prompt_context = prompt_output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("low-risk Stop tolerance", prompt_context)
        self.assertIn("stop-deferred-tail.txt", prompt_context)

        session_output = json.loads(
            self.run_hook("SessionStart", turn_id="turn-next", source="resume")
        )
        session_context = session_output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("low-risk Stop tolerance", session_context)
        self.assertIn("stop-deferred-tail.txt", session_context)

    # ==========================================
    # Function: Verify planning edits automatically reconcile deferred Stop state
    # Method: Change both required files and let the next PostToolUse accept their hashes
    # ==========================================
    def test_deferred_stop_file_update_is_accepted(self) -> None:
        self.run_hook("PostToolUse", turn_id="turn-read", tool_command="git status")
        self.assertEqual(self.run_hook("Stop", turn_id="turn-read"), "")
        self.update_required_files()

        self.assertEqual(
            self.run_hook(
                "PostToolUse",
                turn_id="turn-next",
                tool_name="apply_patch",
                tool_input={"command": "planning file patch"},
                tool_response={"ok": True},
            ),
            "",
        )
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "stop-deferred")
        self.assertFalse(state["adaptive"]["pending"])
        self.assertIsNone(state["recovery"])
        self.assertEqual(
            self.run_hook(
                "Stop",
                turn_id="turn-next",
                stop_hook_active=True,
            ),
            "",
        )
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "stop-deferred")
        self.assertIsNone(state["recovery"])

    # ==========================================
    # Function: Verify no-edit reconciliation clears deferred Stop state explicitly
    # Method: Invoke the reconciled checkpoint path while stop-deferred is pending
    # ==========================================
    def test_deferred_stop_no_edit_reconciliation_is_recorded(self) -> None:
        self.run_hook("PostToolUse", turn_id="turn-read", tool_command="git status")
        self.assertEqual(self.run_hook("Stop", turn_id="turn-read"), "")

        output = io.StringIO()
        with redirect_stdout(output):
            result = CONTROLLER.record_manual_checkpoint(
                self.workspace,
                self.plan_dir.name,
                turn_id="turn-next",
                reconciled=True,
            )
        self.assertEqual(result, 0)
        self.assertIn("Deferred Stop reconciliation recorded", output.getvalue())
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["last_checkpoint_origin"], "stop-deferred")
        self.assertIsNone(state["recovery"])

    # ==========================================
    # Function: Verify unresolved deferred recovery is enforced on the following Stop
    # Method: Defer one read, skip reconciliation, and require a continuation next turn
    # ==========================================
    def test_unresolved_deferred_stop_blocks_the_next_turn(self) -> None:
        self.run_hook("PostToolUse", turn_id="turn-read", tool_command="git status")
        self.assertEqual(self.run_hook("Stop", turn_id="turn-read"), "")

        response = json.loads(self.run_hook("Stop", turn_id="turn-next"))
        self.assertEqual(response["decision"], "block")
        self.assertIn("reconcile the previous turn", response["reason"])

    # ==========================================
    # Function: Verify one high-risk operation still blocks immediately
    # Method: Count a run as one effective tool, equal to the strict default boundary
    # ==========================================
    def test_one_run_reaches_default_stop_boundary(self) -> None:
        self.run_hook(
            "PostToolUse",
            turn_id="turn-run",
            tool_command="pytest -q",
            tool_response="12 passed, 0 failed",
        )
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["adaptive"]["stop_effective_tools"], 1.0)

        response = json.loads(self.run_hook("Stop", turn_id="turn-run"))
        self.assertEqual(response["decision"], "block")
        self.assertIn("not below the configured defer tolerance", response["reason"])

    # ==========================================
    # Function: Verify fractional reads accumulate to the strict boundary
    # Method: Count four small reads at one quarter each and require immediate Stop enforcement
    # ==========================================
    def test_four_small_reads_reach_default_stop_boundary(self) -> None:
        for index in range(4):
            self.run_hook(
                "PostToolUse",
                turn_id="turn-reads",
                tool_command="git status",
                tool_response=f"clean-{index}",
            )
        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["adaptive"]["stop_effective_tools"], 1.0)

        response = json.loads(self.run_hook("Stop", turn_id="turn-reads"))
        self.assertEqual(response["decision"], "block")

    # ==========================================
    # Function: Verify task completion synchronization never defers
    # Method: Mark completion pending with an unchanged progress hash and invoke Stop directly
    # ==========================================
    def test_completion_pending_remains_a_hard_stop(self) -> None:
        state = CONTROLLER.normalize_state(CONTROLLER.load_state(self.plan_dir))
        state["task_status"] = CONTROLLER.TASK_STATUS_COMPLETION_PENDING
        state["task_completion_progress_hash"] = CONTROLLER.sha256_file(
            self.plan_dir / "progress.md"
        )
        CONTROLLER.save_state(self.plan_dir, state)

        response = json.loads(self.run_hook("Stop", turn_id="turn-completion"))
        self.assertEqual(response["decision"], "block")
        self.assertIn("completion is not final", response["reason"])

    # ==========================================
    # Function: Verify the Stop tolerance remains user configurable
    # Method: Lower the strict boundary so one small read no longer qualifies for deferral
    # ==========================================
    def test_stop_tolerance_environment_override(self) -> None:
        self.run_hook("PostToolUse", turn_id="turn-read", tool_command="git status")
        with patch.dict(
            os.environ,
            {"SUPERPLAN_STOP_DEFER_MAX_EFFECTIVE_TOOLS": "0.25"},
            clear=False,
        ):
            response = json.loads(self.run_hook("Stop", turn_id="turn-read"))
        self.assertEqual(response["decision"], "block")

    # ==========================================
    # Function: Verify SessionEnd retains a pending deferred Stop tail
    # Method: Nest the end pointer without replacing the stop-deferred recovery object
    # ==========================================
    def test_session_end_preserves_deferred_stop_recovery(self) -> None:
        self.run_hook("PostToolUse", turn_id="turn-read", tool_command="git status")
        self.assertEqual(self.run_hook("Stop", turn_id="turn-read"), "")
        self.assertEqual(self.run_hook("SessionEnd", turn_id="turn-read"), "")

        state = CONTROLLER.load_state(self.plan_dir)
        self.assertEqual(state["recovery"]["boundary"], "stop-deferred")
        self.assertEqual(state["recovery"]["session_end"]["transcript_path"], str(self.transcript_path))


if __name__ == "__main__":
    unittest.main()
