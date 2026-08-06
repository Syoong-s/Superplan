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
    def test_size_tiers_cap_at_500k(self):
        expected = {
            4_999: 0.0,
            5_000: 0.5,
            20_000: 1.0,
            60_000: 3.0,
            120_000: 5.0,
            250_000: 10.0,
            500_000: 20.0,
            900_000: 20.0,
        }
        for chars, bonus in expected.items():
            with self.subTest(chars=chars):
                self.assertEqual(superplan.size_pressure_bonus(chars), bonus)

    def test_effective_tool_tiers_are_eighty_percent_of_pressure(self):
        expected = {
            4_999: 0.0,
            5_000: 0.4,
            20_000: 0.8,
            60_000: 2.4,
            120_000: 4.0,
            250_000: 8.0,
            500_000: 16.0,
            900_000: 16.0,
        }
        for chars, bonus in expected.items():
            with self.subTest(chars=chars):
                self.assertEqual(superplan.size_meaningful_bonus(chars), bonus)

    def test_edit_uses_input_size_not_response(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Edit",
            tool_input={"old_string": "x", "new_string": "n" * 120_000},
            tool_response={"success": True, "echo": "r" * 500_000},
        ))
        self.assertEqual(score, 8.0)  # 3.0 + 5.0
        self.assertEqual(meaningful, 5.0)  # base edit 1.0 + 120k size weight 4.0

    def test_write_reaches_500k_cap(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Write", tool_input={"content": "x" * 700_000}, tool_response={"success": True}
        ))
        self.assertEqual(score, 23.5)  # 3.5 + capped 20.0
        self.assertEqual(meaningful, 17.0)  # base write 1.0 + capped size weight 16.0


    def test_one_500k_edit_reaches_sixteen_tool_threshold(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Write", tool_input={"content": "x" * 500_000}, tool_response={"success": True}
        ))
        self.assertEqual(score, 23.5)
        self.assertEqual(meaningful, 17.0)
        state = {"adaptive": superplan.fresh_adaptive_state()}
        state["adaptive"].update({
            "active_seconds": 1_200.0,
            "pressure_score": score,
            "tool_calls": 1,
            "meaningful_events": meaningful,
        })
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"SUPERPLAN_CHECKPOINT_MEANINGFUL_EVENTS": "16"}, clear=False):
            due, reason = superplan.checkpoint_due(state, {})
        self.assertTrue(due)
        self.assertIn("weighted meaningful tools", reason)

    def test_read_uses_output_size(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Read", tool_input={"file_path": "/tmp/x"}, tool_response="x" * 250_000
        ))
        self.assertEqual(score, 10.5)  # 0.5 + 10.0
        self.assertEqual(meaningful, 8.0)  # +8.0 weighted tool bonus at 250k

    def test_500k_read_reaches_sixteen_weight(self):
        score, meaningful, _ = superplan.score_tool_event(payload(
            "Read", tool_input={"file_path": "/tmp/huge"}, tool_response="x" * 500_000
        ))
        self.assertEqual(score, 20.5)
        self.assertEqual(meaningful, 16.0)

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

    def test_mcp_read_and_write_are_distinct(self):
        read_score, read_meaningful, _ = superplan.score_tool_event(payload(
            "mcp__github__list_issues", tool_response=[]
        ))
        write_score, write_meaningful, _ = superplan.score_tool_event(payload(
            "mcp__gmail__send_email", tool_input={"body": "x" * 20_000}, tool_response={"sent": True}
        ))
        self.assertEqual(read_score, 0.75)
        self.assertEqual(read_meaningful, 0)
        self.assertEqual(write_score, 4.5)
        self.assertEqual(write_meaningful, 1.8)


if __name__ == "__main__":
    unittest.main()
