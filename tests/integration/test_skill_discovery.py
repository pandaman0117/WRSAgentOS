"""Real Zenoh discovery: only the owner registers skills, including dynamic additions."""

import asyncio

import pytest
from conftest import eventually
from pydantic import Field, model_validator

from wrs_agent import AgentError, System, step
from wrs_agent.executor import ActionExecutor
from wrs_agent.nodes import Node
from wrs_agent.nodes.agent import AgentNode
from wrs_agent.nodes.serve import serve_node
from wrs_agent.nodes.tts.backend import SpeechState
from wrs_agent.processes import LocalStack
from wrs_agent.schemas import Boundary, Empty
from wrs_agent.skills import Skill


class PairArgs(Boundary):
    x: int = Field(ge=0, le=10)
    y: int = Field(ge=0, le=10)

    @model_validator(mode="after")
    def combined_limit(self):
        if self.x + self.y > 10:
            raise ValueError("combined_limit")
        return self


def defined(name, arguments=Empty, version=1):
    return Skill(
        name=name,
        version=version,
        description="Reviewed test skill",
        resources=["speaker"],
        preconditions=[],
        verification="console_state",
        arguments=arguments,
    )


def record(state, args, stop, progress):
    state.completed += 1
    return True


@pytest.mark.zenoh
async def test_dynamic_skill_is_discovered_preflighted_and_bound_without_client_registration(
    tmp_path, monkeypatch,
):
    config = tmp_path / "nodes.toml"
    config.write_text(
        '[nodes.first]\ntype="custom"\nsuffix="-first"\nactions=true\nenabled=true\n'
        '[nodes.second]\ntype="custom"\nsuffix="-second"\nactions=true\nenabled=true\n'
        '[nodes.agent]\ntype="agent"\nsuffix="-agent"\nactions=false\nenabled=true\n',
        encoding="utf-8",
    )
    owners = {}
    entered, release = asyncio.Event(), asyncio.Event()

    class LocalNode(Node):
        async def setup(self):
            self.actions(ActionExecutor(
                self.journal, state=SpeechState(), backend="test",
                features_extra={"robot_controls": False, "controller_flush": False},
            ))
            # Same public method here and after startup.
            self.add_skills(defined(self.node_id + "_seed").bind(record))
            owners[self.node_id] = self

    async def slow(state, args, stop, progress):
        entered.set()
        while not release.is_set():
            if stop.is_set():
                return False
            try:
                await asyncio.wait_for(release.wait(), 0.02)
            except TimeoutError:
                pass
        return record(state, args, stop, progress)

    async with LocalStack(bindings="configs/tts.toml", duration=0.01) as stack:
        monkeypatch.setenv("WRS_AGENT_TOKEN", stack.token)
        env_id = stack.env_id + "-skills"
        common = dict(
            bindings=config, endpoint=stack.endpoint, site=stack.site, env_id=env_id,
        )
        workers = [
            asyncio.create_task(serve_node(
                cls, node_id=name, journal=tmp_path / f"{name}.db", **common,
            ))
            for name, cls in (("first", LocalNode), ("second", LocalNode), ("agent", AgentNode))
        ]
        try:
            async with System.connect(
                stack.endpoint, bindings=config, site=stack.site, env_id=env_id,
                _token=stack.token,
            ) as client:
                await eventually(
                    client.nodes,
                    lambda rows: all(
                        rows.get(name, {}).get("ready") for name in ("first", "second", "agent")
                    ),
                )
                assert {s.name for s in await client.skills()} == {"first_seed", "second_seed"}
                first, second = owners["first"], owners["second"]
                before = first.executor.features()
                pair = defined("pair", PairArgs, version=2).bind(record)
                first.add_skills(pair, defined("slow").bind(slow), *(
                    defined(f"extra{i}").bind(record) for i in range(9)
                ))
                specs = {s.name: s for s in await client.skills()}
                assert len(specs) == 13 and specs["pair"].version == 2
                assert first.executor.boot_id == before.boot_id
                assert first.executor.skill_revision == before.skill_revision + 1
                action = await client.action("pair", x=3, y=4)
                assert action.request.version == 2 and (await action.wait()).state == "SUCCEEDED"

                # Both scalar fields satisfy JSON Schema. The owner-only Python validator
                # rejects their combination before even the first, valid step can run.
                seed = step("first_seed")
                invalid = await client.start(seed, step("pair", x=6, y=6, after=seed))
                result = await invalid.wait()
                assert result.state == "FAILED" and result.error.code == "invalid_arguments"
                assert result.error.node_id == "first"
                assert first.executor.executions == 1 and second.executor.executions == 0

                seed = step("slow")
                running = await client.start(seed, step("pair", x=1, y=2, after=seed))
                await asyncio.wait_for(entered.wait(), 3)
                second.add_skills(pair)
                first.add_skills(defined("later").bind(record))
                # Refresh sees the conflict; the already resolved task retains its owner.
                assert "pair" not in {s.name for s in await client.skills()}
                with pytest.raises(AgentError, match="skill_provider_ambiguous"):
                    await client.action("pair", x=1, y=2)
                release.set()
                assert (await running.wait()).state == "SUCCEEDED"
                assert first.executor.executions == 3 and second.executor.executions == 0

                pinned = tmp_path / "pinned.toml"
                pinned.write_text(
                    config.read_text(encoding="utf-8") + '\n[skills]\npair="first"\n',
                    encoding="utf-8",
                )
                async with System.connect(
                    stack.endpoint, bindings=pinned, site=stack.site, env_id=env_id,
                    _token=stack.token,
                ) as selected:
                    action = await selected.action("pair", x=0, y=1)
                    assert (await action.wait()).state == "SUCCEEDED"
                    await client._transports["first"].request(
                        "request/node/first/shutdown", {}, control=True,
                    )
                    await workers[0]
                    await eventually(
                        selected.nodes, lambda rows: rows["first"]["health"] == "offline",
                    )
                    with pytest.raises(AgentError, match="node_unavailable"):
                        await selected.action("pair", x=1, y=1)
                    assert second.executor.executions == 0
                with pytest.raises(AgentError, match="skill_provider_ambiguous"):
                    await client.action("pair", x=1, y=1)
        finally:
            release.set()
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
