# 识别文本与任务中断

Voice 接收已经识别出来的文本。录音、VAD、ASR 和界面属于输入端，Runtime 管任务，动作节点确认资源是否停止。已提供本地 Qwen ASR 输入适配和循环收音示例；见 [Voice 示例](../examples/voice/README.md)。

## 最小调用

```python
from wrs_agent import launch

with launch() as system:
    receipt = system.send_text("put A in B", input_id="utterance-001")
    if receipt.accepted and receipt.request_id:
        planned = system.planning(receipt.request_id).wait()
        if planned.task:
            print(planned.task.wait().state)
```

执行中停止并等待结束的独立示例：

```powershell
./scripts/run.ps1 examples/voice/01_text_stop_task.py
```

已有服务时使用 `connect()`；异步程序使用 `System.connect()` 和 `await system.send_text(...)`。客户端与服务共享 `WRS_AGENT_TOKEN`，默认只有受信本机入口。confidence 或文本里的角色说明不授予权限。

## 输入与回执

`send_text(text, *, input_id=None, is_final=True, confidence=1.0)` 构造 `TextInput`。text 最长 1024 字符；input_id 不传则生成新编号。ASR 应为每句输入分配稳定编号，置信度字段在 0 到 1 之间。

| TextReceipt 字段 | 含义 |
|---|---|
| `input_id` | 本次输入编号，用于重试核对 |
| `disposition` | ignore / clarify / query / goal / stop / cancel_tts |
| `accepted` | 是否已受理相应操作；不是执行成功证明 |
| `reason` | 忽略或需要确认的原因码 |
| `request_id` | goal 受理后可通过 `system.planning(id)` 查询规划 |
| `task_id` | 查询或停止实际绑定的任务；可能为空 |
| `phase` | 控制回执 STOPPING / STOPPED / UNKNOWN；其他输入为空 |
| `overview` | query 的 Runtime 总览，仍是现有字典合同 |
| `error` | 可选结构化 ErrorInfo；传输/参数等错误也可能抛 AgentError |

`system.planning(id)` 与 `system.task(id)` 只创建查询句柄，不会重复规划或启动任务。Runtime 重启后旧 ID 不存在。句柄等待超时、停止观察和连接客户端退出均不自动取消远端执行；拥有进程的 `launch()` 退出会清理自己启动的服务。

## 当前支持哪些文本

本地规则是可检查的小词表，位于 `wrs_agent/policy.py`，并非通用语言理解器。

| 输入示例 | 当前行为 |
|---|---|
| `停止`、`暂停`、`stop` | 走独立控制入口，停止当前任务并使待返回规划失效 |
| `停，改放到 C` | 先停止；后半句不自动转成新动作，提示取消结束后显式提交新任务 |
| `停止播报`、`别说了` | 只取消当前 TTS 动作，不撤销机器人权限 |
| `做到哪一步了`、`状态` | 查询 Runtime，不调用模型 |
| `嗯`、`好的` | 忽略，不打断 |
| `不要停止`、引用中的停止、不明确的取消 | clarify，不推测控制意图 |
| 未完成识别或低于 0.9 的置信度 | ignore / clarify，不开始动作 |
| `改放到 C`、`完成后再……` | clarify；修改目标需先取消并确认结束，再 start；追加使用显式 enqueue |
| 其他完整文本 | 提交 Planner；是否产生任务由规划和 Runtime 校验决定 |

Mock Planner 只识别严格转移模板（如 `put A in B`）与明确的 home/回原位指令；其余返回 CLARIFY。GLM 使用同一后续校验，不负责签发执行权限。VAD 表示检测到声音，不等于停止指令。

## 停止到底做什么

调用链：

```text
ASR / UI -> system.send_text -> Voice 本地规则
  查询       -> Runtime 总览
  普通目标   -> GoalRequest -> Planner -> 校验 -> Task -> 动作节点
  明确停止   -> Runtime interrupt -> 绑定当前任务 -> 参与节点 hold/cancel
  停止播报   -> TTS cancel
```

