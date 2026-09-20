"""Run a custom skill across real node/Agent processes; optionally serve or connect."""

import argparse
import asyncio
from pathlib import Path

from examples.developer.custom_speech import install_contract
from wrs_agent import AgentError, System, step
from wrs_agent.processes import LocalStack

DIRECTORY = Path(__file__).resolve().parent
CONFIG = DIRECTORY / "custom_speech.toml"
NODE = DIRECTORY / "04_custom_node.py"


class DemoStack(LocalStack):
    """Example supervisor only: choose a known local entry script, no plugin discovery."""

    def node_command(self, role):
        command = super().node_command(role)
        index = command.index("-m")
        command[index : index + 2] = [str(NODE)]
        return command


async def exercise(system):
    nodes = await system.nodes()
    completed = (await system.snapshot("speaker")).data.completed
    assert nodes["speaker"]["skills"] == {"greet": 1, "speak": 1}
    try:
        await system.action("greet", name="student", repeat=99)
    except AgentError as exc:
        assert exc.code == "invalid_arguments"
    else:
        raise AssertionError("invalid skill arguments were accepted")
    greeting = await system.action("greet", name="student", repeat=2)
    assert (await greeting.wait()).state == "SUCCEEDED"
    # The Agent imports the same contract; Runtime scheduling needs no custom branch.
    task = await system.start(step("greet", name="team"))
    assert (await task.wait()).state == "SUCCEEDED"
    long_action = await system.action("speak", text="cancellable console output " * 12)
    assert (await long_action.cancel()).accepted
    assert (await long_action.wait()).state == "CANCELLED"
    assert (await system.snapshot("speaker")).data.completed == completed + 2
    print("PASS: custom node + one shared Skill contract + direct action + Runtime + cancel")


async def run(args):
    install_contract()
    if args.connect:
        async with System.connect(
            f"tcp/127.0.0.1:{args.port or 7447}", env_id=args.env_id, bindings=CONFIG
        ) as system:
            await exercise(system)
    else:
        async with DemoStack(
            bindings=CONFIG, port=args.port or (7447 if args.serve else 0), env_id=args.env_id
        ) as stack:
            if args.serve:
                print(
                    f"ready custom nodes: {stack.endpoint} {stack.env_id}; Ctrl+C to stop",
                    flush=True,
                )
                await asyncio.Event().wait()
            else:
                await exercise(stack.system)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--connect", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--env-id", default=None)
    args = parser.parse_args()
    if args.serve or args.connect:
        args.env_id = args.env_id or "custom-demo"
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
