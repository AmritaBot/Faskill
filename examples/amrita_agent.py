#!/usr/bin/env python3
"""AmritaCore agent integration example for faskill library.

This script demonstrates how to register discovered skills as AmritaCore
tools and use them with an AmritaCore agent.

Requirements:
    pip install faskill[amrita]
"""

import asyncio
import logging
import os
from pathlib import Path

from faskill import SkillContext

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")


def main() -> None:
    """Demonstrate AmritaCore agent integration."""
    print("=" * 60)
    print("faskill: AmritaCore Agent Integration Example")
    print("=" * 60)

    # Check for AmritaCore availability
    try:
        from amrita_core.config import AmritaConfig, set_config

        from faskill.integrations.amcore import (
            build_skill_usage_prompt,
            create_amrita_tools,
        )
    except ImportError as e:
        print(f"\nError: {e}")
        print("\nInstall AmritaCore integration with:")
        print("  pip install faskill[amrita]")
        return

    # AmritaCore requires a global config (builtin tools call get_config())
    set_config(AmritaConfig())

    # Use example skills from examples/skills/ directory
    skills_dir = Path(__file__).parent / "skills"
    print(f"\nUsing skills directory: {skills_dir}")

    # Create skill manager and discover skills
    print("\n[1] Discovering skills...")
    manager = SkillContext(skill_dirs=[skills_dir])
    manager.discover()

    print(f"\nFound {len(manager.list_skills())} skills")

    # Mix skills into AmritaCore tools.  By default (copy=True) they are
    # registered onto a fresh clone of the global ToolsManager() singleton, so
    # the global pool stays clean and we get our own per-session tool pool.
    # Pass copy=False to mix directly into the global ToolsManager() instead.
    print("\n[2] Mixing skills into AmritaCore tools (cloned tool pool)...")
    tools = create_amrita_tools(manager)

    print(f"Registered {len(tools.get_tools())} skill tools:")
    for name in tools.get_tools():
        meta = tools.get_tool_meta(name)
        print(f"  - {name}: {meta.function.description[:60]}...")

    # Progressive disclosure L3: script tools are NOT registered eagerly.
    # When the model invokes a skill tool (below), that skill's script tools
    # are injected into the same tools manager automatically.
    print("\n[3] Script tools are injected on skill activation (L3)...")
    script_names = [n for n in tools.get_tools() if "__" in n]
    print(f"  Script tools before activation: {len(script_names)}")

    # Demonstrate tool invocation (also activates the skill's script tools)
    print("\n[4] Testing skill tool invocation...")
    skill_names = [meta.name for meta in manager.list_skills()]
    if skill_names:
        test_name = skill_names[0]
        test_func = tools.get_tool_func(test_name)
        print(f"\nInvoking tool: {test_name}")
        try:
            result = asyncio.run(
                test_func({"arguments": "Review this Python function for security issues"})
            )
            print(f"\nResult preview (first 200 chars):\n{'-' * 60}")
            print(result[:200])
            print("..." if len(result) > 200 else "")
            print("-" * 60)
        except Exception as e:
            print(f"Error: {e}")

    # Demonstrate script tool injection after activation
    print("\n[4.5] Testing script tool invocation (injected after activation)...")
    script_tools = [name for name in tools.get_tools() if "__" in name]
    print(f"  Script tools after activation: {len(script_tools)}")
    if script_tools:
        test_script = script_tools[0]
        test_func = tools.get_tool_func(test_script)
        print(f"\nInvoking script tool: {test_script}")
        try:
            result = asyncio.run(test_func({"arguments": "{}"}))
            print(f"\nScript result preview (first 200 chars):\n{'-' * 60}")
            print(result[:200])
            print("..." if len(result) > 200 else "")
            print("-" * 60)
        except Exception as e:
            print(f"Info: {e}")
            print("(This is expected if the example script doesn't exist)")
    else:
        print("\nNo script-based tools found (no scripts activated yet)")
        print("Script tools are injected when the model calls a skill tool")

    # Example agent setup (requires API key)
    print("\n[5] Agent setup example (requires API key)...")
    if not os.environ.get("OPENAI_API_KEY"):
        print("  SKIP: OPENAI_API_KEY not set. Set it to run the agent.")
        return

    print("  Creating agent with AmritaCore...")
    try:
        from amrita_core import create_agent, minimal_init
        from amrita_core.consts import DEFAULT_INSTRUCTIONS

        # Build a system-role prompt snippet that tells the model how to use
        # the registered skill tools (kept out of tool descriptions)
        system_prompt = DEFAULT_INSTRUCTIONS + build_skill_usage_prompt(manager)

        async def _run_agent() -> None:
            await minimal_init()
            agent = create_agent(
                base_url="https://api.openai.com/v1",
                api_key=os.environ["OPENAI_API_KEY"],
                model="gpt-4o-mini",
                tools_manager=tools,
                train=system_prompt,
            )
            chat = agent.get_chatobject("Review the code in main.py")
            async with chat.begin():
                async for msg in chat.io_stream.get_response_generator():
                    print(msg, end="", flush=True)
            print()

        asyncio.run(_run_agent())
        print("Agent completed.")
    except Exception as e:
        print(f"  Agent setup failed: {e}")


if __name__ == "__main__":
    main()