Runtime 接到 interrupt 时，在等待网络之前绑定当前任务，停止后续派发，使进行中的规划失效，清空尚未执行的追加队列。控制只覆盖该任务参与的资源，不要求无关节点在线。

回执 STOPPING 仅表示 Runtime 受理取消。任务进入 CANCELLING，独立等待参与资源停止及原动作结果，确认后为 CANCELLED；无法确认则 UNKNOWN。先用 `task.wait()` 确认旧任务已结束，再根据当前状态 `system.start(*steps)` 创建独立任务。没有 task.replace 或自动续跑。完整语义见 [任务句柄](task_handles.md)。

Runtime 当前没有活动任务时，先撤销待返回规划，再向 WRS 发送 hold，覆盖绕过 Runtime 的直接机器人动作。它不会自动取消独立 TTS 动作；需要时使用“停止播报”。如果 Agent 不可达，Voice 等待该控制 RPC 最多 0.5 秒后尝试直接停止机器人，但回执保持 accepted=false、UNKNOWN，因为无法确认任务其他资源。0.5 秒是请求超时配置，不是停止延迟保证。

`system.replay("stop")` 保留既有调试语义，只直接 hold WRS。新 ASR/UI 接入使用 `send_text`；UI 已持有明确任务 ID 时优先使用该任务的 `cancel()`，避免“当前任务”随时间变化带来的用户理解问题。语音控制不是硬件急停。

## 重复、丢回复与重启

- 部分识别 `is_final=False` 不消耗去重编号；最终文本可沿用同一句的 input_id。
- 最终输入一旦提交，重试必须使用相同 input_id、文本、置信度和其他参数。并发重复共享处理中结果；相同 ID 不同内容会拒绝。
- 成功处理的停止输入不会因重发而停止后来的新任务。Runtime 同样保留该 interrupt ID 对应的原目标。
- 状态查询失败后可再次查询；节点控制请求一旦构造，重试保持原编号、实例、epoch 和参数。结果不明不记作成功。
- Voice 的识别/回放共用有界 4096 项会话记录，满时拒绝新增，不静默删除去重历史。Runtime 的任务、规划和请求也有既有容量限制。
- Voice/Runtime 重启不是跨重启的 exactly-once 保证。不要把旧输入录音或日志自动重播成新控制；先重新连接、查询当前状态，再让操作者表达新意图。

通知事件只发送输入编号、分类和受理/控制阶段；不会把识别文本或音频加入该事件。文本会留在会话内存的去重记录中，成为动作参数的内容还可能进入现有动作日志；输入端应自行制定真实音频的保留策略。

## 给 ASR 与 UI 开发者

ASR 第一版只需要把一句已完成的识别交给 `send_text`，保持 input_id 稳定。部分识别可以仅在界面显示。音频线程回调不能阻塞等待网络，也不能直接操作 asyncio.Queue；使用线程安全桥接和有界队列，在所属事件循环提交完整文本。控制输入不能采用观测帧的丢旧保新策略。暂不增加流式音频协议或逐帧任务。

UI 展示 disposition、accepted、phase、task_id 和 error.code。UNKNOWN 展示为需要核实，不显示“已停止”。任务进度来自 `task.watch()`，当前是有界轮询，不保证每个瞬时进度。UI 不应因关闭进度窗口而调用 cancel。

底层 v4 端点是 Voice 的 `request/voice/text`、控制通道的 `request/voice/control_text`，以及 Agent 控制通道的 `request/task/interrupt`。服务端会重新检查控制意图，不能通过选择通道绕过规则；普通调用者使用 System API 即可。

验收入口：`tests/unit/test_text_input.py`、`tests/integration/test_voice_text.py`。真实 ASR、播音完成/停止、嘈杂环境准确率和端到端延迟需要另行验证。

## Qwen 中文输入适配

已增加可选本地 `wrs_agent/speech/asr.py` 和完整 WRS 语音例子；麦克风及推理在输入客户端，Voice 仍消费已识别的文本。控制与固定方向命令的调用链、安装和局限见 [Qwen 语音指南](QWEN_SPEECH.md)。默认测试不会录音、下载模型或播放音频。
