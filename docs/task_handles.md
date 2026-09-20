# 任务句柄、请求调用链与状态版本

本轮保留 `context()` 和 `ActionContext`；节点仍由 TOML 配置允许，未增加自动接纳节点或技能。公开调用不再需要 `action_request()`。协议使用 `wrs/v3/{site}/{target}` 和 `Envelope.schema_version=3`，节点与客户端需要一起升级；不提供旧字段别名。

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
| `hold()` | 阻止后续派发，并请求参与资源停止；返回 `TaskHoldReceipt` |
| `replace(*steps)` | 显式替换此任务，返回一个新任务句柄 |

`wait/watch` 超时只结束观察；关闭 watch 迭代器也不会取消任务。`timeout=None` 允许持续观察。`HELD` 不是终态，等待会继续。退出 `connect()` 仅关闭客户端；退出 `launch()` 则仍会关闭它拥有的本地节点。

```python
from wrs_agent import launch, step

with launch(duration=1) as system:
    task = system.start(step("move_named_pose", pose="B"))
    receipt = task.hold()
    assert receipt.accepted and receipt.phase != "UNKNOWN", receipt
    replacement = task.replace(step("move_named_pose", pose="C"))
    print(replacement.wait().state)
    print(task.wait().state)  # 原任务结果，通常为 CANCELLED
```

`replace()` 要求已显式调用并成功受理 hold。STOPPING 只表示正在停止；新任务以 RESUMING 等待旧参与资源停止确认。旧计划涉及、替换计划不再使用的资源也必须确认停止；无关配置节点不参与。若无法确认，新任务进入 UNKNOWN。重复替换也不能绕过更早的停止依赖。

控制版本变化后，已提交动作继续按原 action_id 查询结果：CANCELLING 仍需等待，只有缺失、不确定或查询超时才报告 UNKNOWN。不会给旧计划重新申请新控制版本的执行资格。

确认旧资源停止后，旧任务保存自己的终态；新任务获得新的 task_id，并以 supersedes 指向旧任务。旧句柄不会跟随新任务。hold 不承诺续跑旧计划；修改目标时需明确写出新的剩余步骤，例如已经持有 A 时仅提交放置和验证。

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

可运行示例：`./scripts/run.ps1 examples/tasks/05_task_handles.py`。
