# 开发交接：先跑通，再替换后端

当前交付的是可以继续分工开发的软件 V1：任务调度、按资源取消与停止确认、任务句柄、节点目录、技能合同、GLM 非流式适配已经连接起来。默认用真实 Zenoh、多进程 Mock 节点验收；WRS 另有真实 Lite6 模型的虚拟 FK 示例。context 保持现状，先把后端接入做好。

## 一次看清系统

```text
UI / Python 脚本 ---- start / goal / task(id) ---> Agent 节点
  |                                               Runtime <-> Planner
  | send_text                                     |  按依赖、资源调度
  v                                               v
Voice 节点：文本分类、明确停止 -> Runtime 控制入口    WRS 节点 / TTS 节点
  | 停止播报                                      Environment / 播音后端
  +---------------------------------------------> TTS 控制入口

UI / Python 脚本 ---- action(...) ----------------> 对应动作节点
ASR 后端 ---------- 已识别文本 -------------------> Voice 文本入口
```

Zenoh 传输消息；Runtime 协调任务；动作节点负责最终准入与实际停止确认。普通查询、进度和节点控制不经过模型。一个 Skill 定义参数、资源、能力要求和验证条件；Node 声明实现了哪些技能版本；TOML 指定本系统允许把技能交给哪个节点。

Voice 和 Agent 已是独立 Zenoh 节点；Planner 是 Agent 内部可替换接口，当前无需再拆进程。Module/Stream 等概念取舍见 [节点与消息](NODES_AND_MESSAGES.md)。

当前明确配置、每种角色一个实例，支持配置节点独立上下线；不自动接纳网络上的新节点或新技能，不实现任意插件加载、跨机器设备所有权服务或多实例负载均衡。同一物理设备只有一个控制所有者。

## 先运行这些入口

从仓库根目录的 PowerShell 运行；解释器固定为 `D:\code\venv312\.venv\Scripts\python.exe`，脚本使用项目 `.local/deps`。新机器先按 [依赖说明](DEPENDENCIES.md) 初始化 WRS submodule、bootstrap 与 router。不要在开发任务中升级共享 Python 或 WRS gitlink。

```powershell
./scripts/run.ps1 examples/beginner/01_action.py
./scripts/run.ps1 examples/tasks/05_task_handles.py
./scripts/run.ps1 examples/tasks/07_voice_control.py
./scripts/run.ps1 examples/developer/05_custom_skill.py
./scripts/run.ps1 examples/developer/06_glm_runtime.py
./scripts/run.ps1 examples/tasks/03_wrs_scene.py
./scripts/run.ps1 examples/tasks/03_wrs_scene.py --cancel
```

前三项理解动作、任务和停止；第四项接入自定义节点与技能；第五项跑通模型适配到独立执行节点；最后两项需要已准备的 WRS 科学依赖。所有命令默认不访问付费模型、不启用硬件、不下载语音权重。WRS 依赖在干净机器的完整重建仍待验证。

## 建议拆给四位开发者的任务

| 分工 | 从哪里接手 | 第一项可验收交付 | 保留的边界 |
|---|---|---|---|
| WRS | `wrs_agent/env/wrs.py`、`examples/tasks/03_wrs_scene.py`、[WRS 审计](WRS_AUDIT.md) | 补一项有明确前置条件和结果验证的虚拟机器人能力，独立节点可查询、取消 | WRS 导入只在适配模块；不能把同步运动塞进控制循环 |
| TTS | `examples/developer/custom_speech.py`、`wrs_agent/nodes/tts.py` | 将 console 后端换成本地播音，实现 speak、进度、按 action_id 取消、停止确认 | 不依赖 WRS，不另建动作协议；真实播放停止后才能报告停止 |
| ASR | [识别文本合同](VOICE_INPUT.md)、`examples/tasks/07_voice_control.py` | 识别后的完整文本进入 send_text；部分识别不派发；明确停止不等模型 | 采集/识别独立运行；不把 VAD 当停止；不自动下载权重 |
| UI | `wrs_agent/system.py`、[任务句柄](task_handles.md)、[错误合同](errors_and_versions.md) | 节点列表、文本输入、任务进度、取消、确认结束后创建新任务、UNKNOWN 展示 | 使用稳定 task_id；关闭观察不停止执行；状态与受理结果分开展示 |

