模型协议回归测试数据，仅由 tests 使用；在线模型示例不读取这些文件，也不会在网络失败时回退到固定响应。

三份文件分别对应 `LLM_PROTOCOL` 的三种取值，按各厂商公开文档的响应结构手写，不是真实服务录制，不能作为某个账号或模型可用的证据：

- `openai_chat_tool_call.json`：Chat Completions 的 `tool_calls`（GLM、DeepSeek、Qwen、vLLM 等兼容服务同形）。
- `openai_responses_function_call.json`：OpenAI Responses 的 `function_call` 输出项。
- `anthropic_tool_use.json`：Anthropic Messages 的 `tool_use` 内容块。
