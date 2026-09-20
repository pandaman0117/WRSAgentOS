# 示例：一份脚本，一件事

每份脚本直接写出配置、调用和结果；没有命令行参数，也没有运行模式开关。修改目标、文本或地址时，直接改代码。先读最简单的一份，再按需要看其他文件。

从仓库根目录运行：

```powershell
./scripts/run.ps1 examples/beginner/01_action.py
```

`run.ps1` 只负责使用项目指定的 Python 和依赖。示例文件名后不需要附加参数。新机器先完成 [依赖准备](../docs/DEPENDENCIES.md)。普通例子使用同步 API；常驻服务和底层通信使用 async。

## 基础动作

| 文件 | 只展示什么 | 预期结果 |
|---|---|---|
| [01_action.py](beginner/01_action.py) | 提交动作并等待 | SUCCEEDED，姿态 B |
| [02_skills.py](beginner/02_skills.py) | 查看可用技能和合同版本 | 名称、版本、描述 |
| [03_cancel_action.py](beginner/03_cancel_action.py) | 取消一次 Mock 播报 | CANCELLED |
| [04_invalid_input.py](beginner/04_invalid_input.py) | 读取参数错误 | invalid_arguments |

## 任务

| 文件 | 只展示什么 | 预期结果 |
|---|---|---|
| [01_sequence.py](tasks/01_sequence.py) | 抓取 → 放置 → 验证 | A 位于 B |
| [02_parallel.py](tasks/02_parallel.py) | 运动与播报同时执行 | 同时出现 2 个活动动作 |
| [03_cancel.py](tasks/03_cancel.py) | 取消结束后开始新任务 | 旧 CANCELLED，新 SUCCEEDED |
| [04_watch.py](tasks/04_watch.py) | 观察任务进度 | 状态变化到 SUCCEEDED |
| [05_goal.py](tasks/05_goal.py) | 等规划，再等执行 | DONE → SUCCEEDED |
| [06_cache.py](tasks/06_cache.py) | 同样状态下复用计划 | 模型调用保持 1，命中 1 次 |

