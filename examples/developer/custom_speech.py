"""One reviewed contract shared by client, Agent and node; no model or transport imports."""

import asyncio
from dataclasses import replace

from pydantic import Field

from wrs_agent.actions import ActionExecutor
from wrs_agent.schemas import Boundary
from wrs_agent.skills import SKILLS, Skill, SkillSpec, SpeakArgs, SpeechState


class GreetArgs(Boundary):
    name: str = Field(min_length=1, max_length=40)
    repeat: int = Field(default=1, ge=1, le=3)


async def console_speak(state, args, stop, progress):
    # Console output only. A real TTS backend must confirm its own playback has stopped.
    for index, character in enumerate(args.text):
        if stop.is_set():
            return False
        print(character, end="", flush=True)
        progress((index + 1) / len(args.text))
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.01)
        except TimeoutError:
            pass
    if stop.is_set():
        return False
    print(flush=True)
    state.completed += 1
    state.last_text = args.text
    return state.last_text == args.text


async def greet(state, args, stop, progress):
    text = " ".join([f"Hello, {args.name}!"] * args.repeat)
    return await console_speak(state, SpeakArgs(text=text), stop, progress)


GREET = Skill(
    spec=SkillSpec(
        name="greet",
        description="Print a greeting through the example speech backend",
        parameters=GreetArgs.model_json_schema(),
        aliases=["问候"],
        tags=["speech"],
        required_capabilities=["greet"],
        resources=["speaker"],
        preconditions=[],
        verification="console_text_complete",
    ),
    arguments=GreetArgs,
    handler=greet,
)


def install_contract():
    # Explicit local code, called before loading configuration in each participating process.
    if "greet" in SKILLS and SKILLS["greet"] != GREET:
        raise ValueError("greet_contract_already_registered")
    SKILLS["greet"] = GREET


def create_node(args, journal):
    if args.role != "tts":
        raise ValueError("example_backend_requires_tts_role")
    return ActionExecutor(
        journal,
        state=SpeechState(),
        backend="console_tts",
        duration=0,
        skills={"speak": replace(SKILLS["speak"], handler=console_speak), "greet": GREET},
        capabilities_extra={
            "robot_controls": False,
            "controller_flush": False,
            "verification": "console_text_complete",
            "stop_scope": "console_character_boundary",
        },
    )
