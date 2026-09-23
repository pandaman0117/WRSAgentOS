# 从一份短脚本开始

项目把三个问题分开：**Skill 会做什么，Node 在哪里执行，Task 怎样组织步骤。** 普通脚本通过 `system` 使用这些能力，不需要自己构造消息或管理 Zenoh 连接。

先按 [依赖说明](DEPENDENCIES.md) 准备项目环境。在仓库根目录运行：

```powershell
./scripts/run.ps1 examples/beginner/01_action.py
```

这份文件的主体就是：

```python
from wrs_agent import launch

with launch(backend="wrs") as system:
    motion = system.action("move_named_pose", pose="B")
    result = motion.wait()
    print(result.state)
    print(system.snapshot().data.robot.pose)
```

`launch()` 启动并拥有本机节点，退出时关闭它们。`action()` 提交一次动作并返回句柄；`wait()` 等这一次动作结束。示例使用实际 WRS 模型，预期输出 SUCCEEDED 和 B。

`result.state` 是 `ActionState` 字符串枚举。任务结果使用 `TaskState`，规划结果使用 `GoalState`；三者都从 `wrs_agent` 导入。可以写 `result.state == ActionState.SUCCEEDED`，打印仍显示 SUCCEEDED。

## 再增加一个概念：任务

直接动作之外，`start()` 可以提交多个步骤：

```python
from wrs_agent import launch, step

with launch(backend="wrs") as system:
    ready = step("move_named_pose", pose="B")
    upward = step("move_relative", dz=0.02, after=ready)
    observe = step("observe", after=upward)
    task = system.start(ready, upward, observe)
    print(task.wait().state)
```

`after` 声明前后关系。Runtime 先检查整个计划，再按照依赖与节点资源派发步骤；运动和播报这样的独立资源可以并行。一个动作节点仍会检查自己的占用和执行权限。

完整文件分别是 [顺序任务](../examples/tasks/01_sequence.py) 和 [并行任务](../examples/tasks/02_parallel.py)。任务句柄始终指向同一个 task_id，查询其他任务使用 `system.task(task_id)`。

## 分别看进度与取消

[04_watch.py](../examples/tasks/04_watch.py) 只展示 `task.watch()`。它返回观察到的状态变化，不保证捕获每一瞬间；超时或停止观察不会取消任务。

[03_cancel.py](../examples/tasks/03_cancel.py) 只展示取消后开始独立新任务：

```python
from wrs_agent import TaskState

receipt = task.cancel()
print(receipt.accepted)
stopped = task.wait()
if stopped.state == TaskState.CANCELLED:
    next_task = system.start(step("move_named_pose", pose="C"))
    print(next_task.wait().state)
```

取消先停止后续派发，再请求参与节点停止并核对结果。受理回执不表示设备已经停住；CANCELLING 表示仍在处理，UNKNOWN 表示无法确认。确认 CANCELLED 后才开始新任务。已经发生的物理效果不会被撤销，例如已经抓住的物体仍可能在手里。

不需要 replace 或自动续跑。旧句柄保留旧结果，新计划使用新的 task_id。

## 把输入换成文字

[01_text_stop_task.py](../examples/voice/01_text_stop_task.py) 在任务执行时调用：

```python
receipt = system.send_text("停止", input_id="stop-001")
print(receipt.accepted)
print(task.wait().state)
```

UI 可以直接提供文字；ASR 后端识别完成后也调用同一个入口。Voice 节点识别明确停止后走本地控制服务，不等待云模型。另有 [只停播报](../examples/voice/02_text_stop_speech.py)、[查询进度](../examples/voice/03_text_query.py)、[文字目标](../examples/voice/04_text_goal.py)，每种情况一份文件。

当前没有真实麦克风识别，VAD 和部分识别也不代表已确认停止。接入约定见 [VOICE_INPUT.md](VOICE_INPUT.md)。

## 让 Planner 给出步骤

[05_goal.py](../examples/tasks/05_goal.py) 展示两次等待：

```python
planned = system.goal("home").wait()
if planned.task is not None:
    print(planned.task.wait().state)
else:
    print(planned.state, planned.reason)
```

第一次等规划结果，第二次等执行结果。此例使用确定的 home 模板；Planner 也可能回答或要求澄清。在线模型见 [模型示例](../examples/README.md#模型)。缓存只缓存计划结构，不保存执行授权，完整行为由测试覆盖。

## 接入自己的节点

先看 [独立连接](../examples/README.md#connect)：服务保持运行，客户端随时连接、退出。`connect()` 只拥有连接，退出不会关闭远端节点。

再看 [节点与技能](../examples/README.md#nodes)：合同在 `greet_skill.py`，执行器在 `01_start_speaker.py`，调度器在 `02_start_agent.py`，调用与取消各有文件。地址、节点名和绑定直接写在代码或 TOML 中，没有命令行模式切换。

WRS 同样使用动作接口：[虚拟运动](../examples/wrs/01_move.py)、[取消](../examples/wrs/02_cancel.py)、[取消后接收新动作](../examples/wrs/03_new_action_after_cancel.py)。另有 [方向移动](../examples/wrs/04_move_relative.py) 和 [独立节点及 viewer](../examples/README.md#wrs-虚拟机器人)。它使用真实 UR7E 模型计算 IK/FK，不代表已经接通硬件或实现抓放。

需要修改内部实现时，再读 [完整调用链与 context](task_handles.md)、[错误合同](errors_and_versions.md)、[开发交接](DEVELOPMENT.md)。全部文件与预期输出见 [示例目录](../examples/README.md)。
