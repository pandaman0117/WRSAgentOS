# WRS-Agent V1

Zenoh 上的轻量机器人 Agent Runtime。模型提出计划，Runtime 检查和调度，动作节点负责实际执行与停止确认。默认使用独立进程的 Mock 机器人、Mock TTS、Agent 和 Voice；WRS 提供 Lite6 虚拟运动适配。

## 先跑一个动作

```python
from wrs_agent import launch

with launch() as system:
    motion = system.action("move_named_pose", pose="B")
    print(motion.wait().state)
    print(system.snapshot().data.pose)
```

完整文件：[01_action.py](examples/beginner/01_action.py)。每个示例只展示一个场景，目标和配置直接写在代码中，不需要命令行参数。

```powershell
./scripts/run.ps1 examples/beginner/01_action.py
```

预期结果：SUCCEEDED，当前位置 B。[示例目录](examples/README.md) 列出所有文件和预期输出；[入门教程](docs/getting_started.md) 依次解释动作、任务、取消与规划。

## 接着看这些文件

| 想了解什么 | 示例 |
|---|---|
| 多步任务 | [顺序执行](examples/tasks/01_sequence.py)、[不同资源并行](examples/tasks/02_parallel.py) |
| 执行时打断 | [取消任务](examples/tasks/03_cancel.py)、[语音停止](examples/voice/01_stop_task.py) |
| 查询和规划 | [观察进度](examples/tasks/04_watch.py)、[等待规划与任务](examples/tasks/05_goal.py) |
| 节点独立运行 | [启动服务与连接客户端](examples/README.md#connect) |
| 开发新节点和技能 | [greet 合同与处理函数](examples/nodes/greet_skill.py)、[分进程运行步骤](examples/README.md#nodes) |
| 接入 WRS | [虚拟运动](examples/wrs/01_move.py)、[取消](examples/wrs/02_cancel.py) |
| 接入 GLM | [离线规划](examples/models/01_plan_offline.py)、[离线执行](examples/models/02_execute_offline.py) |

动作、任务与规划都有各自句柄。`status()` 查询一次，`wait()` 等终态，`watch()` 观察进度；任务或动作的 `cancel()` 返回受理结果，停止完成另行确认。取消结束后可以 `start()` 一个独立新任务，旧句柄始终保留原身份。

结果的 `state` 分别为 `ActionState`、`TaskState`、`GoalState` 字符串枚举，例如 `from wrs_agent import TaskState` 后用 `result.state == TaskState.SUCCEEDED`。原来的字符串比较与 JSON 值不变，详见 [状态枚举](docs/task_handles.md#state-的字符串枚举)。

`launch()` 拥有并管理本机节点；`connect()` 连接已经运行的节点，客户端退出不会关闭服务。同步脚本用 `launch/connect`，异步应用用 `System.launch/System.connect`。UI 应使用异步接口，避免等待阻塞界面。

`send_text()` 接收 UI 文字或 ASR 已识别文本。明确停止经过独立 Voice 节点与本地控制路径，不等待模型；当前没有真实麦克风或 ASR 后端。

## 开发环境

固定解释器：`D:\code\venv312\.venv\Scripts\python.exe`。`scripts/run.ps1` 使用项目 `.local/deps`，不修改共享虚拟环境。新机器在仓库根目录准备：

```powershell
git submodule update --init --recursive
./scripts/bootstrap.ps1
./scripts/install_router.ps1
./scripts/run.ps1 examples/beginner/01_action.py
```

具体依赖及 WRS 科学环境限制见 [DEPENDENCIES.md](docs/DEPENDENCIES.md)。唯一默认源码 submodule 是 [chenhaox/WRS2](https://github.com/chenhaox/WRS2)，固定 `2bb014b747833c2fd9345115fbe26ffb11376f20`。DimOS 等仅为设计参考，不是运行依赖。

示例不使用参数切换场景。项目运维 CLI 仍可用 `./scripts/run.ps1 -m wrs_agent --help`；Python 节点入口为 `wrs_agent.nodes.serve.serve_node()`，示例直接传入明确配置。

## 系统的边界

- **Skill**：参数合同、资源要求、处理函数和结果验证；合同只有一份。
- **Node**：当前提供某些技能的独立执行实例；WRS、TTS、Voice、Agent 已分进程。
- **Bindings**：TOML 明确允许的节点与技能绑定；配置中的节点可独立上下线，不自动接纳未知节点或代码。
- **Runtime**：默认一项活动任务，任务内按依赖和资源并行；整体预检并绑定参与节点的启动实例与控制版本。
- **Planner**：Agent 内的可替换规划接口；不直接执行 WRS 或授予权限。

通信沿用 Event/Stream、Query、Action。协议 v4 前缀为 `wrs/v4/{site}/{target}`，控制有独立有界入口。动作节点最终检查资源占用、boot_id、control_epoch、state_version 和短期凭证；Runtime 的调度锁不能替代它。

`snapshot()` 只读节点状态，`context()` 额外申请执行凭证；普通 `system.action()` 自动处理。任务绑定控制版本，各动作使用新的业务状态版本。完整路径见 [任务句柄与调用链](docs/task_handles.md)。

不能确定动作是否执行或停止时使用 UNKNOWN，按原编号查询与观察，不盲目重发。节点重启不自动恢复旧运动。会话任务/规划记录上限为 4096；Runtime 重启后旧任务 ID 明确不存在。

默认只连接回环 Router，关闭自动网络发现，适用于受信本机进程。跨机身份与 ACL、设备多所有者协调尚未实现。同一物理设备应只有一个控制所有者。

## 模型与设备的验证范围

Mock Planner 只支持有限的明确模板。GLM 适配器使用 HTTPX，离线示例通过固定响应样本验证解析与执行路径，不发送真实云请求。真实规划和执行分别放在 `examples/models/03_plan_live.py`、`04_execute_live.py`，代码开关默认关闭；凭据从环境变量读取。真实调用需要相应服务授权与单独验收，不自动切换计费端点。

WRS profile 使用真实 Lite6 模型进行无窗口 FK 虚拟运动；目前只支持 observe / move_named_pose。抓放、碰撞规划、真实硬件、真实 ASR/音频、双机部署与性能基准均未验收。Mock 的状态变化不能证明这些设备能力。

## 验收与交接

```powershell
./scripts/run.ps1 scripts/verify.py
./scripts/run.ps1 scripts/verify.py --wrs
```

前者运行单元测试、真实 Zenoh/Mock 集成测试、离线示例、Ruff 和环境检查；后者额外验证 WRS 虚拟节点与三个 WRS 示例。常驻服务和独立客户端按组测试；真实 GLM 仅检查默认关闭，不触发联网调用。

每份示例均登记在 `scripts/example_catalog.py`，验收同时检查退出码和关键结果，避免把打印 FAILED 的程序当成通过。最新实际证据见 [ACCEPTANCE.md](docs/ACCEPTANCE.md)，机器报告保存在忽略的 `reports/`。

分工入口：[开发交接](docs/DEVELOPMENT.md)、[语音输入合同](docs/VOICE_INPUT.md)、[错误与技能版本](docs/errors_and_versions.md)、[节点与消息](docs/NODES_AND_MESSAGES.md)、[参考来源](docs/SOURCES.md)。当前优先完成 WRS、TTS、ASR 和 UI 后端；context 重构、Blueprint 和动态接纳继续留待讨论。
