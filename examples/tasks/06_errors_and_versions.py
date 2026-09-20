"""Inspect contract versions and handle a task failure without parsing error strings."""

from wrs_agent import AgentError, launch, step


def main():
    with launch(duration=0.05) as system:
        print("TTS contracts:", system.nodes()["tts"]["skills"])  # {'speak': 1}

        # The object has not been moved to B, so verification fails explicitly.
        task = system.start(step("verify", object="A", target="B"))
        result = task.wait()
        assert result.state == "FAILED" and result.error.code == "action_failed"
        assert system.snapshot().data.pose == "home"
        print(result.state, result.error.code, result.error.stage, result.error.node_id)

        # A direct action refusal carries the same error data in AgentError.
        try:
            system.action("speak", text=123)
        except AgentError as exc:
            assert exc.code == "invalid_arguments"
            print(exc.error.code, exc.error.stage, exc.error.node_id)

        valid = system.start(step("speak", text="Corrected request"))
        assert valid.wait().state == "SUCCEEDED"


if __name__ == "__main__":
    main()
