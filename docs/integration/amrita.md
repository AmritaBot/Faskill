# AmritaCore Integration

This guide covers how to integrate faskill with AmritaCore agents.

AmritaCore's tool system follows the **OpenAI paradigm** (JSON Schema modeled
with Pydantic). faskill's AmritaCore integration **mixes** discovered skills
into a `MultiToolsManager` — by default the global `ToolsManager` singleton
(the same one `AbilityContext.tools` / `glb.tools` resolves to). AmritaCore
agents pick the tools up automatically through `AbilityBackend.load_tools()`
without extra plumbing.

## Table of Contents

- [Installation](#installation)
- [Basic Integration](#basic-integration)
- [Progressive Disclosure with Script Tools](#progressive-disclosure-with-script-tools)
- [Tool Schema](#tool-schema)
- [Complete Example](#complete-example)

---

## Installation

```bash
pip install faskill[amrita]   # With AmritaCore integration
pip install faskill[all]      # All extras
```

---

## Basic Integration

```python
import asyncio
import os

from amrita_core import create_agent, minimal_init
from amrita_core.consts import DEFAULT_INSTRUCTIONS
from faskill import create_context
from faskill.integrations.amcore import (
    build_skill_usage_prompt,
    create_amrita_backend,
    create_amrita_tools,
)


async def main() -> None:
    await minimal_init()

    # 1. Discover skills
    ctx = create_context(skill_dirs=["./skills"])
    ctx.discover()

    # 2. Register skills onto a per-session clone of the global ToolsManager
    tools = create_amrita_tools(ctx)

    # 3. Create an agent; AmritaCore 1.0 resolves tools through the backend, so wire the pool in with a BackendSlots (create_agent() no longer takes a tools_manager argument).
    agent = create_agent(
        base_url="https://api.openai.com/v1",
        api_key=os.environ["OPENAI_API_KEY"],
        model="gpt-4o-mini",
        backend=create_amrita_backend(tools),
        train=DEFAULT_INSTRUCTIONS + build_skill_usage_prompt(ctx),
    )

    chat = agent.get_chatobject("Review the code in main.py")
    async with chat.begin():
        async for msg in chat.io_stream.get_response_generator():
            print(msg, end="", flush=True)


asyncio.run(main())
```

The agent decides _when_ to call a skill tool; AmritaCore validates the
arguments against the schema and feeds the result back.

### Wiring tools into an agent (AmritaCore 1.0)

AmritaCore 1.0 resolves a session's tools through
`AbilityBackend.load_tools(session_id)`, and `create_agent()` no longer
accepts a `tools_manager=` keyword. There are two ways to connect faskill
tools:

- **Per-session pool (recommended)** — `create_amrita_tools(ctx)` returns a
  clone of the global manager; pass `backend=create_amrita_backend(tools)` to
  `create_agent()` as shown above.
- **Global singleton** — register directly onto `ToolsManager()` with
  `copy=False`; the default backend (`LegacyBackend`) serves `glb.tools`
  automatically, so no `backend=` is needed:

  ```python
  create_amrita_tools(ctx, copy=False)  # mutates the global ToolsManager
  agent = create_agent(
      base_url=..., api_key=..., model=...,
      train=DEFAULT_INSTRUCTIONS + build_skill_usage_prompt(ctx),
  )
  ```

## System Prompt Snippet

Tool descriptions stay short (the skill's own description). Instead of
repeating usage instructions in every tool, the integration provides a
**system-role prompt snippet** — `build_skill_usage_prompt(ctx)` — that
lists every discovered skill and explains the calling convention
(`arguments` string, `$ARGUMENTS` template, markdown output). Append it
to the agent's system prompt (`train`) so the model knows — once, globally
— when and how to call the skills. It returns an empty string when no skills
are discovered, so concatenation is always safe.

To mix tools into a specific **per-session** manager instead of the global
singleton, pass one explicitly:

```python
tools = create_amrita_tools(ctx, tools_manager=my_session_manager)
```

## Tool Pool Hygiene: `copy=True`

By default (`copy: bool = True`) tools are registered onto a **fresh clone**
of the target manager and the clone is returned — the original manager
(including the global `ToolsManager` singleton) is never mutated. This keeps
each agent session's tool pool isolated and prevents cross-session
contamination (e.g. skills registered by one agent leaking into another's).

```python
# Default: clone — global ToolsManager stays clean, we get our own pool
# (wire it into an agent with create_amrita_backend(tools))
tools = create_amrita_tools(ctx)
assert tools is not ToolsManager()  # a clone
assert not ToolsManager().has_tool("my-skill")

# Opt out: register directly onto the global target (mutates it in place).
# The default LegacyBackend serves glb.tools, so no backend= is needed.
create_amrita_tools(ctx, copy=False)
assert ToolsManager().has_tool("my-skill")
```

`clone_tools_manager(manager)` creates the copy explicitly — it duplicates the
registry (`_models`) and the disabled-tool set (`_disabled_tools`) into a new
`MultiToolsManager`, so tool registration on the clone never affects the
original. Use it to hand each agent session its own pool:

```python
from faskill.integrations.amcore import clone_tools_manager, create_amrita_backend

session_tools = clone_tools_manager(ToolsManager())
create_amrita_tools(ctx, tools_manager=session_tools, copy=False)
backend = create_amrita_backend(session_tools)  # pass as create_agent(backend=...)
```

`register_amrita_script_tools` accepts the same `copy` parameter.

---

## Progressive Disclosure with Script Tools

Per the progressive disclosure pattern (L1 metadata → L2 content → L3 scripts
on demand), script tools are **not** registered eagerly. When the model calls
a skill tool (i.e. the skill is _activated_), that skill's script tools are
injected into the same tools manager on first invocation — automatically, no
manual registration loop needed:

```python
from faskill.integrations.amcore import create_amrita_tools

# Script tools are NOT present yet
create_amrita_tools(ctx)
assert not ToolsManager().has_tool("pdf-extractor__extract")

# ...model calls the "pdf-extractor" skill tool...
# Now the skill's script tools are available on the same manager:
assert ToolsManager().has_tool("pdf-extractor__extract")
```

Each script becomes a tool named `{skill_name}__{script_name}` — e.g.
`pdf-extractor__extract`. Script tools take a **JSON string** in `arguments`
(AmritaCore 1.0 validates it against the schema before the handler runs, so a
raw object would be rejected):

- On success (`exit_code == 0`): returns the script stdout.
- On failure: returns `{"success": false, "error": "..."}` so the model
  receives a structured, actionable error message.

### Unsupported scripts (missing interpreter)

Scripts whose interpreter is unavailable in the current environment (checked
against `INTERPRETER_MAP` + `shutil.which`, same logic as faskill's
`ScriptExecutor`) are **skipped** — the tool is never registered and the model
is told they exist:

> Note: this skill ships script(s) that cannot be executed in the current
> environment (missing interpreter): convert.sh. Read the script source and
> decide how to handle the task yourself.

The model can then read the script source and handle the task itself, instead
of the runner failing at call time.

### Registering scripts eagerly (optional)

If you prefer eager registration (e.g. you know the environment has every
interpreter), use `register_amrita_script_tools`:

```python
from faskill.integrations.amcore import (
    build_script_usage_prompt,
    create_amrita_tools,
    register_amrita_script_tools,
)

create_amrita_tools(ctx)
for skill_meta in ctx.list_skills():
    skill = ctx.load_skill(skill_meta.name)
    if skill.scripts:
        register_amrita_script_tools(skill, ctx)
```

`register_amrita_script_tools` also mixes into the target manager (global
`ToolsManager` by default; pass `tools_manager=` and/or `copy=` to control
targeting and pool hygiene). `build_script_usage_prompt(skill)` returns a
system-role snippet that lists the script tools and their calling convention
— append it to `train` when registering eagerly.

---

## Tool Schema

Every registered tool follows the OpenAI paradigm:

```json
{
  "type": "function",
  "strict": true,
  "function": {
    "name": "code-reviewer",
    "description": "Review code for best practices and potential issues",
    "parameters": {
      "type": "object",
      "properties": {
        "arguments": {
          "type": "string",
          "description": "Arguments to pass to the skill (empty string if none)"
        }
      },
      "required": ["arguments"]
    }
  }
}
```

Handlers follow the AmritaCore contract: `async (data: dict) -> str`. The
returned string is the tool result the model sees. Synchronous faskill
calls (`invoke_skill`, `execute_skill_script`) are dispatched via
`asyncio.to_thread` so the event loop stays responsive.

---

## Complete Example

See [`examples/amrita_agent.py`](../../examples/amrita_agent.py) for a
runnable example, including script tool discovery.
