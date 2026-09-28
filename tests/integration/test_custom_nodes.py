"""Custom Node classes share lifecycle semantics without claiming a built-in role."""

import asyncio

import pytest
from conftest import eventually

from wrs_agent import System
from wrs_agent.nodes import Node
from wrs_agent.nodes.serve import serve_node
from wrs_agent.processes import LocalStack
from wrs_agent.schemas import Boundary, Empty


class QueryOptions(Boundary):
    label: str


class QueryNode(Node):
    options_type = QueryOptions
    features = ("query.label",)

    async def setup(self):
        async def label(payload):
            Empty.model_validate(payload)
            return {"label": self.options.label}

        self.transport.register_handler(f"request/node/{self.node_id}/label", label)


@pytest.mark.zenoh
async def test_custom_nodes_have_independent_identity_and_shutdown(tmp_path, monkeypatch):
    config = tmp_path / "custom.toml"
    config.write_text(
        '[nodes.first]\ntype="custom"\nsuffix="-custom"\nactions=false\nenabled=true\n'
        '[nodes.second]\ntype="custom"\nsuffix="-custom"\nactions=false\nenabled=true\n'
        '[skills]\n',
        encoding="utf-8",
    )
    # Own a real loopback Router; this test never invokes the offline TTS worker.
    async with LocalStack(bindings="configs/tts.toml") as stack:
        monkeypatch.setenv("WRS_AGENT_TOKEN", stack.token)
        env_id = stack.env_id + "-custom"
        common = dict(bindings=config, endpoint=stack.endpoint, env_id=env_id)
        workers = [
            asyncio.create_task(serve_node(
                QueryNode, node_id=name, options={"label": name}, **common,
            ))
            for name in ("first", "second")
        ]
        # Node servers read the credential from the environment, just like standalone scripts.
        try:
            async with System.connect(
                stack.endpoint, env_id=env_id, bindings=config, _token=stack.token,
            ) as client:
                nodes = await eventually(
                    client.nodes,
                    lambda rows: all(
                        rows.get(name, {}).get("ready") for name in ("first", "second")
                    ),
                )
                assert set(nodes) == {"first", "second"}
                assert nodes["first"]["boot_id"] != nodes["second"]["boot_id"]
                assert all(node["node_type"] == "custom" for node in nodes.values())
                assert all(node["features"] == ["query.label"] for node in nodes.values())
                for name in nodes:
                    bus = client._transports[name]
                    reply = await bus.request(f"request/node/{name}/label", {})
                    assert reply == {"label": name}
                await client._transports["first"].request(
                    "request/node/first/shutdown", {}, control=True,
                )
                await workers[0]
                nodes = await eventually(
                    client.nodes,
                    lambda nodes: (
                        nodes["first"]["health"] == "offline" and nodes["second"]["ready"]
                    ),
                )
                assert not workers[1].done()
                assert await client._transports["second"].request(
                    "request/node/second/label", {},
                ) == {"label": "second"}
                await client._transports["second"].request(
                    "request/node/second/shutdown", {}, control=True,
                )
                await workers[1]
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
