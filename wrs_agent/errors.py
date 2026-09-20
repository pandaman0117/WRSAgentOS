"""One error payload shared by local exceptions, RPC failures and task results."""

from pydantic import ValidationError

from wrs_agent.schemas import ErrorInfo

_MESSAGES = {
    "provider_not_found": "No execution provider is configured for this skill.",
    "node_unavailable": "The configured node is offline.",
    "node_not_ready": "The node is present but not ready to accept actions.",
    "node_ambiguous": "More than one startup instance claims this node identity.",
    "node_instance_changed": "The execution node startup instance changed.",
    "skill_version_mismatch": "The provider does not implement the required skill version.",
    "skill_not_on_node": "The provider does not implement this skill.",
    "unknown_skill": "This skill has no registered local contract.",
    "invalid_arguments": "Arguments do not satisfy the skill contract.",
    "invalid_request": "The message does not satisfy the request contract.",
    "invalid_reply": "The reply does not satisfy the response contract.",
    "unauthorized": "This caller is not authorized.",
    "request_timeout": "No response was received within the request deadline.",
    "execution_unknown": "The submitted action's execution outcome cannot be confirmed.",
    "resource_busy": "The execution node is already running an action.",
    "internal_error": "The operation failed inside the service.",
}


def error_info(code, **context):
    return ErrorInfo(code=code, message=_MESSAGES.get(code, code.replace("_", " ")), **context)


class AgentError(ValueError):
    """A classified operation failure; inspect error/code instead of parsing str(exc)."""

    def __init__(self, error, **context):
        self.error = error if isinstance(error, ErrorInfo) else error_info(error, **context)
        self.code = self.error.code
        super().__init__(f"{self.code}: {self.error.message}")


def from_exception(exc, *, validation_code="invalid_request", **context):
    if isinstance(exc, AgentError):
        return exc.error.model_copy(
            update={
                key: value
                for key, value in context.items()
                if value is not None and getattr(exc.error, key) is None
            }
        )
    code = (
        "request_timeout"
        if isinstance(exc, TimeoutError)
        else validation_code
        if isinstance(exc, ValidationError)
        else "internal_error"
    )
    # Unknown exceptions and validation errors may include credentials or user input.
    return error_info(code, **context)
