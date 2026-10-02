"""AmritaCore integration for faskill library.

This module adapters discovered skills into AmritaCore tools, following the
OpenAI-paradigm JSON Schema (modeled with Pydantic) used by AmritaCore's
tool system.  Tools are mixed into a ``MultiToolsManager`` — by default the
global ``ToolsManager`` singleton (the same one ``AbilityContext.tools`` /
``glb.tools`` resolves to), so AmritaCore agents can pick them up through
``AbilityBackend.load_tools()`` without extra plumbing.

Progressive disclosure (a skill is an atomic execution unit):

- **L1/L2** — only the skill's minimal metadata is loaded up front: one tool
  per skill whose description is the skill's own one-liner.  The heavy
  SKILL.md prompt is *not* pushed into tool descriptions; instead a
  **system-role prompt snippet** (:func:`build_skill_usage_prompt`) tells the
  model once, globally, when and how to call skills
  (``create_agent(..., train=...)``).
- **L3** — script tools are *not* registered eagerly.  Once the model
  actually calls a skill (activating it), that skill's script tools are
  injected into the same manager automatically.  Scripts whose interpreter is
  unavailable in the current environment are skipped, and the model is told
  they exist so it can decide how to handle the task itself.

Tool-pool hygiene: registration functions take ``copy: bool = True`` and
clone the target manager's registry before registering, so the global
``ToolsManager`` singleton is never polluted.  Use :func:`clone_tools_manager`
for a fresh per-session tool pool, and :func:`create_amrita_backend` to hand
that pool to an AmritaCore 1.0 agent (``create_agent(..., backend=...)``).

Installation:
    pip install faskill[amrita]
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import TYPE_CHECKING, Any, Dict

# Import guards for optional dependencies
try:
    from amrita_core.base.backend import BackendSlots, MemoryBackend
    from amrita_core.builtins.backends import LegacyBackend
    from amrita_core.contexts import AbilityContext
    from amrita_core.tools.manager import MultiToolsManager, ToolsManager
    from amrita_core.tools.models import (
        FunctionDefinitionSchema,
        FunctionParametersSchema,
        FunctionPropertySchema,
        ToolData,
        ToolFunctionSchema,
    )
except ImportError as e:
    raise ImportError(
        "AmritaCore integration requires additional dependencies. "
        "Install with: pip install faskill[amrita]"
    ) from e

if TYPE_CHECKING:
    from faskill.core.manager import SkillContext
    from faskill.core.models import Skill
    from faskill.core.scripts import ScriptMetadata

# Tool parameter name (aligned with the LangChain integration's SkillInput)
_ARGUMENTS_PARAM = "arguments"

# System-role prompt sections appended to the agent's system prompt (train) that teach the model when and how to call the registered skill/script tools, instead of repeating the guide in every tool description.
_SKILL_USAGE_SECTION = (
    "\n\n## Available faskill skills\n"
    "Call a skill tool when the user's task matches its purpose. "
    'Pass the user\'s request as the "arguments" string; it is inserted into '
    "the skill template via $ARGUMENTS. "
    "The tool returns the processed skill output (markdown)."
)

_SCRIPT_USAGE_SECTION = (
    "\n\n## Skill scripts\n"
    'Pass a JSON object encoded as a string in "arguments"; it is parsed and '
    "forwarded to the script via stdin. On success the script stdout is "
    'returned; on failure a JSON object {"success": false, "error": "..."} is '
    "returned so you can self-correct."
)


def _build_arguments_schema(
    *,
    name: str,
    description: str,
    parameter_description: str = "Arguments to pass to the tool",
) -> ToolFunctionSchema:
    """Build an OpenAI-paradigm ``ToolFunctionSchema`` with a single ``arguments`` parameter.

    Args:
        name: Tool name (skill name or ``{skill}__{script}``).
        description: Tool description shown to the model.
        parameter_description: Description for the ``arguments`` parameter.

    Returns:
        A ready-to-register ``ToolFunctionSchema``.
    """
    return ToolFunctionSchema(
        type="function",
        strict=True,
        function=FunctionDefinitionSchema(
            name=name,
            description=description,
            parameters=FunctionParametersSchema(
                type="object",
                properties={
                    _ARGUMENTS_PARAM: FunctionPropertySchema(
                        type="string",
                        description=parameter_description,
                    ),
                },
                required=[_ARGUMENTS_PARAM],
            ),
        ),
    )


def _register_tool(
    tools_manager: MultiToolsManager,
    schema: ToolFunctionSchema,
    handler: Any,
) -> None:
    """Register a tool on a ``MultiToolsManager`` (no-op if the name is taken)."""
    if tools_manager.has_tool(schema.function.name):
        return
    tools_manager.register_tool(
        ToolData(
            data=schema,
            func=handler,
        )
    )


def clone_tools_manager(tools_manager: MultiToolsManager) -> MultiToolsManager:
    """Create a fresh ``MultiToolsManager`` with a copied tool registry.

    The copy owns independent ``_models`` / ``_disabled_tools`` containers, so
    registering tools on the copy never mutates the original manager (e.g. the
    global ``ToolsManager`` singleton).  Handlers/schemas (``ToolData``) are
    shared by reference — they are treated as immutable.

    Use this to hand each agent session its own tool pool instead of passing
    the bare global manager around.

    Args:
        tools_manager: Manager whose registry to copy.

    Returns:
        A new ``MultiToolsManager`` instance (never the same object).
    """
    clone = MultiToolsManager()
    clone._models = dict(tools_manager._models)
    clone._disabled_tools = set(tools_manager._disabled_tools)
    return clone


class _SkillAbilityBackend(LegacyBackend):
    """In-process ability backend that serves a faskill tool manager.

    Subclasses :class:`~amrita_core.builtins.backends.LegacyBackend` (which
    already implements memory/billing) and overrides only tool resolution, so
    the agent sees the faskill pool instead of the global ``ToolsManager``
    singleton.
    """

    def __init__(self, tools: MultiToolsManager) -> None:
        super().__init__()
        self._skill_tools = tools

    async def load_ability_all(self, session_id: str) -> AbilityContext:  # noqa: ARG002
        # Reuse the global context's presets/mcp/extra so only the tool pool differs.
        base = self.glb
        return AbilityContext(
            tools=self._skill_tools,
            presets=base.presets,
            mcp=base.mcp,
            extra=base.extra,
        )

    async def load_tools(self, session_id: str) -> MultiToolsManager:  # noqa: ARG002
        return self._skill_tools


def create_amrita_backend(
    tools: MultiToolsManager,
    memory_backend: MemoryBackend | None = None,
) -> BackendSlots:
    """Wire a faskill tool manager into an AmritaCore 1.0 agent.

    AmritaCore 1.0 resolves tools through ``AbilityBackend.load_tools()`` — the
    default :class:`~amrita_core.builtins.backends.LegacyBackend` returns the
    global ``ToolsManager()`` singleton, and ``create_agent()`` no longer
    accepts a ``tools_manager`` argument.  Pass the slots built here as
    ``backend=`` to run an agent against a per-session pool (e.g. the clone
    returned by :func:`create_amrita_tools`):

    .. code-block:: python

        tools = create_amrita_tools(ctx)            # per-session clone
        agent = create_agent(
            base_url=...,
            api_key=...,
            model=...,
            backend=create_amrita_backend(tools),
            train=DEFAULT_INSTRUCTIONS + build_skill_usage_prompt(ctx),
        )

    Args:
        tools: Tool manager to serve to the agent (usually the value returned
            by :func:`create_amrita_tools`).
        memory_backend: Optional memory backend.  Defaults to the same
            in-process backend used for abilities (matching
            ``BackendSlots.default()``).

    Returns:
        ``BackendSlots`` whose ability backend resolves to ``tools``.
    """
    ability = _SkillAbilityBackend(tools)
    return BackendSlots(ability=ability, memory=memory_backend or ability)


def _interpreter_available(script: ScriptMetadata) -> bool:
    """Check whether the script's interpreter is available on this host.

    Uses the same extension→interpreter mapping as faskill's ``ScriptExecutor``
    (``INTERPRETER_MAP``) and probes PATH via ``shutil.which``.

    Returns:
        True when the interpreter exists; False when the runner cannot
        execute this script (unsupported in the current environment).
    """
    from faskill.core.scripts import INTERPRETER_MAP

    interpreter = INTERPRETER_MAP.get(script.path.suffix.lower())
    return bool(interpreter) and shutil.which(interpreter) is not None


def _make_script_handler(
    manager: SkillContext,
    skill_name: str,
    script_name: str,
) -> Any:
    """Create an AmritaCore tool handler that runs a skill script via faskill.

    Handlers follow the AmritaCore contract and return a string:
    - On success (exit_code==0): script stdout.
    - On failure (exit_code!=0): ``{"success": false, "error": ...}`` JSON so
      the model receives a structured, actionable error message.

    Args:
        manager: SkillContext for executing scripts.
        skill_name: Skill name the script belongs to.
        script_name: Script name (without extension).

    Returns:
        Async handler ``(data: dict[str, Any]) -> str``.
    """

    async def invoke_script(data: Dict[str, Any]) -> str:
        """AmritaCore tool handler for script execution."""
        arguments = data.get(_ARGUMENTS_PARAM, {})
        if arguments is None:
            arguments = {}
        if isinstance(arguments, str):
            # Scripts expect structured input; parse the string as a JSON dict, falling back to {"input": <string>} (same convention as the LangChain integration).
            try:
                parsed = json.loads(arguments)
                arguments = parsed if isinstance(parsed, dict) else {"input": arguments}
            except (json.JSONDecodeError, TypeError):
                arguments = {"input": arguments}

        result = await asyncio.to_thread(
            manager.execute_skill_script,
            skill_name,
            script_name,
            arguments,
            None,  # timeout: use manager's default_script_timeout
        )

        if result.exit_code == 0:
            return result.stdout

        error_msg = f"Script failed with exit code {result.exit_code}"
        if result.stderr:
            error_msg += f"\nError: {result.stderr}"
        if result.timeout:
            error_msg += "\n(Script timed out)"
        if result.signal:
            error_msg += f"\n(Killed by signal: {result.signal})"

        return json.dumps({"success": False, "error": error_msg})

    return invoke_script


def _register_skill_scripts(
    skill: Skill,
    manager: SkillContext,
    tools_manager: MultiToolsManager,
) -> list[str]:
    """Register a skill's script tools on a manager; return skipped script names.

    Scripts whose interpreter is unavailable in the current environment are
    skipped (not registered) and their names returned so the caller can tell
    the model to handle them itself.

    Args:
        skill: Skill object with detected scripts.
        manager: SkillContext for executing scripts.
        tools_manager: Manager to register script tools onto.

    Returns:
        Names of scripts that could not be registered (runner unsupported).
    """
    skipped: list[str] = []
    skill_name = skill.metadata.name

    for script in skill.scripts:
        if not _interpreter_available(script):
            skipped.append(script.name)
            continue

        tool_name = script.get_fully_qualified_name(skill_name)
        tool_description = (
            script.description if script.description else f"Execute {script.name} script"
        )
        handler = _make_script_handler(manager, skill_name, script.name)
        schema = _build_arguments_schema(
            name=tool_name,
            description=tool_description,
            parameter_description=(
                "Arguments to pass to the script via stdin as a JSON string"
            ),
        )
        _register_tool(tools_manager, schema, handler)

    return skipped


def _activate_skill_scripts(
    skill_name: str,
    manager: SkillContext,
    tools_manager: MultiToolsManager,
) -> str:
    """Progressive disclosure L3: inject a skill's script tools after activation.

    Called by the skill tool handler once the model has chosen to invoke the
    skill.  Script tools are mixed into the same ``tools_manager`` the skill
    tool lives on.  Scripts the runner cannot execute (missing interpreter)
    are skipped; the returned note tells the model they exist so it can read
    them and decide how to proceed.

    Args:
        skill_name: Name of the skill being activated.
        manager: SkillContext for loading the skill / running scripts.
        tools_manager: Manager to inject script tools into.

    Returns:
        A note string describing skipped scripts, or "" when all registered.
    """
    try:
        skill = manager.load_skill(skill_name)
    except Exception:
        return ""

    skipped = _register_skill_scripts(skill, manager, tools_manager)
    if not skipped:
        return ""

    return (
        "\n\nNote: this skill ships script(s) that cannot be executed in the "
        "current environment (missing interpreter): "
        + ", ".join(skipped)
        + ". Read the script source and decide how to handle the task yourself."
    )


def build_skill_usage_prompt(manager: SkillContext) -> str:
    """Build a system-role prompt snippet guiding the model to use the skills.

    The snippet lists every discovered skill (name + description) and explains
    how to call it (the ``arguments`` string is inserted into the skill
    template via ``$ARGUMENTS``; the tool returns markdown).  Append it to the
    agent's system prompt — e.g. ``create_agent(..., train=...)``:

    .. code-block:: python

        from amrita_core.consts import DEFAULT_INSTRUCTIONS

        train = DEFAULT_INSTRUCTIONS + build_skill_usage_prompt(ctx)
        agent = create_agent(..., train=train)

    Returns an empty string when no skills are discovered, so concatenation
    stays safe.

    Args:
        manager: SkillContext instance with discovered skills.

    Returns:
        A system-role prompt section (may be empty).
    """
    skills = manager.list_skills(include_qualified=False)
    if not skills:
        return ""

    lines = [
        "## Available faskill skills",
        "Call a skill tool when the user's task matches its purpose:",
    ]
    lines.extend(f"- {skill.name}: {skill.description}" for skill in skills)
    lines.append(_SKILL_USAGE_SECTION.strip())
    return "\n".join(lines)


def build_script_usage_prompt(skill: Skill) -> str:
    """Build a system-role prompt snippet guiding the model to use scripts.

    The snippet lists the skill's scripts as ``{skill}__{script}`` tools and
    explains the calling convention (JSON object via stdin; stdout on success,
    structured error JSON on failure).  Append it to the agent's system prompt
    after :func:`register_amrita_script_tools`.

    Returns an empty string when the skill has no scripts.

    Args:
        skill: Skill object with detected scripts (accessed via ``skill.scripts``).

    Returns:
        A system-role prompt section (may be empty).
    """
    scripts = skill.scripts
    if not scripts:
        return ""

    skill_name = skill.metadata.name
    lines = [
        f"## Scripts for skill: {skill_name}",
        "The following script tools are available:",
    ]
    for script in scripts:
        script_name = script.get_fully_qualified_name(skill_name)
        description = script.description or script.name
        lines.append(f"- {script_name}: {description}")
    lines.append(_SCRIPT_USAGE_SECTION.strip())
    return "\n".join(lines)


def create_amrita_tools(
    manager: SkillContext,
    tools_manager: MultiToolsManager | None = None,
    copy: bool = True,
) -> MultiToolsManager:
    """Register discovered skills as AmritaCore tools (progressive disclosure).

    Creates one prompt-based tool per discovered skill (L1 metadata → L2
    content).  Script tools are **not** registered eagerly: when the model
    calls a skill tool, that skill's script tools are injected into the same
    manager on first invocation (L3 activation).  Scripts the runner cannot
    execute (missing interpreter) are skipped and the model is told they exist
    so it can decide how to handle them.

    Tools are mixed into a ``MultiToolsManager`` — by default the global
    ``ToolsManager`` singleton (``AbilityContext.tools`` / ``glb.tools``).  To
    avoid polluting the shared global pool, ``copy=True`` (default) registers
    onto a fresh clone of the target manager and returns the clone; pass
    ``copy=False`` to register directly onto the manager itself.  Handlers
    follow the AmritaCore contract: ``async (data: dict[str, Any]) -> str`` —
    the returned string becomes the tool result the model sees.

    Args:
        manager: SkillContext instance with discovered skills.
        tools_manager: Optional ``MultiToolsManager`` to mix tools into.
            Defaults to the global ``ToolsManager()`` singleton.
        copy: When True (default), register onto a cloned registry and return
            the clone, leaving the original manager untouched.

    Returns:
        The ``MultiToolsManager`` the tools were mixed into (the clone when
        ``copy=True``, else the same instance as ``tools_manager``).

    Raises:
        Various faskill exceptions during tool invocation (bubbled up).

    Example (AmritaCore agent)::

        import asyncio
        from amrita_core import create_agent, minimal_init
        from faskill import create_context
        from faskill.integrations.amcore import (
            build_skill_usage_prompt,
            create_amrita_tools,
        )

        async def main() -> None:
            await minimal_init()

            ctx = create_context(skill_dirs=["./skills"])
            ctx.discover()

            # Registered onto a clone of the global ToolsManager — the global
            # singleton stays clean.  AmritaCore 1.0 resolves tools through the
            # backend, so wire the clone in with create_amrita_backend().
            tools = create_amrita_tools(ctx)
            agent = create_agent(
                ...,
                backend=create_amrita_backend(tools),
                train=DEFAULT_INSTRUCTIONS + build_skill_usage_prompt(ctx),
            )
            chat = agent.get_chatobject("Review the code in main.py")
            async with chat.begin():
                async for msg in chat.io_stream.get_response_generator():
                    print(msg, end="", flush=True)

        asyncio.run(main())
    """
    target: MultiToolsManager = tools_manager if tools_manager is not None else ToolsManager()
    tools: MultiToolsManager = clone_tools_manager(target) if copy else target

    # Get skill metadata list (explicitly not qualified to get SkillMetadata objects)
    skill_metadatas = manager.list_skills(include_qualified=False)

    for skill_metadata in skill_metadatas:
        skill_name = skill_metadata.name

        # CRITICAL: capture the loop value as a default parameter, or every handler would reference the final value (Python late-binding closure).
        async def invoke_skill(
            data: Dict[str, Any],
            _name: str = skill_name,
        ) -> str:
            """AmritaCore tool handler for skill invocation.

            Runs the sync ``invoke_skill`` in a worker thread so the event loop
            stays responsive.  Returns the processed skill content (markdown).
            """
            arguments = data.get(_ARGUMENTS_PARAM, "")
            if arguments is None:
                arguments = ""
            result = await asyncio.to_thread(manager.invoke_skill, _name, arguments)
            # Progressive disclosure L3: the model chose this skill → activate its script tools on the same manager.
            note = _activate_skill_scripts(_name, manager, tools)
            return f"{result}{note}"

        schema = _build_arguments_schema(
            name=skill_name,
            description=skill_metadata.description,
            parameter_description="Arguments to pass to the skill (empty string if none)",
        )
        _register_tool(tools, schema, invoke_skill)

    return tools


def register_amrita_script_tools(
    skill: Skill,
    manager: SkillContext,
    tools_manager: MultiToolsManager | None = None,
    copy: bool = True,
) -> MultiToolsManager:
    """Register all scripts of a skill as AmritaCore tools.

    Each script becomes a tool named ``{skill_name}__{script_name}`` — the same
    fully-qualified format used by the LangChain integration.

    Scripts whose interpreter is unavailable in the current environment are
    skipped (the runner cannot execute them); the caller may surface them to
    the model separately if desired.

    Tools are mixed into a ``MultiToolsManager`` — by default the global
    ``ToolsManager()`` singleton.  ``copy=True`` (default) registers onto a
    fresh clone and returns it, leaving the target manager untouched.

    Args:
        skill: Skill object with detected scripts (accessed via ``skill.scripts``).
        manager: SkillContext instance for executing scripts.
        tools_manager: Optional ``MultiToolsManager`` to mix tools into.
            Defaults to the global ``ToolsManager()`` singleton.
        copy: When True (default), register onto a cloned registry and return
            the clone.

    Returns:
        The ``MultiToolsManager`` the tools were mixed into.

    Example::

        from faskill.integrations.amcore import (
            create_amrita_tools,
            register_amrita_script_tools,
        )

        tools = create_amrita_tools(ctx)
        for skill_meta in ctx.list_skills():
            skill = ctx.load_skill(skill_meta.name)
            if skill.scripts:
                register_amrita_script_tools(skill, ctx, tools_manager=tools)
    """
    target: MultiToolsManager = tools_manager if tools_manager is not None else ToolsManager()
    tools: MultiToolsManager = clone_tools_manager(target) if copy else target

    _register_skill_scripts(skill, manager, tools)

    return tools


__all__ = [
    "build_script_usage_prompt",
    "build_skill_usage_prompt",
    "clone_tools_manager",
    "create_amrita_backend",
    "create_amrita_tools",
    "register_amrita_script_tools",
]