每项提交包含实现、一条可运行示例、正常完成/取消/故障证据。先用 Mock 把接口联调，再接各自真实依赖。不要同时修改协议、Runtime 调度和后端；如果现有合同无法表达能力，先提出具体缺失字段与行为。

## Node 与 Skill 的完整例子

例子中 `speaker` 是一个 TTS 角色的节点实例，提供现有 speak@1 和新增 greet@1。它逐字打印到控制台，用于演示可取消的后端，不会发出声音。

| 文件 | 职责 |
|---|---|
| `examples/developer/custom_speech.py` | 唯一 GreetArgs/Skill 合同、greet/console_speak 实现、create_node |
| `examples/developer/custom_speech.toml` | 实例名 speaker、传输 suffix、enabled、技能绑定 |
| `examples/developer/04_custom_node.py` | 静态导入合同，启动 TTS 或使用同一合同的 Agent |
| `examples/developer/05_custom_skill.py` | 启动独立进程、参数校验、直接动作、Runtime 任务、取消及清理 |

添加技能的步骤：

1. 用 Pydantic 定义参数模型，由它生成参数 Schema；声明资源、所需能力和验证方式。
2. 写普通异步处理函数 `handler(state, args, stop, progress)`，在后端允许的边界响应 stop；按实际结果更新状态。技能不导入模型 SDK 或 Zenoh。
3. 节点 factory 创建现有 ActionExecutor，将技能与后端交给它；沿用注册、快照、context、幂等、日志和控制服务。
4. 客户端、Agent 和动作节点在读取配置前显式导入同一技能合同。例子调用 `install_contract()`；只有节点导入不够，因为客户端与 Planner/Runtime 也需要校验参数。
5. 在 TOML 增加明确绑定；运行直接调用、任务调度和取消的回归。Runtime 不需要为 greet 新增分支。

`main(action_factory=...)` 接受本地 Python 回调，只能用于显式 wrs/tts 节点；不从配置解析任意类名，不从网络安装代码。示例里的 DemoStack 只是选择已审查的启动脚本，并不是新插件框架。仅替换 speak 后端时复用现有 SpeakArgs/SkillSpec，不复制另一套合同。

需要独立启动和连接时，在两个终端设置相同的 `WRS_AGENT_TOKEN`（16–128 字符），然后分别执行：

```powershell
# 终端 A：持续运行 router、speaker 与 Agent
./scripts/run.ps1 examples/developer/05_custom_skill.py --serve

# 终端 B：连接并运行示例；退出后服务继续运行
./scripts/run.ps1 examples/developer/05_custom_skill.py --connect
```

默认使用 `tcp/127.0.0.1:7447`、env_id=custom-demo；可在两端显式指定相同的 `--port` 与 `--env-id`。不设置共享 token 时，启动端生成的临时 token 只供自己的子进程使用。例子测试入口：`tests/integration/test_developer_examples.py`。

## WRS：先接虚拟能力

现有 WRS Node 已把固定版本 Lite6 接到公共动作协议。`03_wrs_scene.py` 展示直接动作的 ACCEPTED、进度、查询、取消，以及 Runtime 的命名姿态任务。同步 FK 在所属工作线程运行；控制先撤销旧权限，等在途调用返回后再确认停止。

当前真实 WRS profile 仅支持 observe / move_named_pose，支持 home/B/C 命名姿态。pick/place/物体 verify 和碰撞规划仍明确 unsupported；Mock 的抓取成功不能作为真实 WRS 能力证明。下一步可在适配器内加入已验证的夹爪、目标几何、碰撞与结果观测，再扩展对应技能。长时间规划宜放独立进程，设备控制保持单一所有者。

节点最终准入仍必须检查 boot_id、control_epoch、state_version、短期授权和资源占用；Runtime 的锁不替代节点校验。不能确认设备效果时使用 UNKNOWN，不能把“函数返回了”直接当成物理成功。参考 `tests/integration/test_wrs.py` 和 `tests/unit/test_wrs_boundary.py`。

