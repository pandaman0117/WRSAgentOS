# 任务句柄、请求调用链与状态版本

当前保留 `context()` 和 `ActionContext`；节点仍由 TOML 配置允许，未增加自动接纳节点或技能。公开调用不再需要 `action_request()`。协议使用 `wrs/v4/{site}/{target}` 和 `Envelope.schema_version=4`，节点与客户端需要一起升级；不提供旧字段别名。

## state 的字符串枚举

动作、任务、规划结果的 `state` 分别使用标准库 `StrEnum`，可从包入口直接导入。编辑器可以补全成员，已有字符串比较继续有效。

```python
from wrs_agent import TaskState, launch, step

with launch() as system:
    task = system.start(step("move_named_pose", pose="B"))
    result = task.wait()
    if result.state == TaskState.SUCCEEDED:
        print("任务完成")
    print(result.state)        # SUCCEEDED
    print(result.state.value)  # SUCCEEDED，明确取出普通字符串
```

| 返回对象 | state 类型 | 允许值 |
|---|---|---|
| `ActionStatus`，包含动作回执内的 status | `ActionState` | ACCEPTED、RUNNING、VERIFYING、SUCCEEDED、FAILED、CANCELLING、CANCELLED、UNKNOWN |
| `TaskStatus` | `TaskState` | QUEUED、RUNNING、CANCELLING、SUCCEEDED、FAILED、CANCELLED、UNKNOWN |
| `TaskCancelReceipt` | `TaskState` 的原有子集 | CANCELLING、SUCCEEDED、FAILED、CANCELLED、UNKNOWN |
| `GoalStatus` / `GoalResult` | `GoalState` | WAITING、DONE、ANSWER、CLARIFY、FAILED、STALE、REQUIRES_CONFIRMATION |

同步和异步接口返回相同枚举；任务的 `status/wait/watch` 与取消回执都保留枚举类型。根据对象选择对应枚举，不用规划的 DONE 判断任务执行成功。

`result.state == "SUCCEEDED"` 仍然成立，打印及 f-string 仍显示原值。Pydantic 消息对象的 `model_dump()` 保留枚举；`model_dump(mode="json")`、`model_dump_json()`、Zenoh 和 SQLite 日志仍使用原字符串，不需要协议升级或日志迁移。未知字符串仍拒绝，不把未知拼写自动归为 UNKNOWN。

`system.status()` 的 Runtime 总览和 `nodes()` 目录仍为原始字典，来自消息的状态值仍是字符串；其中 IDLE 表示尚无任务或规划，不加入任务/规划结果枚举。步骤结果的 BLOCKED/STALE、设备 admission、控制 phase、验证结果也保持各自原有合同。

## 一次动作的完整调用链

普通同步脚本只需：

```python
from wrs_agent import launch

with launch() as system:
    action = system.action("move_named_pose", pose="B")
    print(action.wait().state)
```

它在内部依次经过：

1. 同步 `Session.action()` 使用现有 Runner 调用异步 `System.action()`。
2. `System` 根据配置找到动作节点，刷新目录并检查在线实例，再调用 `ActionClient.context()`。
3. `context()` 通过 `Transport.request("request/action/context", {})` 向执行节点申请 `ActionContext`。节点返回当前状态以及短期 `lease_id`；普通 `snapshot()` 不产生凭证。
4. `ActionClient.submit(skill, args, context=..., task_id=...)` 在内部生成一次 `action_id`，构造 `ActionRequest`。这个消息合同仍明确包含 boot_id、control_epoch、state_version、lease_id、task_id 和参数。
5. 客户端调用 `Transport.request("request/action/submit", request.model_dump())`。Transport 处理信封、校验、Zenoh 请求与回复，不安排任务。
6. 对端 `register_actions()` 校验消息合同，把请求交给 `ActionExecutor.submit()`。执行器依次检查重复 ID、实例、控制版本、状态版本、短期凭证、技能与资源，并在副作用之前记录意图。
7. 节点返回受理回执；执行在后台继续。客户端返回 `ActionHandle`，后续 `status()` / `wait()` 查询同一个 action_id。成功还需检查动作结果中的 verification。

