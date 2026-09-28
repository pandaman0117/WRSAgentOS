# 开发交接：先跑通，再替换后端

当前交付的是可以继续分工开发的软件 V1：任务调度、按资源取消与停止确认、任务句柄、节点目录、技能合同、在线模型非流式适配（OpenAI Chat/Responses、Anthropic Messages 三种线协议）已经连接起来。默认用真实 Zenoh、多进程 Mock 节点验收；WRS 另有真实 UR7E 模型的虚拟 FK 示例。context 保持现状，先把后端接入做好。

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

Zenoh 传输消息；Runtime 协调任务；动作节点负责最终准入与实际停止确认。 Node 的 `features` 表示提供哪些功能，`skills` 表示可调用的操作，`options` 表示启动设置。普通查询、进度和节点控制不经过模型。一个 Skill 定义参数、资源、能力要求和验证条件；Node 从绑定表发布完整技能合同；TOML 声明接入节点，唯一技能提供者自动选定，同名冲突才配置可选路由。

Voice 和 Agent 已是独立 Zenoh 节点；Planner 是 Agent 内部可替换接口，当前无需再拆进程。五类内置节点共用一层 Node 生命周期；编写方法见 [节点实现与启动](NODE_LAUNCH.md)，概念取舍见 [节点与消息](NODES_AND_MESSAGES.md)。

launch 的便捷部署清单仍每种内置角色一个实例；独立节点按 node_id 区分，可同时运行多个。同一 site/env_id 内的运行节点通过 Zenoh 动态发现，Agent 和普通 Node 不持有全局部署清单。节点和显式追加的技能都可在运行中加入；同名技能需明确选择，已有任务固定执行实例。不自动加载发现到的代码，不实现任意插件加载、跨机器设备所有权服务或多实例负载均衡。同一物理设备只有一个控制所有者。

## 源码职责与阅读入口

| 文件 | 维护内容 |
|---|---|
| `system.py` / `sync.py` / `handles.py` | 异步客户端、同步包装与任务/规划句柄 |
| `runtime.py` | 文件开头定义任务执行、执行状态和规划状态；Runtime 是任务、规划和取消的唯一协调入口 |
| `plan_validation.py` | 技能、能力和资源先后关系的纯校验 |
| `executor.py` | 单节点动作准入、幂等、执行日志与停止确认 |
| `nodes/action_rpc.py` | 动作客户端、动作句柄与服务端消息绑定 |
| `nodes/node.py` | 唯一 Node 基类：初始化、通信资源与退出清理 |
| `nodes/<role>/node.py` | 配置类与 Node 直接子类同文件，各自拥有校验、状态、请求处理与业务装配；Voice 使用 Empty |
| `nodes/options.py` / `serve.py` | 共享字段约束；内置节点列表、参数映射与单节点运行入口 |
| `processes.py` | 本机进程启动、并发等待初始化与进程回收 |
| `skills/contracts.py` / `catalog.py` | 共用技能绑定类型；对节点发现结果做检索与校验，无中央 SKILLS |
| `skills/robot/definitions.py` / `skills/speech/definitions.py` | 各能力自己的参数、描述与合同；说明书在同目录 SKILL.md |
| `env/mock.py` / `wrs.py` / `ur.py` / `ur_rtde.py` | 机器人状态与后端实现 |
| `nodes/asr/capture.py` / `qwen.py` | 麦克风与脚本采集 / Qwen 识别模型 |
| `nodes/tts/backend.py` / `qwen.py` | 播报状态、声卡与真实/离线执行 / Qwen 合成模型 |
| `nodes/model_assets.py` / `nodes/{asr,tts}/assets.json` | 共用离线模型校验、各节点的固定模型清单 |

