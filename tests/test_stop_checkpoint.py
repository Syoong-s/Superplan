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
    ) -> str:
        payload: dict[str, object] = {
            "cwd": str(self.workspace),
            "hook_event_name": event,
            "session_id": self.session_id,
            "turn_id": turn_id,
        }
        if event == "Stop":
            payload["stop_hook_active"] = stop_hook_active
            payload["last_assistant_message"] = "Final response candidate"
        if event == "PostToolUse":
            payload.update(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": tool_command or "echo substantive-work"},
                    "tool_response": {"output": "ok"},
                }
            )

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
                turn_id=None,
                complete=False,
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
    # Function: Verify a manual checkpoint without both required edits cannot bypass Stop
    # Method: Change findings only, record and stamp the checkpoint, then attempt to stop
    # ==========================================
    def test_manual_checkpoint_without_required_updates_still_blocks(self) -> None:
        findings = self.plan_dir / "findings.md"
        findings.write_text(
            findings.read_text(encoding="utf-8") + "\nFinding only.\n",
            encoding="utf-8",
        )
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-findings")

        state = CONTROLLER.load_state(self.plan_dir)
        self.assertFalse(state["manual_checkpoint_required_files_changed"])
        response = json.loads(self.run_hook("Stop", turn_id="turn-findings"))
        self.assertEqual(response["decision"], "block")

    # ==========================================
    # Function: Verify a manual checkpoint from an earlier turn remains stale
    # Method: Stamp one turn and attempt to stop a different turn
    # ==========================================
    def test_previous_turn_manual_checkpoint_still_blocks(self) -> None:
        self.update_required_files()
        self.record_plain_checkpoint()
        self.stamp_plain_checkpoint_turn("turn-old")

        response = json.loads(self.run_hook("Stop", turn_id="turn-new"))
        self.assertEqual(response["decision"], "block")

    # ==========================================
    # Function: Verify a no-op checkpoint cannot rebind old manual state to a new turn
    # Method: Repeat the plain command without file changes and inspect the retained turn metadata
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

        response = json.loads(self.run_hook("Stop", turn_id="turn-new"))
        self.assertEqual(response["decision"], "block")

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
    # Function: Verify model guidance prevents redundant plain checkpoints
    # Method: Inspect mid-turn, user-submit, and Stop continuation messages
    # ==========================================
    def test_guidance_reserves_plain_checkpoint_for_hookless_fallback(self) -> None:
        checkpoint_message = CONTROLLER.checkpoint_prompt(self.plan_dir, "test pressure")
        self.assertIn("do not run the plain `superplan.py checkpoint`", checkpoint_message)

        user_submit = json.loads(self.run_hook("UserPromptSubmit", turn_id="turn-guidance"))
        additional_context = user_submit["hookSpecificOutput"]["additionalContext"]
        self.assertIn("do not run the plain `superplan.py checkpoint`", additional_context)

        stop_response = json.loads(self.run_hook("Stop", turn_id="turn-guidance"))
        self.assertIn("Do not run the plain `superplan.py checkpoint`", stop_response["reason"])


if __name__ == "__main__":
    unittest.main()