如果提交回复丢失，客户端只查询刚才生成的 action_id。查到记录就继续观察；查不到或查询也失败则报告 `UNKNOWN` 并带 action_id，不自动重发动作。

`system.start(*steps)` 多了一段 Runtime 调度：先接收确定计划并生成 task_id，再对所有参与节点完成整体预检，保存各节点 `(boot_id, control_epoch)`；随后按依赖和资源派发。每一步取新 context 后先检查这两个绑定，再使用相同的 `ActionClient.submit()`。业务状态可以随着前一步变化，所以 state_version 按动作更新，不在整项任务中固定。

底层示例现在是：

```python
context = await client.context()
action = await client.submit("observe", {}, context=context, task_id="roundtrip")
print((await action.wait()).state)
```

这些概念分工不同：`ActionRequest` 是线上的数据合同；`client.submit()` 是动作调用入口；`bus.request()` 是消息传输操作。移除公开组装函数后，普通使用者只接触 `system.action()`。

## 为什么保留两个版本

| 字段 | 回答的问题 | 失效例子 |
|---|---|---|
| `boot_id` | 是否还是同一次节点启动？ | 节点重启，旧任务不能获得新实例授权 |
| `control_epoch` | 这次动作是否仍被允许执行？ | 停止发生但姿态没变，旧请求仍必须失效 |
| `state_version` | 动作使用的业务状态是否仍然有效？ | 物体位置或持物状态变化，但没有发生停止 |
| `lease_id` | 是否持有该节点签发的短期执行凭证？ | 凭证过期，或已经被控制变化撤销 |

`control_epoch` 可以理解为“执行权限版本”，`state_version` 可以理解为“业务状态版本”。将二者合并，会无法分别表达“环境变了”和“权限被撤销了”。只读状态查询和签发 context 不增加 state_version；节点决定何时推进自己的业务状态版本。旧字段 `world_version` 已移除，旧错误码 `stale_world` 改为 `stale_state`。

## TaskHandle 的使用和边界

```python
from wrs_agent import launch, step

with launch() as system:
    task = system.start(step("move_named_pose", pose="B"))
    print(task.id, task.status().state)
    print(task.wait().state)
```

句柄只持有任务身份和连接，调用现有 Runtime 服务，不保存调度器或自动追踪“当前任务”。`system.task(task_id)` 可在重连后重建同一任务的句柄。`system.status()` 仍返回 Runtime 总览字典；全局 `system.wait/watch` 已删除。

| 方法 | 含义 |
|---|---|
| `status()` | 返回这项任务的一次 `TaskStatus` |
| `wait(timeout=10)` | 等待终态并返回 `TaskStatus`，也可能 FAILED/CANCELLED/UNKNOWN |
| `watch(timeout=10)` | 每 20ms 尝试轮询并返回有变化的状态，可能错过瞬时进度 |
| `cancel()` | 取消这项任务；返回 `TaskCancelReceipt`，受理与停止完成分开 |

`wait/watch` 超时只结束观察；关闭 watch 迭代器也不会取消任务。`timeout=None` 允许持续观察。`CANCELLING` 不是终态，等待会继续。退出 `connect()` 仅关闭客户端；退出 `launch()` 则仍会关闭它拥有的本地节点。

```python
from wrs_agent import TaskState, launch, step

with launch(duration=1) as system:
    task = system.start(step("move_named_pose", pose="B"))
    receipt = task.cancel()
    assert receipt.accepted, receipt
    stopped = task.wait()
    if stopped.state == TaskState.CANCELLED:
        next_task = system.start(step("move_named_pose", pose="C"))
        print(next_task.wait().state)
    else:
        print(stopped.state, stopped.error)
```

