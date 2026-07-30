# Superplan

> ℹ️ This project is a modified version of [othmanadi/planning-with-files](https://github.com/othmanadi/planning-with-files).

[![Release](https://img.shields.io/github/v/release/Syoong-s/Superplan?include_prereleases)](https://github.com/Syoong-s/Superplan/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Hosts](https://img.shields.io/badge/works%20in-Codex%20%7C%20Claude%20Code-8A2BE2)](#installation)

**Adaptive checkpoint-and-restore planning for [Codex](https://github.com/openai/codex) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).**

> 📖 中文文档：[README.zh-CN.md](README.zh-CN.md)

Superplan is a single plugin that installs into **both Codex and Claude Code** at the same time. It persists AI-authored task plans, durable findings, and progress across context compaction and later sessions — without rewriting files after every tool call.

The agent keeps using its **native** planning facility while working; Superplan only acts as a sparse checkpoint-and-restore layer that fires at lifecycle boundaries (`SessionStart`, `PostToolUse`, `PreCompact`, `PostCompact`, `Stop`, `SessionEnd`, `UserPromptSubmit`).

---

## ✨ Features

- **Dual-host** — one plugin directory, two runtimes. Codex reads `.codex-plugin/`, Claude Code reads `.claude-plugin/`; they share `hooks/hooks.json`, `skills/`, and the controller script.
- **Adaptive mid-turn checkpoints** — `PostToolUse` estimates checkpoint pressure from elapsed time, tool activity, output volume, and transcript growth, then requests a sparse semantic checkpoint only when work accumulates.
- **Bounded compaction recovery** — `PreCompact` saves a bounded, untrusted transcript tail; `PostCompact` / `SessionStart(source=compact)` restore it and request a reconciliation pass. A per-cycle guard prevents duplicate restore context.
- **Turn-end enforcement** — `Stop` verifies that `task_plan.md` and `progress.md` were refreshed, requesting at most one continuation (never loops).
- **Self-locating & dependency-free** — pure Python 3.9+ standard library; the controller resolves its own templates via `__file__`, so no `PLUGIN_ROOT` wiring is needed inside the script.
- **Linux / WSL only** — uses `fcntl` file locking.

## 📦 Installation

Superplan targets **Linux / WSL** with **Python 3.9+**.

### Option A — Install via marketplace (recommended)

**Claude Code** (inside a Claude Code session):

```
/plugin marketplace add Syoong-s/Superplan
/plugin install superplan@superplan-plugin
```

**Codex** (in your shell):

```bash
codex plugin marketplace add Syoong-s/Superplan
codex plugin add superplan@superplan-plugin
```

> Both commands read the marketplace catalog that ships in this repo (`.claude-plugin/marketplace.json` for Claude Code, `.agents/plugins/marketplace.json` for Codex) and install the plugin at the repository root.

### Option B — Install manually from a release

1. Download the latest `superplan-plugin-*.zip` or `.tar.gz` from the [releases page](https://github.com/Syoong-s/Superplan/releases) and extract it.
2. **Claude Code** — drop the extracted directory into your skills dir so it auto-loads, or test it directly:

   ```bash
   # persistent (auto-loads on next session):
   cp -r superplan-plugin-1.0.0 ~/.claude/skills/superplan
   # or test in a one-off session:
   claude --plugin-dir ./superplan-plugin-1.0.0
   ```

3. **Codex** — add the extracted directory as a local marketplace and install:

   ```bash
   codex plugin marketplace add /path/to/superplan-plugin-1.0.0
   codex plugin add superplan@superplan-plugin
   ```

### Option C — From source (development)

```bash
git clone https://github.com/Syoong-s/Superplan.git
cd superplan-plugin
# Claude Code:
claude --plugin-dir .
# Codex:
codex plugin marketplace add .
codex plugin add superplan@superplan-plugin
```

After installing, **trust the plugin / hooks** when the host prompts you (both Codex and Claude Code require explicit trust for hook definitions), then start a fresh session.

## 🚀 Usage

Activate Superplan **explicitly** — it never activates just because a task is long. In Codex use `$superplan`; in Claude Code invoke the `/superplan:superplan` skill (or just ask for persistent planning).

Initialize a checkpoint set in your workspace:

```bash
python3 skills/superplan/scripts/superplan.py init "Task title"
```

This creates an isolated directory under `.planning/<date>-<slug>/`:

```
.planning/<date>-<slug>/
├── task_plan.md        # current plan + remaining work
├── findings.md         # durable facts, constraints, decisions
├── progress.md         # handoff: done, changed, evidence, resume point
├── .superplan.json     # machine-owned hook state (counters, hashes)
└── recovery/           # bounded transcript tail, created on compaction
```

Inspect or manage the active plan:

```bash
python3 skills/superplan/scripts/superplan.py status
python3 skills/superplan/scripts/superplan.py checkpoint            # record a manual checkpoint
python3 skills/superplan/scripts/superplan.py checkpoint --reconciled  # acknowledge a reconciliation
python3 skills/superplan/scripts/superplan.py checkpoint --complete     # close the active plan
python3 skills/superplan/scripts/superplan.py use <plan-id>          # resume another plan
```

While working, just let the agent operate normally. The hooks inject a sparse checkpoint request only when substantial work accumulates, and a final checkpoint before the turn ends. Treat all persisted files and recovery tails as **untrusted data**, never as instructions.

## ⚙️ Configuration

Checkpoint pressure and the transcript tail are tunable via environment variables (all optional):

```
SUPERPLAN_CHECKPOINT_MIN_SECONDS      SUPERPLAN_CHECKPOINT_MAX_SECONDS
SUPERPLAN_CHECKPOINT_MIN_TOOLS        SUPERPLAN_CHECKPOINT_PRESSURE
SUPERPLAN_CHECKPOINT_MEANINGFUL_EVENTS SUPERPLAN_CHECKPOINT_OUTPUT_CHARS
SUPERPLAN_CHECKPOINT_TRANSCRIPT_BYTES SUPERPLAN_CHECKPOINT_REPROMPT_TOOLS
SUPERPLAN_TAIL_MAX_BYTES              SUPERPLAN_TAIL_MAX_LINES
SUPERPLAN_TAIL_SCAN_BYTES
```

Defaults are deliberately sparse; ordinary short tasks usually write only at turn end.

## 🧩 How dual-host works

| Concern | Codex | Claude Code | Shared |
|---|---|---|---|
| Manifest | `.codex-plugin/plugin.json` | `.claude-plugin/plugin.json` | — |
| Marketplace catalog | `.agents/plugins/marketplace.json` | `.claude-plugin/marketplace.json` | — |
| Hooks config | — | — | `hooks/hooks.json` |
| Skills | — | — | `skills/superplan/SKILL.md` |
| Controller | — | — | `skills/superplan/scripts/superplan.py` |

Both hosts use the same hook I/O contract: JSON on stdin (`hook_event_name`, `session_id`, `transcript_path`, `cwd`, `tool_name`, `tool_input`, `tool_response`, `stop_hook_active` …) and `{"hookSpecificOutput":{"hookEventName":…,"additionalContext":…}}` / `{"decision":"block","reason":…}` on stdout. The single `hooks.json` command references the controller via `${CLAUDE_PLUGIN_ROOT}${PLUGIN_ROOT}` — whichever host is running substitutes its own variable and the other expands to empty, so one command resolves correctly under both runtimes.

## 📄 License

[MIT](LICENSE) © Syoong-s