`launch`、`connect`、`step` 和 `System` 的调用保持原样。动作与任务消息不变；
节点退出改用 request/node/<node_id>/shutdown，Python serve_node 改用节点类和 options，
迁移说明见 [节点实现与启动](NODE_LAUNCH.md)。内部导入迁移：
`wrs_agent.actions` → `wrs_agent.executor`；
`wrs_agent.nodes.actions` → `wrs_agent.nodes.action_rpc`；
TTS 的 Mock、状态和后端归 `wrs_agent.nodes.tts` 下的 mock/state/backend/qwen；
ASR 的捕获、识别和 Mock 归 `wrs_agent.nodes.asr` 下的 capture/qwen/mock。
旧顶层 speech 包已删除，具体导入对照见 [节点实现与启动](NODE_LAUNCH.md)。
直接使用 ActionExecutor 的节点应把延迟/故障放进
自己的 handler；内置 SKILLS 只提供合同，需要显式绑定 handler。
领域参数不再从 `wrs_agent.skills` 或 `skills.contracts` 导出，改从
`wrs_agent.skills.robot` / `wrs_agent.skills.speech` 导入。添加内置技能的具体步骤见
[技能库](../wrs_agent/skills/README.md)。
Runtime 内部状态分别从 `execution` 与 `planning` 读取；调用方仍通过 snapshot、
task_status 和 goal_status 获取原有消息。规划协程在 `planning.worker`。

## 先运行这些入口

从仓库根目录的 PowerShell 运行，使用 Python 3.12；脚本默认调用当前 `python`，可通过 `WRS_AGENT_PYTHON` 选择本机解释器，依赖使用项目 `.local/deps`。新机器先按 [依赖说明](DEPENDENCIES.md) 初始化 WRS submodule、bootstrap 与 router。不要在开发任务中升级共享 Python 或 WRS gitlink。

```powershell
./scripts/run.ps1 examples/beginner/01_action.py
./scripts/run.ps1 examples/tasks/03_cancel.py
./scripts/run.ps1 examples/voice/01_text_stop_task.py
./scripts/run.ps1 examples/wrs/04_move_relative.py
./scripts/run.ps1 examples/wrs/01_move.py
./scripts/run.ps1 examples/wrs/02_cancel.py
```

这些机器人示例都需要已准备的 WRS 科学依赖；前三项理解动作、任务和停止，第四项验证实际方向移动。自定义节点的分终端启动步骤见下节。所有命令默认不访问付费模型、不启用硬件、不下载语音权重。WRS 依赖在干净机器的完整重建仍待验证。

## 建议拆给四位开发者的任务

| 分工 | 从哪里接手 | 第一项可验收交付 | 保留的边界 |
|---|---|---|---|
| WRS | `wrs_agent/env/wrs.py`、`examples/wrs/01_move.py`、[WRS 审计](WRS_AUDIT.md) | 补一项有明确前置条件和结果验证的虚拟机器人能力，独立节点可查询、取消 | WRS 导入只在适配模块；不能把同步运动塞进控制循环 |
| TTS | `wrs_agent/nodes/tts/backend.py`、`nodes/tts/qwen.py`、[Qwen 指南](QWEN_SPEECH.md) | 接手 Qwen speak 后端，验证真实声卡停止、短句延迟和播报质量 | 不依赖 WRS，不另建动作协议；真实播放停止后才能报告停止 |
| ASR | `wrs_agent/nodes/asr/node.py`、`nodes/asr/qwen.py`、[识别文本合同](VOICE_INPUT.md) | 接手 Qwen 中文短句输入，测试近讲/噪声与识别延迟；明确停止不经过 Planner | 采集/识别独立运行；不把 VAD 当停止；不自动下载权重 |
| UI | `wrs_agent/system.py`、[任务句柄](task_handles.md)、[错误合同](errors_and_versions.md) | 节点列表、文本输入、任务进度、取消、确认结束后创建新任务、UNKNOWN 展示 | 使用稳定 task_id；关闭观察不停止执行；状态与受理结果分开展示 |

每项提交包含实现、一条可运行示例、正常完成/取消/故障证据。先用 Mock 把接口联调，再接各自真实依赖。不要同时修改协议、Runtime 调度和后端；如果现有合同无法表达能力，先提出具体缺失字段与行为。

## Node 与 Skill 的完整例子

例子中 `speaker` 是直接继承 Node 的 custom 节点，仅提供新增 greet@1。它逐字打印到控制台，演示可取消的后端，不播放声音。

