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

参数错误示例：`./scripts/run.ps1 examples/beginner/04_invalid_input.py`；合同版本查询见 `examples/beginner/02_skills.py`。
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
动作、任务、规划的 `state` 分别返回 `ActionState`、`TaskState`、`GoalState` 字符串枚举，详见 [状态枚举](task_handles.md#state-的字符串枚举)。枚举保留原有合法值；取消回执仍拒绝 QUEUED/RUNNING，未知状态仍拒绝。

任务句柄返回类型化的 `TaskStatus`；`system.status()` 总览和 `system.nodes()` 仍是字典，错误字段也是序列化的同一合同。

| 常见错误码 | 意义 |
|---|---|
| `provider_not_found` | 未发现或选定该技能的执行者 |
| `node_unavailable` | 节点在当前发现视图中不可用 |
| `node_not_ready` | 节点在线，但尚未开放动作准入 |
| `node_ambiguous` | 多个启动实例声明相同节点身份 |
| `node_endpoint_ambiguous` | 不同动作节点占用同一个服务地址 |
| `node_role_ambiguous` / `node_role_mismatch` | 角色不唯一需显式选定 peer / 所选节点角色不符 |
| `discovery_capacity_exceeded` | 有界节点目录容量耗尽 |
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

执行端同时发布技能名称/版本与完整 SkillSpec；客户端和 Runtime 不导入具体技能包。
step() 的未指定版本在提交时从发现结果解析，显式版本必须与提供者精确匹配。
Task 保存确定的合同、提供者和启动会话；追加新技能不改变已提交任务。
节点重启后，旧任务不能继承新会话的权限。

TOML 保留节点部署，[skills] 只作可选提供者覆盖。唯一提供者自动解析，
重名报告 skill_provider_ambiguous，指定提供者离线不会自动转给其他节点。
缺失提供者、节点离线、参数无效与版本冲突保留独立错误码。

参数 Schema 由 Pydantic 类型生成，自定义 Python 校验在所属执行端做批量纯预检。
全部步骤通过后才执行首个动作，实际提交仍做原有权限和参数检查。
缓存使用发现到的合同签名，不存执行授权。完整接口见 [技能库](../wrs_agent/skills/README.md)。

## 协议迁移和范围

当前信封为 `Envelope.schema_version=4`，Zenoh 前缀为 `wrs/v4/{site}/{target}`。v4 删除任务 hold/replace、TaskControl/TaskHoldReceipt、任务 HELD/RESUMING 和 supersedes；使用 task/cancel、TaskCancelRequest/TaskCancelReceipt、CANCELLING。设备 resume 更名 allow_actions，回执阶段为 ACTIONS_ALLOWED。v3 客户端与节点必须一起升级，没有自动兼容路由。

技能发现同时携带版本映射和完整 specs，RPC 错误仍为 ErrorInfo。已有动作日志保留，缺少 error 的旧记录按 None 读取，不重播历史动作；Runtime 的任务结果仍只保存于当前进程会话。

技能发现复用原有 request/features；新增 request/skills/validate 只做批量参数预检。未增加依赖或后台服务。未做延迟或吞吐基准，不宣称性能提升。

保留原有 context、任务句柄、配置绑定和节点内资源准入。同名技能只支持显式选定提供者，暂不增加负载均衡、设备所有权服务或自动安装节点代码。

### features 命名迁移（2026-09-25）

当前开发版把 capabilities 统一命名为 features：节点目录返回 `features`，
技能可用性以实际注册表为准，底层查询为 `request/features`，
Python 查询方法为 `features()`，返回类型为 `FeatureSnapshot`。
旧字段和路径不再兼容，客户端与节点需一起更新并重启；不支持混用新旧节点。
该命名迁移保持原有语义；后续技能发现消息的增量见下节。
完整对照表见 [Node 指南](NODE_LAUNCH.md#功能名称迁移)。


### 技能单入口迁移（2026-09-25）

删除公共全局 SKILLS、register_greet 和普通 TOML 的逐技能路由。
FeatureSnapshot 新增 specs、boot_id、skill_revision；NodeInfo 增加 skill_revision。
Python step() 发送 version=None，Runtime 解析为明确版本后冻结 Task；
ActionRequest 仍要求明确正整数版本。节点和客户端必须一同更新重启。
add_skills 为显式本地追加，不支持替换、卸载或 Python 热加载。


### 动态节点发现迁移（2026-09-25）

节点在 `wrs/v4/{site}/{env}/discovery/{node_id}/{target}/{boot_id}` 声明存活，
NodeInfo 新增 `target`、`actions`、`robot_controls`。目录核对声明与描述后建立通信对象；
旧的各目标 namespace 下 presence 声明不再作为发现来源，相关节点和客户端需一同更新重启。
Action/Control 请求地址和 boot/epoch 校验保持不变。普通 Node 不读取部署 TOML；
launch 和显式传入 bindings 的启动/连接入口可解析文件，System.connect 默认只需通信域与凭据。
Task 同时固定客户端引用和控制能力，运行中目录变化不替换其执行者。


技能编写接口现接收 name、arguments、handler 和动作说明，SkillSpec 由参数模型派生。
已移除 required_features 与未实现的 interrupt_mode；preconditions/verification 是说明，
不会自动执行校验。停止、资源、参数预检与后端结果确认保持原有执行边界。
本次开发版合同变更需要客户端与节点同批更新；技能行为未改变时不提升动作 version。
目录描述满时新增节点报告 discovery_capacity_exceeded，离线描述可以回收。
真正的重复实例仍报 node_ambiguous，同址动作服务仍报 node_endpoint_ambiguous；
声明尚未核验的同址节点暂报 node_not_ready，不能因容量拒收而绕过冲突检查。
