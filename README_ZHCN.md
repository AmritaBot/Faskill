# faskill

> **Fork 自 [maxvaega/skillkit](https://github.com/maxvaega/skillkit)**  
> 经过大量重构，修复了多个上游 bug，增强了安全性，并新增了抽象层。  
> 由 [AmritaConstant](https://github.com/AmritaBot) 维护。

<div align="center">

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/faskill)](https://pypi.org/project/faskill/)
[![GitHub release](https://img.shields.io/github/v/release/AmritaBot/faskill)](https://github.com/AmritaBot/faskill/releases)
</div>

**faskill** 是一个 Python 库，将 Anthropic 的 Agent Skills 能力带给任何 LLM 驱动的 Agent。它通过渐进式披露（progressive disclosure）发现、加载并调用打包的专业知识，以节约 token 成本。

## 功能特性

- **SKILL.md 兼容** — 可直接使用任何已有 skill，即插即用
- **框架无关** — 可独立使用，也可与 LangChain 集成（更多集成计划中）
- **模型无关** — 适用于任何 LLM
- **多源发现** — 自定义目录、插件，支持基于优先级的冲突解决
- **渐进式披露** — 元数据优先加载，80% 内存节省，LRU 缓存；脚本按需加载
- **脚本执行** — 支持 Python、Shell、JavaScript、Ruby、Perl，带安全校验和超时控制
- **可插拔 Runner** — `Runner` 抽象层，默认 `HostRunner`；可替换为 Docker、Firecracker 等
- **插件生态** — 支持插件清单（`.claude-plugin/plugin.json`），命名空间化 skill 访问
- **完善的异常层级** — 20+ 类型化异常，精准错误处理

---

## 相比上游 (skillkit) 的重要改进

本 fork 在原始版本基础上进行了大量重构和 bug 修复：

| 类别         | 改进内容                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Bug 修复** | `PRIORITY_CUSTOM` 不再递减 — 5 个以上来源不会触发 `ValueError: Priority must be positive`                                                  |
| **Bug 修复** | `create_langchain_tools()` 不再预加载所有脚本 — 遵循渐进式披露 (L1→L2→L3)                                                                  |
| **新增**     | `InvalidSkillNameError` — 含空格的名称会被拒绝（可通过 `NO_FAIL_ON_SPACE=1` 绕过）                                                         |
| **新增**     | `Runner` 抽象层 — `HostRunner`（默认，单次警告裸机安全风险），支持替换后端                                                                 |
| **新增**     | `ArgumentSerializationError` / `ArgumentSizeError` / `ToolIDValidationError` — 细粒度脚本异常                                              |
| **新增**     | `ConfigurationError` / `AsyncStateError` / `PluginError` — 更完善的错误报告                                                                |
| **重构**     | `SkillManager` → `SkillContext` + `create_context()` 工厂；模块化架构（discovery、parser、registry、invoker、processors、scripts、runner） |
| **重构**     | 完整测试套件（425 个测试），70%+ 覆盖率，全面的测试 fixtures                                                                               |

---

## 安装

```bash
pip install faskill              # 核心库
pip install faskill[langchain]   # LangChain 集成
pip install faskill[all]         # 全部扩展
```

---

## 快速上手

### 1. 创建一个 skill

```
.claude/skills/code-reviewer/SKILL.md
```

```markdown
---
name: code-reviewer
description: 审查代码最佳实践和潜在问题
allowed-tools: Read, Grep
---

# 代码审查

分析提供的代码：

- 最佳实践违规
- 潜在 bug
- 安全漏洞

使用 $ARGUMENTS 访问用户输入。
```

### 2. 独立使用

```python
from faskill import create_context

ctx = create_context(skill_dirs=["./.claude/skills"])
ctx.discover()

# 列出所有可用 skill
for skill in ctx.list_skills():
    print(f"{skill.name}: {skill.description}")

# 调用 skill
result = ctx.invoke_skill("code-reviewer", "审查函数 calculate_total()")
print(result)
```

### 3. 与 LangChain 集成

```python
from faskill import create_context
from faskill.integrations.langchain import create_langchain_tools
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

ctx = create_context(skill_dirs=["./.claude/skills"])
ctx.discover()

tools = create_langchain_tools(ctx)

llm = ChatOpenAI(model="gpt-4o")
agent = create_agent(llm, tools, system_prompt="你是一个有用的助手。")
result = agent.invoke({"messages": [{"role": "user", "content": "帮我审查代码"}]})
```

---

## SKILL.md 格式

```yaml
---
name: my-skill # 必填：唯一标识符
description: ... # 必填：可读描述
allowed-tools: Bash, Read # 可选：工具白名单
version: "1.0" # 可选：语义版本
---
# Skill 内容，使用 $ARGUMENTS 占位符
```

- **参数替换**: `$ARGUMENTS` → 用户输入；`$$ARGUMENTS` → 字面量 `$ARGUMENTS`
- **无占位符**: 参数将被追加到内容末尾

---

## 脚本执行

Skill 可以包含可执行脚本，用于确定性操作：

```
my-skill/
├── SKILL.md
└── scripts/
    └── extract.py
```

```python
result = ctx.execute_skill_script(
    skill_name="my-skill",
    script_name="extract",
    arguments={"file": "doc.pdf", "pages": "all"},
    timeout=30,
)

if result.success:
    print(result.stdout)
else:
    print(f"错误 ({result.exit_code}): {result.stderr}")
```

支持类型: `.py`, `.sh`, `.js`, `.rb`, `.pl`, `.bat`, `.cmd`, `.ps1`。

### 脚本 Runner（可插拔）

`ScriptExecutor` 接受 `runner` 参数 — 可替换为沙箱后端：

```python
from faskill.core.scripts import ScriptExecutor
from faskill.core.runner import HostRunner  # 默认（单次安全警告）

# 默认：裸机执行
executor = ScriptExecutor(runner=HostRunner())

# 未来：Docker, Firecracker, gVisor...
# executor = ScriptExecutor(runner=DockerRunner(image="python:3.12"))
```

---

## API 参考

### `create_context()`

```python
from faskill import create_context

ctx = create_context(
    skill_dirs=["./skills", "./plugins"],  # 目录列表；包含
    # .claude-plugin/plugin.json
    # 的目录被视为插件
    default_script_timeout=30,  # 秒 (1-600)
    max_cache_size=100,  # LRU 缓存条目数
)
```

### `SkillContext`

| 方法                                  | 描述                                            |
| ------------------------------------- | ----------------------------------------------- |
| `discover()`                          | 同步发现 skill                                  |
| `adiscover()`                         | 异步发现 skill                                  |
| `list_skills()`                       | 列出所有已发现 skill 的元数据                   |
| `list_skills(include_qualified=True)` | 列出名称（包含 `plugin:skill` 限定名）          |
| `get_skill(name)`                     | 按名称获取元数据；失败抛出 `SkillNotFoundError` |
| `invoke_skill(name, args)`            | 同步调用（带缓存）                              |
| `ainvoke_skill(name, args)`           | 异步调用（带缓存）                              |
| `execute_skill_script(...)`           | 执行打包的脚本                                  |
| `get_cache_stats()`                   | 缓存命中/未命中统计                             |
| `clear_cache(name?)`                  | 清除缓存条目                                    |
| `add_source(path)`                    | 构造后追加 skill 目录                           |

### 核心类型

| 类型                    | 描述                                         |
| ----------------------- | -------------------------------------------- |
| `SkillMetadata`         | 名称、描述、路径、允许工具、优先级           |
| `Skill`                 | 完整 skill：元数据 + 内容 + 脚本             |
| `SkillSource`           | 源目录及类型和优先级                         |
| `ScriptMetadata`        | 检测到的脚本：名称、路径、语言、描述         |
| `ScriptExecutionResult` | 退出码、stdout、stderr、执行时间等           |
| `CacheStats`            | 缓存大小、最大容量、命中数、未命中数、命中率 |
| `Runner`                | 脚本执行后端的抽象基类                       |
| `HostRunner`            | 默认 Runner — 裸机子进程执行（单次安全警告） |

### 异常继承树

```
SkillsUseError
├── SkillParsingError
│   ├── InvalidYAMLError
│   ├── MissingRequiredFieldError
│   ├── InvalidSkillNameError          # 名称含空格（绕过: NO_FAIL_ON_SPACE=1）
│   └── InvalidFrontmatterError
├── SkillNotFoundError
├── SkillInvocationError
│   ├── ArgumentProcessingError
│   ├── ArgumentSerializationError
│   ├── ArgumentSizeError
│   └── ContentLoadError
├── ConfigurationError
├── AsyncStateError
├── PluginError
│   ├── ManifestNotFoundError
│   ├── ManifestParseError
│   └── ManifestValidationError
├── ScriptError
│   ├── InterpreterNotFoundError
│   ├── ScriptNotFoundError
│   ├── ScriptPermissionError
│   ├── ArgumentSerializationError
│   ├── ArgumentSizeError
│   └── ToolIDValidationError
├── SkillSecurityError
│   ├── SuspiciousInputError
│   ├── SizeLimitExceededError
│   └── PathSecurityError
```

---

## 示例

查看 `examples/` 目录：

| 文件                  | 演示内容             |
| --------------------- | -------------------- |
| `basic_usage.py`      | 同步和异步独立使用   |
| `async_usage.py`      | FastAPI 异步集成     |
| `langchain_agent.py`  | LangChain Agent 集成 |
| `multi_source.py`     | 多源发现与冲突解决   |
| `file_references.py`  | 安全文件路径解析     |
| `caching_demo.py`     | 缓存性能演示         |
| `script_execution.py` | 脚本执行与错误处理   |

---

## 文档

- **[核心功能](docs/core-features.md)** — 多源发现、缓存、脚本、模式
- **[API 参考](docs/reference.md)** — SKILL.md 规范、系统需求、开发
- **[LangChain 集成](docs/integration/langchain.md)** — 同步/异步、脚本工具、工具 ID 格式

---

## 寻找 skill

- [Anthropic Skills Library](https://github.com/anthropics/skills)
- [Claude-Plugins.dev](https://claude-plugins.dev/skills)
- [awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills)
- [awesome-skills](https://github.com/maxvaega/awesome-skills)

---

## 贡献

1. Fork → 创建分支 → 修改 → 添加测试
2. 确保 `uv run pytest` 通过（≥70% 覆盖率）
3. 确保 `uv run ruff check src/` 和 `uv run pyright src/` 通过
4. 提交 Pull Request

详细指南见 **[CONTRIBUTING.md](CONTRIBUTING.md)**。

---

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
