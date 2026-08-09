# Changelog

## 1.8.0

- Added a Stop-specific effective-tool tolerance with a strict default boundary of `1.0`: native planning housekeeping counts as `0`, small reads count as `0.25`, and writes/runs/failures/agents count as at least `1.0`.
- Made zero-impact housekeeping after an accepted checkpoint end silently, preventing a final native `update_plan` call from forcing a duplicate Stop continuation.
- Added low-risk deferred Stop recovery. Eligible turns save bounded `stop-deferred-tail.txt` / metadata artifacts and end without blocking; the next `UserPromptSubmit` reconciles first, with `SessionStart(resume)` as a fallback.
- Preserved hard Stop enforcement for `completion_pending`, unresolved mandatory checkpoints, and any tool activity at or above the configured tolerance.
- Preserved deferred recovery across `SessionEnd`, added automatic and explicit no-edit reconciliation paths, and bumped persisted state schema to 10.
- Repaired stale regression fixtures and expectations so the complete 36-test suite matches the current controller and exercises the new Stop lifecycle.

## 1.7.1

- Added machine-owned current-task lifecycle states: `active`, `completion_pending`, and `complete`, while keeping the conversation-scoped Superplan container itself active.
- Restored `checkpoint --complete` with new semantics: it marks only the current task for completion and requires one fresh final `progress.md` update before completion is finalized.
- Prevented later user requests from replacing `task_plan.md` while the current task is unfinished; they are treated as continuation/additional requirements and must update the existing task plan in place.
- Allowed `task_plan.md` replacement only after the preceding task is formally complete; the first subsequent task-plan edit automatically reopens task status as `active`.
- Added Stop enforcement for pending task completion so a missing final progress update cannot silently produce a completed task state.
- Bumped persisted state schema to 9 and plugin version to 1.7.1.

## 1.7.0

- Changed Superplan from one-task/one-plan lifecycle semantics to one persistent plan container per conversation. Completing a user task no longer closes the plan; later turns automatically reuse it unless the user explicitly switches or deactivates.
- Removed the project-global `.planning/.active_plan` mechanism entirely. Active routing now uses `.planning/.bindings/<session-key>.plan`, keyed by host and session id, so concurrent conversations in the same project do not overwrite each other's active plan.
- Added PostToolUse session actions for `init`, `use`, and `deactivate`; `use` explicitly transfers a plan from any previous conversation owner to the calling conversation.
- Made plan-directory reservation atomic, so concurrent `init` calls with the same title safely receive distinct plan ids.
- Made `task_plan.md` current-task state that may be replaced for a new task, while `progress.md` and `findings.md` are cumulative detailed conversation history. Historical task detail must never be compacted, summarized away, or deleted merely to shorten the files.
- Replaced `checkpoint --complete` with explicit conversation-scoped `deactivate <plan-id>`. Manual `status` and `checkpoint` operations now require an explicit plan id because no global active pointer exists.
- Bumped persisted state schema to 8 and plugin version to 1.7.0. No `.active_plan` compatibility or migration path is retained.

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