| 文件 | 职责 |
|---|---|
| `examples/nodes/greet_skill.py` | GreetArgs/Skill 合同与处理函数，仅节点导入 |
| `examples/nodes/bindings.toml` | speaker / agent 实例与传输 suffix，无逐技能配置 |
| `examples/nodes/00_start_router.py` | 独立 Router |
| `examples/nodes/01_start_speaker.py` | SpeakerNode 在 setup 中绑定 ActionExecutor，通过 serve_node 启动 |
| `examples/nodes/02_start_agent.py` | 直接启动 Agent，从节点发现合同 |
| `examples/nodes/03_call_skill.py` | 一次直接动作 |
| `examples/nodes/04_task.py` | Runtime 调度一次任务 |
| `examples/nodes/05_cancel.py` | 取消正在执行的动作 |

先按 [节点示例步骤](../examples/README.md#nodes) 在不同终端运行。端口为 7448，env_id 为 node-demo，各进程使用环境变量中相同的 WRS_AGENT_TOKEN。配置直接写在文件里，不靠命令行参数选择启动或调用模式。

添加技能只需要两处业务代码：

1. 定义 Pydantic 参数与 Skill，直接传 handler；SkillSpec/Schema 自动生成。
2. 把技能序列交给 ActionExecutor；多后端共享合同时才使用 MY_SKILL.bind(handler)。

Agent、客户端、中央目录、普通 TOML 都不用修改。执行器构造与
Node.add_skills(*skills) 共用同一个追加接口；启动后也可在节点所属线程显式调用。
重复名字拒绝覆盖，整批失败不留下部分注册，追加后下次查询刷新目录。
计划先由执行端批量做纯参数预检，再开始动作，已有任务固定合同和提供者。
详细接口与约束见 [技能库](../wrs_agent/skills/README.md)。

若只替换 speak 后端，从 `wrs_agent.skills.speech` 导入 `SKILLS` 和 `SpeakArgs`，复用既有合同并绑定处理实现；无需复制参数合同或新建 greet。机器人后端对应引用 `wrs_agent.skills.robot`。样例取消的边界是控制台字符间隔，真实播音必须提供真实输出停止确认。进程联调回归在 `tests/integration/test_developer_examples.py`，包含从其他工作目录启动与客户端退出后服务保持运行。

## WRS：先接虚拟能力

现有 WRS Node 已把固定版本 UR7E 接到公共动作协议。`examples/wrs/01_move.py` 展示运动和结果查询，`02_cancel.py` 展示取消，`03_new_action_after_cancel.py` 展示确认取消后接收新动作。同步 FK 在所属工作线程运行；控制先撤销旧权限，等在途调用返回后再确认停止。

当前真实 WRS profile 支持 observe / move_named_pose / move_relative，支持 home/B/C 命名姿态，以及世界坐标系每次最多 10 cm 的末端目标位移。独立节点、方向控制和只读 WRS viewer 见 [WRS 示例](../examples/README.md#wrs-虚拟机器人)。pick/place/物体 verify 和碰撞规划仍明确 unsupported；Mock 的抓取成功不能作为真实 WRS 能力证明。下一步可在适配器内加入已验证的夹爪、目标几何、碰撞与结果观测，再扩展对应技能。长时间规划宜放独立进程，设备控制保持单一所有者。

节点最终准入仍必须检查 boot_id、control_epoch、state_version、短期授权和资源占用；Runtime 的锁不替代节点校验。不能确认设备效果时使用 UNKNOWN，不能把“函数返回了”直接当成物理成功。参考 `tests/integration/test_wrs.py` 和 `tests/unit/test_wrs_boundary.py`。

## TTS：保持相同动作合同

先跑 console 示例，再替换合成/播放部分。重复相同 action_id 不重复播放；相同编号不同参数拒绝。取消请求受理与播放实际停止是两件事，后端要等待输出停止后才能报告确认。同步 SDK 调用不能阻塞控制循环；外部回调需要线程安全桥接。

状态结果可以继续复用 `wrs_agent.nodes.tts.backend.SpeechState`。完成后更新 completed/last_text；取消不冒充完成。若设备可能已产生声音但无法确定是否停止，处理函数应使用现有 ExecutionUnknown 路径，而不是普通失败或虚构成功。真实驱动的重启恢复策略必须按其可观测性确定，不能直接套用“Mock 历史全为终态即可接单”的结论。

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

动作/任务/规划结果的 state 分别为 ActionState、TaskState、GoalState，可从 wrs_agent 导入；使用字符串枚举，消息中的字符串值不变。状态结果主要是类型化对象；`system.status()` 的 Runtime 总览、`nodes()` 目录仍为字典。不要假设每个返回值都有相同字段。错误读取 error.code，UNKNOWN 要保留并显示。浏览器项目可随后在独立服务中包装这些 API；本轮不引入 Web 框架、前端依赖或新的控制协议。

## 在线模型：按线协议接入，不按厂商

两份独立在线文件：

- `examples/models/01_plan.py`：读取实际 WRS 状态/能力，在线模型只提出计划。
- `examples/models/02_execute.py`：LLMClient → ModelPlanner → Runtime → Zenoh → 独立 WRS 节点。脚本拥有 Runtime，不另启动 Agent。

配置 `LLM_PROTOCOL`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 后直接运行，会访问在线服务；没有离线回退或默认关闭开关。`.env` 不自动读取，凭据不能写进代码。协议回归样本位于 `tests/fixtures/models/`，只供测试；自动验收不调用真实模型。

常驻 Agent 的 CLI 使用 `-m wrs_agent launch --live-model`，Python 使用 `launch(live_model=True)`。默认不创建 Planner，显式 `start()`/`action()` 照常运行；`goal()` 返回 `planner_unavailable_or_busy`。模型失败保留结构化错误（`llm_*` 错误码），不换成 Mock 成功；明确停止不等模型返回，迟到结果失效。目前只有非流式单工具提案，没有流式输出或 GLM TTS。

`wrs_agent/planner/providers/` 的分层：

| 文件 | 负责 |
|---|---|
| `__init__.py` | `ModelRequest`/`ModelReply`/`ModelClient` 合同；Planner 只依赖它 |
| `llm.py` | `LLMConfig`（读 `LLM_*`、校验端点/代理/头）、`LLMClient`（HTTP、超时、大小上限、错误分类）、`PROTOCOLS` 表 |
| `wire.py` | 三种协议共用的系统提示、`propose_plan` 工具、`LLMError`、`LLM_EXTRA_BODY` 合并规则 |
| `openai_chat.py` / `openai_responses.py` / `anthropic_messages.py` | 各自的 `PATH`、`headers(key)`、`request_body(request, config)`、`parse_reply(data)` |

扩展方式按成本从低到高：同一协议上的新厂商只改环境变量；厂商私有字段放 `LLM_EXTRA_BODY`/`LLM_EXTRA_HEADERS`；新线协议（例如 Gemini 原生 `generateContent`）新增一个含上述四个名字的模块，加入 `PROTOCOLS` 与 `LLMConfig.protocol` 的取值，并补 `tests/unit/test_llm.py` 的夹具参数。非 HTTP 的模型（本地进程内推理等）直接实现 `ModelClient` 协议，交给 `ModelPlanner`。不引入厂商 SDK、LiteLLM 或 LangChain：三种协议的请求/回复都是小型 JSON，自己解析才能保证"最多一个提案、散文永远只是回答、未完成即拒绝"这些规则在每个厂商上一致。

## Mock 的保留边界

Mock 是同一套节点和消息接口的替代后端，不是另一套服务器框架。以下三类仍有测试用途：

| 保留项 | 用途 |
|---|---|
| `env/mock.py` | 无科学依赖运行调度；注入抓取失败、UNKNOWN 和停止确认故障 |
| `nodes/tts/backend.py` 的 make_mock_tts | 无音频设备验证并行、幂等、重启与只取消播报 |
| `nodes/asr/capture.py` 的 make_mock_capture | 无麦克风验证按键采集、取消、过期输入和文本路由 |

模型路径只使用 `LLMClient`。单元测试在 HTTP 层提供固定响应，Agent 多进程测试连接
`tests/llm_fixtures.py` 启动的回环 HTTP 服务；延迟和释放均由测试控制，产品没有测试 RPC。
默认 `launch()` 的机器人和语音仍使用 Mock，模型规划关闭；`backend="wrs"` 只选择机器人后端，不会同时启用真实模型或语音。
真实部署分别配置 WRS、Qwen TTS/ASR、在线模型；在线调用失败不会回退到 Mock。
WRS 虚拟机器人实际执行模型的 IK/FK，不能与 Mock 的物体状态修改混为一谈。

示例只保留需要模拟播报的并行任务和资源隔离取消演示，并注明不出声；取消动作、规划、
服务/客户端的重复 Mock 示例已移除，分别参考 WRS、在线模型、真实 TTS 和自定义节点示例。
Mock 服务/客户端测试程序位于 `tests/fixtures/connect/`，手写协议响应位于
`tests/fixtures/models/`。测试与示例索引同步更新；编号保留，避免无关重命名。

## 合并验收与后续范围

```powershell
./scripts/run.ps1 scripts/verify.py
./scripts/run.ps1 scripts/verify.py --wrs
```

后者增加 WRS 虚拟节点测试、全部有限机器人示例，以及独立节点、客户端和只读 viewer 验证。全部教学文件由 scripts/example_catalog.py 登记；有限时长脚本检查实际输出，常驻节点和独立客户端按组验证。真实命令、测试数量及限制见 [ACCEPTANCE.md](ACCEPTANCE.md)；机器报告生成在本地 reports/。本地 EXECPLAN 按仓库规则不上传，本文件是可提交的开发路线与交接合同。

当前优先补真实 ASR、本地可停止 TTS、WRS 虚拟抓放场景和 UI。动态接纳、context 重构、多设备所有权协调、跨机认证/ACL、持久任务恢复、性能基准分别立项；不作为这些后端开始开发的前置条件。真实硬件、真实音频质量、GLM 账号服务和干净机器 WRS 环境仍需单独验收。

## 小模块合并取舍（2026-09-25）

Runtime 的 TaskExecution、ExecutionState、PlanningState 只属于 Runtime，已放到 runtime.py 开头；
保留独立数据类与原字段，状态迁移仍在 Runtime，删除 runtime_state.py。
合并时按最新技能发现代码保存 bindings/specs/boots，未改调度、权限或取消算法。

nodes/builtin.py 已合并到 nodes/serve.py：内置列表、启动参数映射和单节点入口放在一起，
CLI 与 LocalStack 统一从 serve.py 导入；Node 生命周期仍在 node.py。

以下候选尚未合并。行数是审查时含空行/注释的近似规模。
判断顺序为：是否同一职责、是否真实共享/替换边界、合并后是否更易定位，最后才看文件大小。

| 候选 | 建议与规模 | 阅读和迁移约束 |
|---|---|---|
| skills/speech/definitions.py（29 行）+ 同包 __init__.py；robot 对应 118 行 + 包入口 | 各自收进技能包 __init__.py，约 30/120 行；不把两类技能混合 | 当前 definitions 只经包入口转导出；保留 __all__、SKILL.md 资源读取和无注册副作用，执行函数仍由后端绑定 |
| nodes/agent/rpc.py（56 行）+ node.py（52 行） | 可选，合并后约 100 行，优先级较低 | 只有一个生产调用方，但集成测试独立调用 register_runtime；若合并保留普通函数，不额外改成绑定方法。现有协议适配边界也有阅读价值 |

下列短模块建议保留：

- plan_validation.py：纯计划/资源依赖校验，独立算法和测试边界；不再扩大 Runtime。
- store.py：SQLite 日志、重启恢复和磁盘线程，与动作调度的职责不同。
- handles.py：任务/规划查询句柄，边界是结果身份和等待行为，避免继续扩大 System。
- nodes/options.py、instance_lock.py、scene.py、nodes/model_assets.py：分别被多个节点、进程或脚本使用。
- skills/contracts.py、catalog.py：共享定义类型与发现合同操作；包入口转导出后仍被多个组件复用。
- 模型协议适配、wire.py、providers 的公共类型，以及 ASR/TTS 的 qwen.py：共享类型或模型/协议替换边界。
- env/viewer.py：查看器服务生命周期，与机器人运动后端不同。
- 节点包 __init__.py 和数据资源：短小的包入口/资源文件正常存在，不把所有 Node 代码塞入包入口。

只有一个生产调用方不等于没有独立价值；纯算法、持久化、设备/协议适配即使很短，也可能更适合单独阅读。
完整扫描与调用方证据保存在 reports/runtime_merge_inventory.json、runtime_merge_review.json。
