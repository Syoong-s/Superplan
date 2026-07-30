# Changelog

## 1.0.0

First public release. Superplan now runs in **both Codex and Claude Code** as a single, shared plugin.

### Added
- **Dual-host support**: one plugin directory installs into Codex (`.codex-plugin/`) and Claude Code (`.claude-plugin/`) simultaneously.
- **Claude Code manifest** (`.claude-plugin/plugin.json`) and **marketplace catalogs** for both hosts (`.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json`).
- **`PostCompact` lifecycle hook**: restores the checkpoint after compaction on Claude Code, mirroring Codex's `SessionStart(source=compact)`. A per-cycle guard (`compact_restore_emitted`) prevents duplicate restore context when both events fire.
- Shared `hooks/hooks.json` now resolves the controller via `${CLAUDE_PLUGIN_ROOT}${PLUGIN_ROOT}` so a single command works under both runtimes, and adds `fork` to the `SessionStart` matcher.
- Host-neutral `SKILL.md` controller resolution: checks `PLUGIN_ROOT` (Codex), `CLAUDE_PLUGIN_ROOT` (Claude Code), and searches both `~/.codex` and `~/.claude`.
- Bilingual README (English + 简体中文) with install tutorials for both hosts.
- GitHub Actions release workflow that publishes the whole plugin directory with each tagged release.
- MIT license.

### Changed
- Plugin version reset to `1.0.0` for the inaugural public, dual-host release.
- Hook command help text and user-facing messages made host-neutral (no longer Codex-only wording).

### Pre-release history (local-only, Codex-only)

## 2.1.1

- Internal packaging refresh of the Codex-only plugin.

## 2.1.0

- Added sparse adaptive `PostToolUse` mid-turn checkpoint requests.
- Added bounded pre-compaction transcript-tail capture with byte and line limits.
- Added automatic `SessionStart(source=compact)` reconciliation instructions.
- Added `checkpoint --reconciled` for no-change or completed reconciliation acknowledgement.
- Added Linux file locking for concurrent hook-state updates.
- Added parent-directory active-plan resolution for hooks running from workspace subdirectories.