`cancel()` 受理后，任务进入 CANCELLING：立即阻止后续派发，使待返回规划失效，清空依赖当前任务继续执行的追加队列；后台请求所有参与资源停止，等待在途提交并按原 action_id 核对结果。确认后独立进入 CANCELLED，无法确认则 UNKNOWN。它不需要另一项任务来完成收尾，也不撤销已经发生的抓取、播音等效果。

只有当前任务的参与节点进入停止确认，无关节点离线不影响取消。即使参与节点暂时空闲，也要撤销旧控制版本，阻止网络途中迟到的旧动作。

CANCELLING / UNKNOWN 时 `start()` 拒绝新任务，返回 task_busy。确认正常取消后可以提交一项独立新任务；根据停止后的真实状态写步骤，例如 A 已在手里就只提交放置与验证。旧句柄一直保存原结果，不会跟随新任务。没有替换链或自动续跑。

取消排队任务只删除指定排队项，不影响正在执行的任务与其他排队项；取消当前任务则一并取消尚未执行的追加队列。已知终态的当前任务收到取消请求时保持原终态。旧任务 ID 不能取消后来的任务；相同取消请求的重试返回首次受理结果，不代表最新状态，最新状态用 status/wait 查询。句柄自动复用自己的取消 request_id，并发调用和丢回复重试不会重复发起控制。

### 任务取消与设备准入

任务用户只需 `task.cancel()`。设备层仍有节点的 hold 控制服务：停止设备并关闭动作准入。`system.allow_actions(node=...)` 在确认停止、状态有效时允许**新动作**，不会续跑旧任务。此前的 resume 名称已删除。

正常任务取消会在确认动作结束后，重新开放它自己关闭的机器人准入。只有启动实例与本次控制版本仍匹配，且停止前仍是原任务绑定的开放权限，才能自动开放；另一次设备 hold、重启恢复锁止、UNKNOWN 都不能被取消或新任务解除。独立动作 `action.cancel()` 仍遵循节点的规则：机器人保持关闭，Mock TTS 确认结束后可接收新播报。

节点协议中，`ControlRequest.action_id` 有值的 cancel 仅取消匹配的活动动作；无值的 cancel 用于撤销该参与资源的旧权限，包含尚在途中的请求。Runtime 对机器人使用 hold，对 TTS 使用这种资源取消。两者都必须幂等，不能用一个普通“取消协程”冒充停止确认。

异步形式与同步形式一一对应：

```python
from wrs_agent import System, step

async with System.launch() as system:
    task = await system.start(step("move_named_pose", pose="B"))
    async for status in task.watch():
        print(status.state)
    result = await task.wait()
    same = system.task(task.id)  # 构造句柄本身不通信
    assert (await same.status()).task_id == result.task_id
```

## 规划请求单独等待

```python
planned = system.goal("put A in B").wait()
if planned.task is not None:
    print(planned.task.wait().state)
else:
    print(planned.state, planned.reason)
```

`goal()` 返回 `GoalHandle`，身份是规划期间的 request_id。它的 `wait()` 等规划结束，不等物理执行。规划结果可能为 ANSWER、CLARIFY、FAILED、STALE 或 REQUIRES_CONFIRMATION；只有计划被接收为任务时，DONE 结果才带 TaskHandle。之后的任务或规划不会覆盖原结果。

Runtime 在本次进程会话内保存最多 4096 项任务和规划结果，总数满时拒绝新增；已有结果仍可查询，不为新增项淘汰旧结果。请求去重也保持原有 4096 项上限。排队任务有自己的 ID，停止清队列或前项失败时，尚未执行的任务保存 CANCELLED。Runtime 重启不恢复任务：旧任务与规划 ID 分别明确返回 task_not_found / goal_not_found。

执行节点的动作日志独立保留。历史全为已知终态时，Mock TTS 重启可接新动作；有未确认记录时仍为 UNKNOWN，绝不重播。机器人仍采用原来的保守恢复准入。

可运行示例：[取消后开始新任务](../examples/tasks/03_cancel.py)、[观察进度](../examples/tasks/04_watch.py)、[等待规划](../examples/tasks/05_goal.py)。每份脚本直接运行，不需要附加参数。
