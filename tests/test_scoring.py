#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "skills/superplan/scripts/superplan.py"
spec = importlib.util.spec_from_file_location("superplan_controller", MODULE_PATH)
assert spec and spec.loader
superplan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(superplan)


def payload(tool_name: str, *, tool_input=None, tool_response=None, event="PostToolUse", error=None):
    value = {
        "hook_event_name": event,
        "tool_name": tool_name,
        "tool_input": tool_input or {},
    }
    if tool_response is not None:
        value["tool_response"] = tool_response
    if error is not None:
        value["error"] = error
    return value


class ScoringTests(unittest.TestCase):
    # ==========================================
    # Function: Verify configured pressure tiers and their cap
    # Method: Compare boundary sizes with the controller's current tuning table
    # ==========================================
    def test_size_tiers_cap_at_500k(self):
        expected = {
            4_999: 0.0,
            5_000: 0.5,
            20_000: 2.0,
            60_000: 4.0,
            120_000: 8.0,
            250_000: 15.0,
            500_000: 30.0,
            900_000: 30.0,
        }
        for chars, bonus in expected.items():
            with self.subTest(chars=chars):
                self.assertEqual(superplan.size_pressure_bonus(chars), bonus)

    # ==========================================
    # Function: Verify configured meaningful-event tiers and their cap
    # Method: Compare boundary sizes with the independent effective-tool table values
    # ==========================================
    def test_effective_tool_tiers_match_configuration(self):
        expected = {
            4_999: 0.0,
            5_000: 0.3,
            20_000: 1.0,
            60_000: 3.0,
            120_000: 6.0,
            250_000: 12.0,
            500_000: 24.0,
            900_000: 24.0,
        }
        for chars, bonus in expected.items():
            with self.subTest(chars=chars):
                self.assertEqual(superplan.size_meaningful_bonus(chars), bonus)

    # ==========================================
    # Function: Verify edit scoring uses edited input size
    # Method: Ignore a larger echoed response and apply the current 120k tier
    # ==========================================
    def test_edit_uses_input_size_not_response(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Edit",
            tool_input={"old_string": "x", "new_string": "n" * 120_000},
            tool_response={"success": True, "echo": "r" * 500_000},
        ))
        self.assertEqual(score, 11.0)  # 3.0 + 8.0
        self.assertEqual(meaningful, 7.0)  # base edit 1.0 + 120k size weight 6.0

    # ==========================================
    # Function: Verify write scoring reaches the configured 500k cap
    # Method: Apply capped input-size additions to the base write weight
    # ==========================================
    def test_write_reaches_500k_cap(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Write", tool_input={"content": "x" * 700_000}, tool_response={"success": True}
        ))
        self.assertEqual(score, 33.5)  # 3.5 + capped 30.0
        self.assertEqual(meaningful, 25.0)  # base write 1.0 + capped size weight 24.0


    # ==========================================
    # Function: Verify one 500k edit reaches a 24-event threshold
    # Method: Feed the current capped write score into the hard checkpoint predicate
    # ==========================================
    def test_one_500k_edit_reaches_twenty_four_tool_threshold(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Write", tool_input={"content": "x" * 500_000}, tool_response={"success": True}
        ))
        self.assertEqual(score, 33.5)
        self.assertEqual(meaningful, 25.0)
        state = {"adaptive": superplan.fresh_adaptive_state()}
        state["adaptive"].update({
            "active_seconds": 1_200.0,
            "pressure_score": score,
            "tool_calls": 1,
            "meaningful_events": meaningful,
        })
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"SUPERPLAN_CHECKPOINT_MEANINGFUL_EVENTS": "24"}, clear=False):
            due, reason = superplan.checkpoint_due(state, {})
        self.assertTrue(due)
        self.assertIn("weighted meaningful tools", reason)

    # ==========================================
    # Function: Verify read scoring uses visible output size
    # Method: Apply the current 250k tier to a small read base weight
    # ==========================================
    def test_read_uses_output_size(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Read", tool_input={"file_path": "/tmp/x"}, tool_response="x" * 250_000
        ))
        self.assertEqual(score, 15.5)  # 0.5 + 15.0
        self.assertEqual(meaningful, 12.0)  # +12.0 weighted tool bonus at 250k

    # ==========================================
    # Function: Verify a 500k read reaches the current capped weight
    # Method: Add the configured maximum output-size tier to the read base
    # ==========================================
    def test_500k_read_reaches_twenty_four_weight(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Read", tool_input={"file_path": "/tmp/huge"}, tool_response="x" * 500_000
        ))
        self.assertEqual(score, 30.5)
        self.assertEqual(meaningful, 24.0)

    def test_native_plan_update_is_lightweight(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "update_plan", tool_input={"plan": [{"step": "work", "status": "in_progress"}]},
            tool_response={"ok": True},
        ))
        self.assertEqual(score, 0.5)
        self.assertEqual(meaningful, 0)

    def test_light_bash_is_not_meaningful(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Bash", tool_input={"command": "git status"}, tool_response="clean"
        ))
        self.assertEqual(score, 0.5)
        self.assertEqual(meaningful, 0)

    def test_test_command_and_failure(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Bash", tool_input={"command": "pytest -q"}, tool_response="2 failed in 1.0s"
        ))
        self.assertEqual(score, 5.0)  # run 2.5 + failure 2.5
        self.assertEqual(meaningful, 2)

    def test_zero_failed_is_not_failure(self):
        event = payload("Bash", tool_input={"command": "pytest -q"}, tool_response="12 passed, 0 failed")
        self.assertFalse(superplan.tool_failed(event))
        score, meaningful, _ = superplan.score_tool_event(event)
        self.assertEqual(score, 2.5)
        self.assertEqual(meaningful, 1)

    def test_claude_failure_event_is_counted(self):
        score, meaningful, chars = superplan.score_tool_event(payload(
            "Bash",
            tool_input={"command": "npm test"},
            event="PostToolUseFailure",
            error="Exit code 1\nError: missing module",
        ))
        self.assertGreater(chars, 0)
        self.assertEqual(score, 5.0)
        self.assertEqual(meaningful, 2)

    # ==========================================
    # Function: Verify MCP reads and writes remain distinct
    # Method: Apply read base weight and current 20k input tier independently
    # ==========================================
    def test_mcp_read_and_write_are_distinct(self):
        read_score, read_meaningful, _ = superplan.score_tool_event(payload(
            "mcp__github__list_issues", tool_response=[]
        ))
        write_score, write_meaningful, _ = superplan.score_tool_event(payload(
            "mcp__gmail__send_email", tool_input={"body": "x" * 20_000}, tool_response={"sent": True}
        ))
        self.assertEqual(read_score, 0.75)
        self.assertEqual(read_meaningful, 0)
        self.assertEqual(write_score, 5.5)
        self.assertEqual(write_meaningful, 2.0)

    # ==========================================
    # Function: Verify Stop-specific risk distinguishes housekeeping, reads, and runs
    # Method: Reuse semantic scoring while enforcing zero, fractional, and hard weights
    # ==========================================
    def test_stop_effective_tool_weights(self):
        native = payload(
            "update_plan",
            tool_input={"plan": [{"step": "done", "status": "completed"}]},
            tool_response={"ok": True},
        )
        read = payload("Bash", tool_input={"command": "git status"}, tool_response="clean")
        run = payload("Bash", tool_input={"command": "pytest -q"}, tool_response="12 passed")

        _, native_meaningful, _ = superplan.score_tool_event(native)
        _, read_meaningful, _ = superplan.score_tool_event(read)
        _, run_meaningful, _ = superplan.score_tool_event(run)
        self.assertEqual(superplan.stop_effective_tool_weight(native, native_meaningful), 0.0)
        self.assertEqual(superplan.stop_effective_tool_weight(read, read_meaningful), 0.25)
        self.assertEqual(superplan.stop_effective_tool_weight(run, run_meaningful), 1.0)

    # ==========================================
    # Function: Verify a failed native planning call is not harmless housekeeping
    # Method: Apply the failure floor before the native-planning zero-weight exemption
    # ==========================================
    def test_failed_native_plan_update_reaches_stop_boundary(self):
        failed_native = payload(
            "update_plan",
            tool_input={"plan": []},
            tool_response={"ok": False, "error": "invalid plan"},
        )
        _, meaningful, _ = superplan.score_tool_event(failed_native)
        self.assertGreaterEqual(meaningful, 1.0)
        self.assertEqual(
            superplan.stop_effective_tool_weight(failed_native, meaningful),
            meaningful,
        )


if __name__ == "__main__":
    unittest.main()
