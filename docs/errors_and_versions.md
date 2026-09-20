# 错误与技能合同版本

普通调用仍然是 `system.action(...)` 和 `system.start(...)`。这次增加的是失败原因和合同检查，不增加调度服务或启动参数。

## 使用错误数据

调用未被接收时抛出 `AgentError`；已经返回句柄的动作或任务，通过结果的 `error` 读取失败信息。成功结果的 `error` 为 `None`。

```python
from wrs_agent import AgentError, launch, step

with launch() as system:
    try:
        system.action("speak", text=123)  # 参数不满足合同
    except AgentError as exc:
        print(exc.error.code, exc.error.stage, exc.error.node_id)

    task = system.start(step("verify", object="A", target="B"))
    result = task.wait()
    if result.error is not None:
        print(result.state, result.error.code, result.error.action_id)
```

完整可运行示例：`./scripts/run.ps1 examples/tasks/06_errors_and_versions.py`。
同步和异步 API 使用同一错误类型。`RemoteError` 和 `AgentError` 共享 `ErrorInfo`，后者仍继承 `ValueError`。

| 字段 | 含义 |
|---|---|
| `code` | 供程序判断的错误码，不解析异常字符串 |
| `message` | 简短说明，不包含原始异常、凭据或完整验证输入 |
| `stage` | discovery / preflight / submit / observe / control / planning；没有明确阶段时为空 |
| `node_id` | 发生错误的节点，或返回该错误的服务节点；尚未选择时可能为空 |
| `task_id` | 已确定的任务身份；请求尚未受理时可能为空 |
| `action_id` | 已构造的动作身份；整体预检失败时为空 |

`action_id` 非空只代表请求身份已确定，不代表节点已经接受或执行。`reason` 保留已有描述及恢复依据；新调用方优先检查 `error.code`。
任务句柄返回类型化的 `TaskStatus`；`system.status()` 总览和 `system.nodes()` 仍是字典，错误字段也是序列化的同一合同。

| 常见错误码 | 意义 |
|---|---|
| `provider_not_found` | 未为该技能配置执行者 |
| `node_unavailable` | 配置中的节点离线 |
| `node_not_ready` | 节点在线，但尚未开放动作准入 |
| `node_ambiguous` | 多个启动实例声明相同节点身份 |
| `node_instance_changed` | 任务绑定的节点启动实例发生变化 |
| `skill_version_mismatch` | 本地技能合同或节点声明版本不匹配 |
| `skill_not_on_node` / `unknown_skill` | 执行节点没有实现 / 本地没有注册该技能 |
| `invalid_arguments` / `invalid_request` | 技能参数 / 消息结构校验失败 |
| `unauthorized` | 调用身份不被接受 |
| `task_busy` | 当前任务仍在执行、取消中或结果未知，不能开始另一项任务 |
| `resource_busy` | 节点已有冲突动作；不会停止占用者 |
| `request_timeout` | 本次请求没有按时得到回复 |
| `action_failed` | 动作明确失败；可结合动作的 reason / verification 查看依据 |
| `execution_unknown` | 已提交动作的执行结果无法确认 |

提交前的能力、状态或 context 查询失败，任务为 `FAILED`，没有动作身份，不按已执行处理。提交后丢失回执时，客户端只按原 action_id 查询；能查到就继续观察，查不到或查询失败才报告 `execution_unknown`。Runtime 将这类任务记为 `UNKNOWN`，只对相关资源请求控制，不盲目重发动作。

单独查询超时不等于远端执行失败。`wait/watch` 的观察期限到达仍抛出 `TimeoutError`，不会取消远端任务；停止必须显式调用 `task.cancel()` 或 `action.cancel()`。控制回执的 `accepted`、`phase` 继续区分请求受理与已经停止，`STOPPING` 不等于 `STOPPED`。

## 只有一份技能参数合同

- Skill Registry 的 `Skill(spec, arguments, handler)` 定义技能含义；参数 Schema 从 `arguments` 生成。
- Node Registry 的 `skills={"speak": 1}` 声明当前实例实现的合同，不维护另一份参数说明。
- TOML 的技能绑定决定本系统允许交给哪个节点执行。

查询示例：`system.nodes()["tts"]["skills"]` 返回 `{"speak": 1}`。`system.skills()` 只展示本地合同与就绪节点匹配的技能，原始目录仍能看到不兼容的声明以便诊断。

`SkillSpec.version`、`Step.version`、`ActionRequest.version` 使用正整数。`step()` 和 `system.action()` 自动取本地注册版本；Runtime 在任何分支派发前检查全部参与者，节点准入再次检查收到的版本。候选检索与计划缓存也校验版本。更换兼容的 TTS 后端不需要修改参数定义或 Runtime。

参数或结果语义发生不兼容变更时提升技能版本；当前要求精确匹配，不自动降级、不同时路由多个版本。没有自动下载、加载或接纳配置之外的技能。版本声明由经过审核的实现维护，目前不校验跨进程 Schema 摘要，错误地复用旧版本号仍需开发者避免。

合同版本与 `control_epoch`、`state_version` 不同：前者描述技能接口，后两者描述执行权限和业务状态，解释见 [任务句柄与调用链](task_handles.md)。

## 协议迁移和范围

当前信封为 `Envelope.schema_version=4`，Zenoh 前缀为 `wrs/v4/{site}/{target}`。v4 删除任务 hold/replace、TaskControl/TaskHoldReceipt、任务 HELD/RESUMING 和 supersedes；使用 task/cancel、TaskCancelRequest/TaskCancelReceipt、CANCELLING。设备 resume 更名 allow_actions，回执阶段为 ACTIONS_ALLOWED。v3 客户端与节点必须一起升级，没有自动兼容路由。

技能声明仍为版本映射，RPC 错误仍为 ErrorInfo。已有动作日志保留，缺少 error 的旧记录按 None 读取，不重播历史动作；Runtime 的任务结果仍只保存于当前进程会话。

本轮没有增加依赖、后台服务或额外版本查询 RPC。检查复用原有节点发现、能力缓存与执行准入；错误只新增小型结构化数据。未做延迟或吞吐基准，不宣称性能提升。

保留原有 context、任务句柄、配置绑定和节点内资源准入。暂不增加多实例选路、设备所有权服务、自动接纳节点或订阅协议。