任务结果可用 `TaskState.SUCCEEDED` 等枚举成员判断，动作和规划结果分别使用 `ActionState`、`GoalState`；打印仍显示原字符串。取消示例演示这种写法，完整约定见 [状态枚举](../docs/task_handles.md#state-的字符串枚举)。

`after` 表示步骤依赖；没有依赖、使用不同节点的步骤可以并行。这里抓取/放置是 Mock 状态变化，目标规划是确定的 Mock 模板。

## 语音入口

| 文件 | 只展示什么 |
|---|---|
| [01_stop_task.py](voice/01_stop_task.py) | 任务运行时收到“停止” |
| [02_stop_speech.py](voice/02_stop_speech.py) | “别说了”只停止播报，机器人继续 |
| [03_query.py](voice/03_query.py) | “做到哪一步了”查询进度 |
| [04_text_goal.py](voice/04_text_goal.py) | 已识别文本成为规划目标 |

这些例子直接传入已识别文本，不采集麦克风。ASR 或 UI 接入后调用同一个 `send_text()`。明确停止走控制路径，不等待模型。受理不等于停止完成，最终结果用任务或动作句柄查询。

## WRS 虚拟机器人

| 文件 | 只展示什么 |
|---|---|
| [01_move.py](wrs/01_move.py) | Lite6 虚拟运动到 B，读取关节和末端位置 |
| [02_cancel.py](wrs/02_cancel.py) | 取消虚拟运动并查询停止确认 |
| [03_new_action_after_cancel.py](wrs/03_new_action_after_cancel.py) | 确认取消后开放新动作准入，再回 home |

需要已准备好的 WRS 科学依赖。使用真实 WRS 模型的无窗口 FK 运动，不连接硬件；没有验证真实抓放或碰撞规划。普通任务取消会收尾，直接机器人动作取消则需要显式 `allow_actions()`；它只允许新动作，不续跑旧动作。

## connect

这一组区分“拥有服务”和“连接服务”。在两个终端中配置相同的 `WRS_AGENT_TOKEN` 环境变量（16–128 字符），确保回环端口 7447 空闲。

终端一运行 [01_start_system.py](connect/01_start_system.py)，保持运行：

```powershell
./scripts/run.ps1 examples/connect/01_start_system.py
```

看到“TTS 已就绪”后，终端二运行 [02_client.py](connect/02_client.py)：

```powershell
./scripts/run.ps1 examples/connect/02_client.py
```

客户端完成一次播报后退出，服务继续运行。终端一按 Ctrl+C 关闭自己拥有的节点和 Router。地址、配置路径和 env_id 都直接写在两份代码中。

## nodes

这一组交给开发新节点与技能的同学。`speaker` 是独立 TTS 角色节点，只提供 `greet`，逐字打印问候，不播放声音。Agent 是另一个进程，使用既有 Runtime 调度。

| 文件 | 职责 |
|---|---|
| [greet_skill.py](nodes/greet_skill.py) | 唯一参数合同、技能描述和可取消处理函数 |
| [bindings.toml](nodes/bindings.toml) | 节点实例与技能绑定 |
| [router.json5](nodes/router.json5) | 本组 Router 配置，回环端口 7448 |
| [00_start_router.py](nodes/00_start_router.py) | 终端一：Router |
| [01_start_speaker.py](nodes/01_start_speaker.py) | 终端二：技能执行节点 |
| [02_start_agent.py](nodes/02_start_agent.py) | 终端三：任务调度节点 |
| [03_call_skill.py](nodes/03_call_skill.py) | 终端四：调用一次 greet |
| [04_task.py](nodes/04_task.py) | 终端四：通过任务调用 greet |
| [05_cancel.py](nodes/05_cancel.py) | 终端四：取消正在打印的问候 |

在各终端设置相同的 `WRS_AGENT_TOKEN`，依次启动：

```powershell
# 终端一
./scripts/run.ps1 examples/nodes/00_start_router.py
# 终端二
./scripts/run.ps1 examples/nodes/01_start_speaker.py
# 终端三
./scripts/run.ps1 examples/nodes/02_start_agent.py
```

看到两个节点的 ready 后，在终端四分别运行：

```powershell
./scripts/run.ps1 examples/nodes/03_call_skill.py
./scripts/run.ps1 examples/nodes/04_task.py
./scripts/run.ps1 examples/nodes/05_cancel.py
```

预期依次为 SUCCEEDED、SUCCEEDED、CANCELLED。先退出 Agent 和 Speaker，最后退出 Router，均使用 Ctrl+C。技能日志保存在 `.local/state/example-speaker.sqlite3`，重启保留去重记录；不要在节点运行时删除日志。

新增技能主要改合同与处理函数、节点创建信息和绑定，不需要修改 Runtime。详细边界见 [开发交接](../docs/DEVELOPMENT.md)。

## 模型

| 文件 | 只展示什么 | 网络调用 |
|---|---|---|
| [01_plan_offline.py](models/01_plan_offline.py) | GLM 响应解析为计划 | 无，固定 HTTP 样本 |
| [02_execute_offline.py](models/02_execute_offline.py) | 计划经过 Runtime 与独立 Mock 节点执行 | 只有本机 Zenoh |
| [03_plan_live.py](models/03_plan_live.py) | 真实 GLM 只提出计划 | 需手动开启 |
| [04_execute_live.py](models/04_execute_live.py) | 真实 GLM 规划，Mock 节点执行 | 需手动开启 |

真实模型两份文件的 `ALLOW_LIVE_MODEL` 默认是 `False`，直接运行会明确退出。确认服务使用权限和费用，配置 `GLM_API_KEY`、`GLM_MODEL`、`GLM_BASE_URL` 后，手动修改相应文件中的开关和目标。凭据只放环境变量；`.env.example` 不会自动加载。真实服务未验收，普通示例和回归测试不会调用它。

离线样本固定为 A → B；修改问题文字不会让该样本自动产生新计划。

## 底层通信

| 文件 | 只展示什么 |
|---|---|
| [01_query.py](transport/01_query.py) | 向动作节点查询快照 |
| [02_events.py](transport/02_events.py) | 订阅一条动作进度事件，再查询终态 |
| [03_submit.py](transport/03_submit.py) | 显式获取 context，由客户端构造请求 |
| [04_timeout.py](transport/04_timeout.py) | 查询超时后仍可继续查询 |

通常只需前面的 `system.action()`；这组用于接手通信代码。事件不保证每条都被观察到，终态通过句柄查询。测试断言、故障注入和多场景汇总留在 `tests/`；`scripts/verify.py --wrs` 检查所有离线示例输出，成组服务由集成测试验证。
