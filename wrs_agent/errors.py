"""One error payload shared by local exceptions, RPC failures and task results."""

from pydantic import ValidationError

from wrs_agent.schemas import ErrorInfo

_MESSAGES = {
    "glm_thinking_invalid": (
        "GLM_THINKING 应为 off/low/high/max；留空则由账号模型自行决定思考深度。"
        "off 关闭思考，GLM-5.3 不接受，该模型最省时的档位是 low。"
    ),
    "glm_http_400": (
        "GLM 拒绝了请求参数。若与思考深度有关，请改用 GLM_THINKING=low："
        "厂商文档称 GLM-5.3 系列不接受关闭思考，实际是否接受由服务端和端点决定。"
    ),
    "glm_dns_error": "无法解析智谱服务域名。请检查 DNS、网络和代理设置。",
    "glm_tls_certificate_error": "HTTPS 证书校验失败。请检查系统时间、证书和 HTTPS 代理配置。",
    "glm_tls_error": "TLS 握手中断。请检查代理路由或 HTTPS 拦截配置。",
    "glm_proxy_error": "代理连接失败。请检查代理是否运行及其地址和端口。",
    "glm_connect_error": "无法建立智谱服务连接。请检查网络、代理和防火墙。",
    "glm_protocol_error": "智谱服务或代理未返回完整的 HTTP 响应。",
    "glm_transport_error": "GLM 网络传输失败。可运行 scripts/check_glm_connection.py 排查。",
    "glm_timeout": "GLM 请求超时。请检查网络或稍后重试。",
    "glm_model_missing": (
        "Set GLM_MODEL to a model ID enabled for your account. "
        "GLM_API_KEY and GLM_BASE_URL do not select a model. "
        "If using .env, configure this IDE run configuration to load that file."
    ),
    "glm_model_invalid": (
        "GLM_MODEL must be a model ID of 1 to 128 letters, digits, dots, underscores or hyphens."
    ),
    "glm_base_url_invalid": (
        "GLM_BASE_URL must be a supported GLM endpoint; see .env.example."
    ),
    "glm_api_key_missing_or_invalid": (
        "Set GLM_API_KEY to your API key without whitespace. "
        "If using .env, configure this IDE run configuration to load that file."
    ),
    # unordered_resource_conflict 不在这张表里：它的正文要点名是哪两个步骤和哪个资源，
    # 由 runtime.require_ordered_resources 就地构造，否则这里的通用句会盖掉那些名字。
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
    "relative_target_unreachable": "No nearby joint-limit-valid IK solution for this offset.",
    "resource_busy": "The execution node is already running an action.",
    "asr_busy": "This microphone is already capturing another push-to-talk session.",
    "asr_press_finished": "This push-to-talk session already ended; start a new one.",
    "asr_press_not_found": "No push-to-talk session is active with this ID.",
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
