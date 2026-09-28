import asyncio

import pytest
from conftest import eventually

from wrs_agent import AgentError, System, step
from wrs_agent.processes import LocalStack, python_command
from wrs_agent.schemas import ActionRequest
from wrs_agent.transport import RemoteError, Transport

pytestmark = pytest.mark.zenoh


async def test_incompatible_restarted_node_blocks_plan_and_retains_error_for_reconnect():
    async with LocalStack(duration=0.02) as stack:
        system = stack.system
        before = (await system.nodes())["tts"]["boot_id"]
        tts = system.clients["tts"]
        worker = stack.processes[2]
        await tts.transport.request("request/node/tts/shutdown", {}, control=True)
        await asyncio.to_thread(worker.wait, timeout=3)
        stack.processes.remove(worker)
        stack._spawn(
            "tts-v2",
            python_command(
                "tests/fixtures/versioned_tts.py",
                "tts",
                "--endpoint",
                stack.endpoint,
                "--site",
                stack.site,
                "--env-id",
                stack.env_id,
                "--journal",
                stack.directory / "tts-v2.sqlite3",
                "--duration",
                "0.02",
            ),
        )
        await stack._wait_ready("tts")
        view = await eventually(
            system.nodes,
            lambda rows: rows["tts"]["ready"] and rows["tts"]["boot_id"] != before,
        )
        assert view["tts"]["skills"] == {"speak": 2}
        assert (await tts.features()).skills == {"speak": 2}
        assert next(s for s in await system.skills() if s.name == "speak").version == 2
        task = await system.start(
            step("move_named_pose", pose="B"),
            step("speak", text="must not run").model_copy(update={"version": 1})
        )
        result = await task.wait()
        assert result.state == "FAILED"
        assert result.error.code == "skill_version_mismatch"
        assert result.error.node_id == "tts" and result.error.task_id == task.id
        assert result.error.stage == "preflight" and result.error.action_id is None
        for node in system.clients.values():
            assert (await node.transport.request("request/health", {}))["executions"] == 0
        async with System.connect(
            stack.endpoint, site=stack.site, env_id=stack.env_id, _token=stack.token
        ) as reconnected:
            assert (await reconnected.task(task.id).status()).error == result.error
        # A mismatch on an unused resource must not block a new robot-only task.
        independent = await system.start(step("move_named_pose", pose="B"))
        assert (await independent.wait()).state == "SUCCEEDED"
        inferred = await system.action("speak", text="use discovered version")
        assert inferred.request.version == 2
        assert (await inferred.wait()).state == "SUCCEEDED"


async def test_structured_rpc_errors_keep_identity_without_exposing_exception_inputs():
    async with LocalStack(bindings="configs/tts.toml", duration=0.02) as stack:
        server = stack.system.clients["tts"].transport
        server.node_id = "tts"

        async def reject(payload):
            raise AgentError(
                "resource_busy", node_id="tts", task_id="task", action_id="action", stage="submit"
            )

        async def invalid(payload):
            return ActionRequest.model_validate(payload).model_dump()

        async def internal(payload):
            raise RuntimeError("private-test-value")

        server.register_handler("request/test/reject", reject)
        server.register_handler("request/test/invalid", invalid)
        server.register_handler("request/test/internal", internal)
        caller = Transport(stack.endpoint, stack.site, server.env_id, stack.token, "error-test")
        unauthenticated = Transport(
            stack.endpoint, stack.site, server.env_id, "wrong-test-token-value", "bad-auth-test"
        )
        try:
            with pytest.raises(RemoteError) as caught:
                await caller.request("request/test/reject", {})
            error = caught.value.error
            assert (error.code, error.stage, error.node_id, error.task_id, error.action_id) == (
                "resource_busy",
                "submit",
                "tts",
                "task",
                "action",
            )
            for method, code in [("invalid", "invalid_request"), ("internal", "internal_error")]:
                with pytest.raises(RemoteError) as caught:
                    await caller.request(f"request/test/{method}", {"text": "private-test-value"})
                assert caught.value.code == code and caught.value.error.node_id == "tts"
                assert "private-test-value" not in str(caught.value.error.model_dump())
            with pytest.raises(RemoteError) as caught:
                await unauthenticated.request("request/features", {})
            assert caught.value.code == "unauthorized" and caught.value.error.node_id == "tts"
        finally:
            await caller.close()
            await unauthenticated.close()
