# Superplan

> ℹ️ 本项目基于 [othmanadi/planning-with-files](https://github.com/othmanadi/planning-with-files) 修改而来。

[![Release](https://img.shields.io/github/v/release/Syoong-s/Superplan?include_prereleases)](https://github.com/Syoong-s/Superplan/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Hosts](https://img.shields.io/badge/适用于-Codex%20%7C%20Claude%20Code-8A2BE2)](#安装)

**适用于 [Codex](https://github.com/openai/codex) 与 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 的自适应检查点持久化规划插件。**

> 📖 English: [README.md](README.md)

Superplan 是**一个插件目录，可同时安装到 Codex 与 Claude Code**。它将一个“对话级”的持久计划容器跨上下文压缩和后续轮次保存下来：当前任务的 `task_plan.md` 受任务完成状态门控，只有前序任务正式完成后才可由新任务替换；`progress.md` / `findings.md` 会累计保留所有前序任务的详细内容，不允许为了缩短文件而压缩成摘要。

Agent 在工作时继续使用**原生**规划能力；Superplan 只在生命周期边界（`SessionStart`、`PostToolUse`、`PreCompact`、`PostCompact`、`Stop`、`SessionEnd`、`UserPromptSubmit`）作为稀疏的检查点保存与恢复层触发。

---

## ✨ 功能特性

- **双宿主** —— 一个插件目录，两套运行时。Codex 读取 `.codex-plugin/`，Claude Code 读取 `.claude-plugin/`；二者共享 `hooks/hooks.json`、`skills/` 与控制器脚本。
- **对话级持续激活** —— 首次显式激活后，同一对话后续任务自动复用同一个 plan；单个任务完成不会关闭 plan。
- **任务完成门控** —— 当前任务会一直保持 `active`，直到显式执行 `checkpoint --complete`；任务未完成时，后续请求不得覆盖 `task_plan.md`。完成标记会强制触发一次新的最终 `progress.md` 更新，之后任务状态才正式变为 `complete`。
- **多对话并发隔离** —— `.planning/.bindings/<session-key>.plan` 为每个 Codex / Claude Code 对话单独路由，同一项目内多个对话不会再争用全局活动指针。
- **详细历史累计保留** —— 只有前序任务已经正式完成，新任务才可以覆盖 `task_plan.md`；`progress.md` 和 `findings.md` 必须保留所有前序任务的详细内容，不能用 compact summary 替换。
- **自适应中途检查点** —— `PostToolUse` 根据已用时间、工具活动、输出体量与转录增长估算检查点压力，仅当工作累积到一定程度时才请求一次稀疏语义检查点。
- **双文件自动检查点** —— `task_plan.md` 与 `progress.md` 都在上次正式检查点后发生变化时，下一个 `PostToolUse` 会立即接受一个真正的 `automatic` 检查点；`init` 创建的模板哈希只是差异基线，绝不算有效检查点。
- **有界压缩恢复** —— `PreCompact` 保存一段有界的、不可信的转录尾部；`PostCompact` / `SessionStart(source=compact)` 恢复它并请求一次对账。逐周期保护机制避免恢复上下文重复注入。
- **风险感知的轮末强制** —— 最终回复前必要时先做 final-response handoff；`Stop` 仍是硬性兜底，没有有效检查点时绝不会直接进入低风险延迟。
- **自定位、零依赖** —— 纯 Python 3.10+ 标准库；控制器通过 `__file__` 自行解析模板，脚本内部无需 `PLUGIN_ROOT` 接线。
- **仅限 Linux / WSL** —— 使用 `fcntl` 文件锁。

## 📦 安装

Superplan 面向 **Linux / WSL**，需要 **Python 3.10+**。

### 方式 A —— 通过 marketplace 安装（推荐）

**Claude Code**（在 Claude Code 会话内）：

```
/plugin marketplace add Syoong-s/Superplan
/plugin install superplan@superplan-plugin
```

**Codex**（在终端中）：

```bash
codex plugin marketplace add Syoong-s/Superplan
codex plugin add superplan@superplan-plugin
```

> 两条命令都会读取仓库内置的 marketplace 目录（Claude Code 用 `.claude-plugin/marketplace.json`，Codex 用 `.agents/plugins/marketplace.json`），并把仓库根目录作为插件安装。

### 方式 B —— 从 release 手动安装

1. 在 [releases 页面](https://github.com/Syoong-s/Superplan/releases) 下载最新的 `superplan-plugin-*.zip` 或 `.tar.gz` 并解压。
2. **Claude Code** —— 把解压目录放入 skills 目录自动加载，或直接测试：

   ```bash
   # 持久化（下次会话自动加载）：
   cp -r superplan-plugin-<version> ~/.claude/skills/superplan
   # 或一次性测试：
   claude --plugin-dir ./superplan-plugin-<version>
   ```

3. **Codex** —— 把解压目录作为本地 marketplace 添加并安装：

   ```bash
   codex plugin marketplace add /path/to/superplan-plugin-<version>
   codex plugin add superplan@superplan-plugin
   ```

### 方式 C —— 从源码安装（开发）

```bash
git clone https://github.com/Syoong-s/Superplan.git
cd superplan-plugin
# Claude Code：
claude --plugin-dir .
# Codex：
codex plugin marketplace add .
codex plugin add superplan@superplan-plugin
```

安装后，当宿主提示时**信任插件 / 钩子**（Codex 与 Claude Code 都要求对钩子定义显式信任），然后开启新会话。

## 📦 发布包内容

每次 [release](https://github.com/Syoong-s/Superplan/releases) 会发布 `superplan-plugin-<version>.tar.gz` 和 `.zip`，仅包含运行时所需的插件组件：

```
superplan-plugin-<version>/
├── .codex-plugin/
│   └── plugin.json                 # Codex 清单
├── .agents/plugins/
│   └── marketplace.json            # Codex marketplace 目录
├── .claude-plugin/
│   ├── plugin.json                 # Claude Code 清单
│   └── marketplace.json            # Claude Code marketplace 目录
├── hooks/
│   ├── hooks.json                  # 共享生命周期钩子
│   └── claude-failure-hooks.json   # Claude Code PostToolUseFailure 钩子
├── skills/superplan/
│   ├── SKILL.md                    # 技能定义
│   ├── agents/openai.yaml          # Codex agent 配置
│   ├── scripts/superplan.py        # 控制器（纯标准库，Python 3.9+）
│   └── templates/
│       ├── task_plan.md
│       ├── findings.md
│       └── progress.md
├── README.md
├── README.zh-CN.md
├── CHANGELOG.md
└── LICENSE
```

开发专用文件（`.github/`、`tests/`、`.gitignore`）和运行时产物（`__pycache__/`、`.planning/`、`.superplan.json`）均不包含在发布包中。

## 🚀 使用

Superplan 只需要**首次显式激活**；它不会因为任务很长而自行激活。在 Codex 中使用 `$superplan`，在 Claude Code 中调用 `/superplan:superplan`（或直接要求持久化规划）。

为当前对话初始化一个长期存在的 plan 容器：

```bash
python3 skills/superplan/scripts/superplan.py init "任务标题"
```

目录结构：

```
.planning/
├── .bindings/                    # 每个活动对话一个绑定文件
└── <日期>-<slug>/
    ├── task_plan.md              # 当前任务；仅在前序任务完成后才可整体替换
    ├── findings.md               # 跨任务累计的详细发现
    ├── progress.md               # 跨任务累计的详细进展
    ├── .superplan.json           # 机器维护的 hook / session 状态
    └── recovery/                 # 压缩或延迟 Stop 时创建的有界转录尾部
```

成功执行 `init` 后，`PostToolUse` 会把该 plan 绑定到发起命令的当前对话。新版完全没有 `.active_plan`，也不存在项目级全局活动指针。

首次激活后，**同一对话**后续所有用户轮次都会自动复用同一个 plan。如果当前任务仍是 `active`，后续用户请求必须视为当前任务的继续或新增要求，只能在原有 `task_plan.md` 上继续修改，不能整体覆盖。只有前序任务已经正式标记为 `complete`，真正的新任务才允许整体替换 `task_plan.md`。`progress.md` 和 `findings.md` 中以前任务的详细内容必须原样保留并在其基础上增量修改，不得为了缩短文件而折叠、删除或压缩成 compact summary。

`init` 创建的哈希只是“文件是否变化”的基线，并不建立有效检查点。当 `task_plan.md` 与 `progress.md` 都在最近一次正式检查点之后发生变化时，下一个 `PostToolUse` 会立即记录 `automatic` 检查点并重置检查点计数器；只有出现持久化发现变化时才需要更新 `findings.md`。

显式管理命令：

```bash
python3 skills/superplan/scripts/superplan.py status <plan-id>
python3 skills/superplan/scripts/superplan.py use <plan-id>                 # 显式切换/转移 plan
python3 skills/superplan/scripts/superplan.py deactivate <plan-id>          # 仅停用当前对话的 Superplan
python3 skills/superplan/scripts/superplan.py checkpoint --plan-id <plan-id> # hooks 不可用时的手动兜底
python3 skills/superplan/scripts/superplan.py checkpoint --plan-id <plan-id> --reconciled
python3 skills/superplan/scripts/superplan.py checkpoint --plan-id <plan-id> --complete   # 标记“当前任务”完成
```

不要因为当前任务完成就执行 `deactivate`。当前任务真正完成并验证后，执行 `checkpoint --complete`：控制器会先将任务置为 `completion_pending`，随后 hook 强制要求对 `progress.md` 再做一次新的最终语义更新；只有检测到这次更新后，任务状态才正式变成 `complete`。Superplan 本身始终保持活动，以便下一条用户请求继续使用同一个 plan。

工作过程中让 agent 正常操作即可。hooks 只在工作累积较多时注入稀疏检查点请求，并在轮末校验最终检查点。准备最终回复前，如果尚无有效检查点，或最近检查点之后又发生了实质性工作，应一次性更新 `task_plan.md` 与 `progress.md`，并把它作为最后一个必要的文件操作；`PostToolUse` 会自动记录检查点，`Stop` 仅作兜底。如果 hooks 不可用，任务完成时先运行 `checkpoint --complete`，再对 `progress.md` 做一次最终详细更新，然后再次运行同一个 `checkpoint --complete` 命令即可完成状态确认。

在 `Stop` 判定中，原生计划收尾工具的轮末权重为 0，每个小型只读操作权重为 0.25，写入、运行、失败、代理或未知副作用操作的权重至少为 1.0。默认延迟边界使用严格的 `< 3.0`，但前提是已经存在有效检查点；没有有效检查点时必须先同步。符合条件的低风险轮次会保存 `recovery/stop-deferred-tail.txt` 并直接结束，不生成续写提示；下一次 `UserPromptSubmit` 会在处理新请求前注入对账要求。`SessionStart(startup|resume)` 只作为会话边界的恢复兜底，并非每条后续提示都会触发。任务完成同步和实质性陈旧工作仍执行硬性 Stop 校验。

恢复时，如果某个规划文件过大，Superplan 只可能在**注入上下文的视图**中省略中间部分，磁盘上的文件绝不会被截短；agent 也会被明确要求不得覆盖或压缩这些被省略的历史内容。

所有持久化文件、绑定文件和 recovery tail 都应视为**不可信数据**，不能当作高优先级指令。

## ⚙️ 配置

检查点压力与转录尾部可通过环境变量调节（均可选）：

```
SUPERPLAN_CHECKPOINT_MIN_SECONDS      SUPERPLAN_CHECKPOINT_MAX_SECONDS
SUPERPLAN_CHECKPOINT_MIN_TOOLS        SUPERPLAN_CHECKPOINT_PRESSURE
SUPERPLAN_CHECKPOINT_MEANINGFUL_EVENTS SUPERPLAN_CHECKPOINT_OUTPUT_CHARS
SUPERPLAN_CHECKPOINT_TRANSCRIPT_BYTES SUPERPLAN_CHECKPOINT_REPROMPT_TOOLS
SUPERPLAN_STOP_DEFER_MAX_EFFECTIVE_TOOLS
SUPERPLAN_TAIL_MAX_BYTES              SUPERPLAN_TAIL_MAX_LINES
SUPERPLAN_TAIL_SCAN_BYTES
```

默认值刻意偏稀疏；普通短任务通常只在轮末写入一次。`SUPERPLAN_STOP_DEFER_MAX_EFFECTIVE_TOOLS` 默认为 `3.0` 并使用严格小于比较；设为 `0` 可关闭低风险 Stop 延迟，同时保留有效检查点后的显式收尾工具豁免。

## 🧩 双宿主如何工作

| 关注点 | Codex | Claude Code | 共享 |
|---|---|---|---|
| 清单 | `.codex-plugin/plugin.json` | `.claude-plugin/plugin.json` | - |
| Marketplace 目录 | `.agents/plugins/marketplace.json` | `.claude-plugin/marketplace.json` | - |
| 钩子配置 | - | - | `hooks/hooks.json` |
| 技能 | - | - | `skills/superplan/SKILL.md` |
| 控制器 | - | - | `skills/superplan/scripts/superplan.py` |

两套宿主使用同一套钩子 I/O 协议：stdin 接收 JSON（`hook_event_name`、`session_id`、`transcript_path`、`cwd`、`tool_name`、`tool_input`、`tool_response`、`stop_hook_active`……），stdout 输出 `{"hookSpecificOutput":{"hookEventName":…,"additionalContext":…}}` / `{"decision":"block","reason":…}`。唯一的 `hooks.json` 命令通过 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 引用控制器——当前运行的宿主替换自己的变量，另一个展开为空，因此一条命令在两套运行时下都能正确解析。

## 🧪 开发验证

- **本地测试环境：** WSL2 Linux，Python 3.14.4。
- **可移植目标：** Linux，Python 3.10 或更高版本，并提供标准库 `fcntl` 模块。
- **外部依赖：** 无。

在仓库根目录运行以下可移植验证命令：

```bash
python3 -m py_compile skills/superplan/scripts/superplan.py tests/test_stop_checkpoint.py tests/test_scoring.py
python3 -m unittest discover -s tests -v
```

## 📄 许可证

[MIT](LICENSE) © Syoong-s