## TTS：保持相同动作合同

先跑 console 示例，再替换合成/播放部分。重复相同 action_id 不重复播放；相同编号不同参数拒绝。取消请求受理与播放实际停止是两件事，后端要等待输出停止后才能报告确认。同步 SDK 调用不能阻塞控制循环；外部回调需要线程安全桥接。

状态结果可以继续复用 SpeechState。完成后更新 completed/last_text；取消不冒充完成。若设备可能已产生声音但无法确定是否停止，处理函数应使用现有 ExecutionUnknown 路径，而不是普通失败或虚构成功。真实驱动的重启恢复策略必须按其可观测性确定，不能直接套用“Mock 历史全为终态即可接单”的结论。

## ASR / UI：复用客户端

UI 可使用 `System.connect()` 的异步入口，使等待任务进度与用户停止操作并行；普通小脚本使用同步 `connect()`。不要在 UI 事件线程中调用同步 wait。进程生命周期由 launch/外部部署管理，UI 连接不负责启动每个后端。

| 操作 | 接口 |
|---|---|
| 节点与可用技能 | `nodes()`、`skills()` |
| 一次直接动作 | `action(...)` → ActionHandle |
| 显式计划 | `start(*steps)` → TaskHandle |
| 自然语言目标 | `goal(text)` → GoalHandle |
| ASR/文本输入 | `send_text(...)` → TextReceipt |
| 重连观察 | `task(task_id)`、`planning(request_id)` |
| 任务进度/取消 | 句柄的 `status/watch/wait/cancel` |

状态结果主要是类型化对象；`system.status()` 的 Runtime 总览、`nodes()` 目录仍为字典。不要假设每个返回值都有相同字段。错误读取 error.code，UNKNOWN 要保留并显示。浏览器项目可随后在独立服务中包装这些 API；本轮不引入 Web 框架、前端依赖或新的控制协议。

## GLM：完整软件路径已接好

`03_glm_adapter.py --dry-run` 只展示计划，不启动动作。`06_glm_runtime.py` 默认使用 HTTP 夹具，经过 GLMClient → ModelPlanner → Runtime → 真实 Zenoh → 独立 Mock WRS/TTS，执行并检查结果。它演示嵌入式 Runtime，因此动作配置 `configs/actions.toml` 不再额外启动一个 Agent。

真实服务使用进程环境中的 GLM_API_KEY、GLM_MODEL、GLM_BASE_URL，模型和端点应按实际可用服务设置；`.env.example` 仅说明变量，不自动读取。本轮没有发送真实模型请求。先验收仅规划调用，再显式开启端到端例子：

```powershell
./scripts/run.ps1 examples/developer/03_glm_adapter.py --live-model --dry-run
./scripts/run.ps1 examples/developer/06_glm_runtime.py --live-model --goal "put A in B"
```

常驻 Agent 也可通过 `-m wrs_agent launch --model-provider glm --live-model` 使用同一适配器。GLM 失败会保留结构化规划错误，如 glm_http_401；不会换成 Mock 成功。停止不等模型返回，迟到结果失效。当前只支持非流式单工具提案，尚无流式输出或 GLM TTS。

## 合并验收与后续范围

```powershell
./scripts/run.ps1 scripts/verify.py
./scripts/run.ps1 scripts/verify.py --wrs
```

后者增加 WRS 虚拟节点测试和完成/取消示例。真实命令、测试数量及限制见 [ACCEPTANCE.md](ACCEPTANCE.md)；机器报告生成在本地 reports/。本地 EXECPLAN 按仓库规则不上传，本文件是可提交的开发路线与交接合同。

当前优先补真实 ASR、本地可停止 TTS、WRS 虚拟抓放场景和 UI。动态接纳、context 重构、多设备所有权协调、跨机认证/ACL、持久任务恢复、性能基准分别立项；不作为这些后端开始开发的前置条件。真实硬件、真实音频质量、GLM 账号服务和干净机器 WRS 环境仍需单独验收。
