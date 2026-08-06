# Changelog

## 1.6.0

- Moved every user-adjustable checkpoint, active-time, semantic-hint, recovery, base tool-weight, failure-weight, and size-tier parameter into one configuration section at the beginning of `superplan.py`.
- Replaced separate derived size tables with one explicit `(chars, pressure, effective-tool)` table, making both additions independently editable.
- Removed hard-coded scoring values from `score_tool_event()` and routed all tool categories through named top-level weight constants.
- Kept all existing environment-variable overrides and v1.5.0 scoring behavior unchanged by default.

## 1.5.0

- Increased size-based weighted effective-tool values to 80% of the matching pressure bonus: `0.4/0.8/2.4/4/8/16`.
- Made the 500k tier contribute `+16` effective-tool weight, guaranteeing that it reaches a configured 16-tool threshold once the active-time gate is satisfied.
- Retained the user-selected pressure curve `0.5/1/3/5/10/20` and the 500k cap.

## 1.4.0

- Replaced the 500k size-pressure curve with user-selected bonuses: `0.5/1/3/5/10/20`.
- Added proportional weighted meaningful-tool bonuses at one fifth of pressure: `0.1/0.2/0.6/1/2/4`.
- Applied weighted size bonuses to both edit input and read/search/run output, capped at 500k.
- Stored weighted meaningful-tool totals as decimals while retaining the existing integer threshold configuration.

## 1.3.0

- Reworked pressure scoring across Codex and Claude Code tool names.
- Added separate edit-input and read/output size weighting through a capped 500k tier.
- Reduced pressure from lightweight reads, inspection-only shell commands, and native transient planning tools.
- Distinguished read-only and state-changing MCP/local tools by action verbs.
- Added Claude Code `PostToolUseFailure` accounting without exposing the unsupported event to Codex.
- Expanded structured and textual failure detection.
