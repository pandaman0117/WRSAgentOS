# WRS-Agent V1

准备接手 WRS、TTS、ASR 或 UI 开发的同学，先看 [开发交接与分工](docs/DEVELOPMENT.md)，其中包含可运行的节点/Skill 例子、接入合同和验收入口。

第一次接触这个项目，可以先读 [从一个动作开始，读懂 WRS-Agent](docs/getting_started.md)：跟着可运行的例子，逐步理解技能、动作、任务，以及系统为什么这样分工。

已实现 M0–M3 的虚拟运行切片、M4 的 GLM 非流式适配与离线联调，以及 M5 本地技能库、严格条件缓存和一次恢复。单 Runtime/Planner、独立 WRS 虚拟节点或 Mock WRS、Mock TTS、Voice 识别文本输入与事件回放，通过真实 Zenoh router 跨进程通信。真实麦克风、ASR、有声 TTS 和 UI 待分工接入。

技能由 `configs/bindings.toml` 显式绑定执行节点。Runtime 按依赖和资源调度；WRS 只执行机器人技能，TTS 自己管理播报。Voice 可直接取消 TTS 或停止 WRS；查询和 VAD 不停止机械臂。模型等待不会占用控制路径。

先从 [入门示例](examples/beginner/01_action.py) 开始：

```powershell
./scripts/run.ps1 examples/beginner/01_action.py
```

[示例目录](examples/README.md) 按难度分为 beginner（一次动作、技能查询）、tasks（多步任务、缓存、WRS 虚拟模型）和 developer（协议、故障与模型适配）。前两组全部使用同步 API，不需要先学习 async/await。

普通 Python 脚本使用 `launch()`：

```python
from wrs_agent import launch

with launch() as system:  # 真 Zenoh + 独立 Mock 节点，退出时清理
    speech = system.action("speak", text="我正在处理")
    motion = system.action("move_named_pose", pose="B")
    print(motion.status())  # 只读查询
    speech.cancel()        # 只取消这次播报
    print(motion.wait())    # 此处才等待机器人动作完成
```

`launch()` 按 TOML 的 enabled 启动节点；默认配置包含 Agent、机器人、Mock TTS 和 Voice 文本/回放入口。
它启动本地 Zenoh，等待节点就绪，退出时清理自己启动的进程；本身不发送任务。
只需播报可用 `launch(bindings="configs/tts.toml")`，只需机器人用 `configs/robot.toml`。
`system.skills("播报")` 查询当前可用技能，无需手工创建客户端或能力字典。
返回值、同步调用的边界和本轮简化记录见 [API 说明](docs/api_simplification.md)。

已有节点在运行时，使用 `connect()`，调用动作的写法相同：

```python
from wrs_agent import connect

with connect(bindings="configs/tts.toml") as system:
    speech = system.action("speak", text="我已经连接")
    print(speech.wait().state)
```

启动程序与连接程序需在环境变量中设置同一个 `WRS_AGENT_TOKEN`（16–128 字符），
不要写进代码或 TOML。未设置时 launch 生成只供自身子进程使用的临时凭据；connect 不猜凭据。
默认连接本机 `tcp/127.0.0.1:7447`、`site="local"`、`env_id="arm01"`，可显式传入。
connect 退出只关闭自己的连接，节点和已接收动作继续运行；停止动作要显式 cancel。
异步程序可用 `System.connect()`；可运行的双程序步骤见 [连接示例](examples/README.md#connect)。

`action()` 收到接收回执就返回句柄，长动作在各节点继续并行执行。
`cancel()` 返回取消接收结果，随后 `wait()`/`status()` 确认终态。
`wait(timeout=...)` 超时只结束本次等待；需要停止时显式调用 `cancel()`。
只有普通脚本调用端被等待阻塞，独立 Voice/Agent/WRS/TTS 节点继续运行。

多步任务只需 `step(..., after=...)` 描述依赖，原 Runtime 调度不变：

```python
from wrs_agent import launch, step

with launch() as system:
    picked = step("pick", object="A")
    placed = step("place", object="A", target="B", after=picked)
    task = system.start(
        step("speak", text="我正在处理"),  # 与抓取并行
        picked, placed,
        step("verify", object="A", target="B", after=placed),
    )
    print(task.wait().state)
```

识别后的完整文本或 UI 输入可以通过同一个入口发送：

```python
receipt = system.send_text("put A in B", input_id="utterance-001")
planned = system.planning(receipt.request_id).wait()
if planned.task is not None:
    print(planned.task.wait().state)
```

`send_text("停止")` 在 Runtime 控制路径绑定并停止当前任务、撤销待返回的规划；重复相同 input_id 不会停止后来的新任务。
`send_text("停止播报")` 只取消当前 TTS；查询、附和和未完成识别不停止机器人。
回执只表示受理，STOPPING 仍需确认；自然语言修订不自动恢复运动。规则、重试和 ASR/UI 接入见 [语音文本合同](docs/VOICE_INPUT.md)。
演示：`./scripts/run.ps1 examples/tasks/07_voice_control.py`。这不是麦克风识别或硬件急停验证。

`start()` 返回 TaskHandle，`goal()` 返回 GoalHandle；`task.status/watch` 查询或迭代指定任务的进度，不调用 Planner。
`system.status()` 保留 Runtime 总览。规划结果、停止与替换语义见 [任务句柄与完整调用链](docs/task_handles.md)。
`nodes()` 直接查询配置中的节点、技能、能力和 ready。Skill Registry 描述技能，
Node Registry 描述当前执行者；配置决定绑定，模型只提出技能。
节点以 `{"speak": 1}` 声明实现的技能版本，复用技能库中的唯一参数合同；版本不匹配时整项任务在派发前拒绝。
失败可通过 `result.error.code` 或 `AgentError.error` 读取，不必解析异常文本。见 [错误与技能版本](docs/errors_and_versions.md)。
在线实例由 Zenoh Liveliness 通知，能力按 boot_id 缓存；ready 仍查询节点，提交前校验当前授权。多实例歧义时拒绝执行；Vision 仍只有 disabled 声明。

`launch(backend="wrs_virtual")` 使用真实 WRS FK 虚拟节点，不连接硬件；
当前 WRS profile 仅支持 observe/move_named_pose，pick/place 例子使用 Mock。
同步入口适用于普通单线程脚本。已有异步程序继续使用
`async with System.launch()`，方法语义相同。同步包装仅复用一个标准库
`asyncio.Runner`，不新增后台事件循环线程、依赖、调度器或协议。

节点无需共同继承基类。内部只有一种 ActionClient，WRS/TTS 共用动作协议；
RobotClient 子类已删除。普通用户用 system.action，不必选择或组装 Client。
机器人节点额外提供 hold/resume 服务，TTS 不提供；
取消只结束指定播报，确认结束后新请求可用新授权开始，不续播旧内容。
机器人适配器统一放在 `wrs_agent/env/`；旧 `environments/` 转发目录已删除。
Action 客户端和服务绑定集中在 `nodes/actions.py`，Planner 接口和计划校验集中在
`planner/__init__.py`。技能描述不再带默认节点，执行位置只由 TOML 配置决定。

Zenoh 协议 v3 使用前缀 wrs/v3/{site}/{target}（target 由节点配置 suffix 确定）。
精确 Query：request/node/{node_id}、request/action/context、request/action/status；
Action：request/action/submit、request/control/cancel；Event：events/action。
WRS 另有 request/snapshot、request/control/hold|resume。Agent 提供 request/task/*
及 request/nodes；Voice 直接使用目标节点的控制服务。env_id 字段保持原含义；信封 schema_version=3，客户端与节点须同时升级。
`system.snapshot()` 默认查询机器人，`system.snapshot("tts")` 查询播报节点；每次只读一个节点。
返回的 `node_id`、`boot_id`、`state_version`、`captured_at_ns` 说明来源、实例、业务版本和采集时间，
`data` 是该节点的类型化业务数据：机器人读 `.data.pose`，播报读 `.data.completed`。
这不是全系统在同一时刻的聚合视图；采集时间来自源节点时钟，也不代替观测有效性检查。
`state_version` 表示该节点的业务状态版本；control_epoch 单独约束执行权限，两个版本分别校验。

`snapshot()` 只读状态，不签发执行凭证；底层调用者通过 `context()` 取得当前状态及 `lease_id`，然后提交动作。普通 `system.action()` 自动处理，不需要用户填写。旧 `snapshot().lease_id` 调用需要迁移。


运行环境固定为 `D:\code\venv312\.venv\Scripts\python.exe`（3.12.0）。`scripts/run.ps1` 使用该解释器和项目 `.local/deps`，不修改共享虚拟环境。

在本目录的 PowerShell 中运行：

```powershell
git submodule update --init --recursive
./scripts/bootstrap.ps1
./scripts/install_router.ps1
./scripts/run.ps1 examples/beginner/01_action.py
./scripts/run.ps1 examples/tasks/01_parallel_and_stop.py
./scripts/run.ps1 scripts/verify.py
```

也可直接指定解释器，通过同一个项目启动入口运行：

```powershell
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py examples/beginner/01_action.py
```

在 IDE 中运行时，将脚本设为 `scripts/run.py`、参数设为 `examples/beginner/01_action.py`、解释器选项设为 `-X utf8 -S`，工作目录设为仓库根目录。这会加载项目锁定依赖；仅选择同一个 Python 而直接运行示例，仍可能加载共享环境中其他版本的包。router 版本检查支持 `RUST_LOG=info/debug` 产生的前置日志，真实版本不匹配时会显示期望版本、路径和实际输出。

tasks/01_parallel_and_stop 演示四个独立节点并行、查询不打断、Voice 直连取消 TTS 与停止 WRS。输入是明确标注的结构化事件回放；不是 ASR，也不是云模型理解结果。developer/02_mock_interrupt 进一步演示并行动作、挂起的 Mock 模型等待、只取消 TTS、持物停止、拒绝旧动作/旧模型结果，以及重新规划到 C。结束时清理自己启动的进程。前台持续运行用 `./scripts/run.ps1 -m wrs_agent launch`，Ctrl+C 停止。

`wrs_agent/__main__.py` 是 Python 标准的命令行入口：`python -m wrs_agent` 会执行它。
它读取参数，启动 `wrs`、`agent`、`tts`、`voice` 中的一个节点，或用 `launch` 启动本机系统；
普通脚本仍用上面的 `launch()`。节点的任务循环和动作执行留在各自实现中。
可用参数通过 `./scripts/run.ps1 -m wrs_agent --help` 查看。

已通过单元、真实 Zenoh/Mock 和真实 WRS FK 节点测试、示例、Ruff 和 doctor；各层级的最新数量与命令见 docs/ACCEPTANCE.md。GLM 为离线 HTTP 夹具，不是真实云服务验收。verify.py 会在本地 reports/ 生成验收结果。开发助手指令、执行计划、IDE 配置和机器报告保留本地，不提交远程。

通信只有三种语义：

- Event/Stream：发布事实和进度，多订阅者直接接收；事件可能丢失，状态查询补偿。
- Query：能力、状态等短请求；控制服务有独立有界入口。
- Action：快速 ACCEPTED，随后进度/终态、按 ID 查询和取消；WRS/TTS 共用同一合同。

默认每个动作节点最多一个冲突资源动作，最多 12 步任务、16 项追加任务、4096 条会话动作/控制记录；达到容量明确拒绝，不删除去重历史再重放。每次确定计划使用独立 task_id；替换生成新 ID 并记录 supersedes。动作 ID、节点 boot_id/epoch、短期授权和停止确认仍各有职责。task_revision 只保留为线路兼容字段，新 Runtime 固定发送 0。

默认只连接回环 router，关闭自动网络发现；凭据由启动器生成，经环境变量传给自己的子进程，不靠 source/category/节点名称授予权限。该配置仅用于受信本机 Mock/WRS 虚拟节点，远程身份绑定与 ACL 尚未实现。网络拥塞/查询丢失返回错误或超时，不自动重发物理动作。

WRS submodule 固定到用户指定 [chenhaox/WRS2](https://github.com/chenhaox/WRS2) 的 `2bb014b747833c2fd9345115fbe26ffb11376f20`。真实 WRS Lite6 命名姿态运动、进度/查询与取消/恢复准入已通过；详情见 [docs/WRS_AUDIT.md](docs/WRS_AUDIT.md)。本任务未修改原有本地 WRS2 工作拷贝。

尚未完成：WRS 抓取/放置及碰撞验证、GLM 真实账号服务验证、独立 Vision 节点、真实 ASR/TTS/麦克风、双机保护配置和负载基准。WRS profile 使用真实模型的 FK 虚拟运动；Mock/TTS 测试不是实机或真实音频证据，实机后端不可选择。

GLM 客户端已支持国内智谱的 OpenAI 兼容 Chat Completions，复用 ModelPlanner，默认仅运行原生 tool_calls 的离线 HTTP 夹具：

```powershell
./scripts/bootstrap.ps1 -Extra glm
./scripts/run.ps1 examples/developer/03_glm_adapter.py --dry-run
```

输出明确包含 network=false、actions_submitted=0。端点为 `https://open.bigmodel.cn/api/coding/paas/v4`，没有客户端身份伪装。环境变量见 .env.example；该文件不自动加载。模型名必须填写账号实际支持值，密钥只从进程环境读取。

具备对应服务使用权限后，在本机环境设置 GLM_API_KEY、GLM_MODEL 和 GLM_BASE_URL，再执行 `./scripts/run.ps1 examples/developer/03_glm_adapter.py --live-model --dry-run`。示例只返回计划建议，不启动动作节点。运行节点仍默认 MockClient；Runtime 已可用 --model-provider glm --live-model 显式选择现有 GLM 适配器。需先完成独立 dry-run 服务验收，本轮未发送真实请求。

适配器保留原生 message/tool_calls 和 usage 于内存，拒绝多工具、未知工具及未完成/拒绝响应。工具参数原样交给 ModelPlanner，统一拒绝非法 JSON、越权字段及错误计划；没有自动工具执行。当前只接受非流式请求，stream=true、未知参数和 Claude 协议在配置时失败。客户端复用连接，设置总超时，至多重试一次建连；HTTP 错误不重试、不跟随重定向、不切换计费端点。原生内容和凭据不写日志。

[官方套餐协议](https://docs.bigmodel.cn/cn/terms/subscription-agreement) 对自建应用/机器人调用有用途限制，协议兼容不改变授权范围。Coding Plan 聊天端点不能用作 TTS；[glm-tts](https://docs.bigmodel.cn/cn/guide/models/sound-and-video/glm-tts) 使用独立的普通 API `/api/paas/v4/audio/speech`，本仓库未接入或调用该服务。

本轮新增的可运行入口：

```powershell
./scripts/run.ps1 examples/tasks/03_wrs_scene.py
./scripts/run.ps1 examples/tasks/03_wrs_scene.py --cancel
./scripts/run.ps1 examples/beginner/02_skills.py
./scripts/run.ps1 examples/tasks/02_cache_reuse.py
./scripts/run.ps1 scripts/verify.py --wrs
```

tasks/03_wrs_scene 是 headless 场景：独立 WRS Node 使用真实 Lite6，输出 ACCEPTED、进度、关节/FK 状态及停止反馈；Runtime 随后调度回到 home。控制先撤权，等待在途同步 FK 返回后才确认停止。该 profile 没有经验证的夹爪/目标场景，pick/place/物体 verify 与碰撞规划明确 unsupported。默认 verify 不加载 WRS 科学依赖；--wrs 才增加真实虚拟节点检查。科学包来自指定 Python 已有环境，干净机器恢复全部 WRS 依赖尚未验证。

[技能库](wrs_agent/skills/README.md) 的机器合同在 `wrs_agent/skills/__init__.py`；中文别名/标签只负责候选检索。Runtime 对整份计划先检查节点能力，再启动动作。候选检索缓存与计划缓存分别计数，进度不调用 Planner。

计划缓存仅在任务实际验证成功后保存严格四步转移模板，最多 64 项。命中要求相关对象位置、标定、技能合同与能力仍匹配；每次执行重新获取授权和动作 ID。否定、数量、时序或未知模板不自动复用。tasks/02_cache_reuse 示例的 model_calls 为 1→1→2→3：第二次命中，改目标和相关状态变化拒绝旧模板。计数来自独立 Agent 内的脚本化 Mock ModelClient，经真实 Zenoh 执行，不声称节省真实 GLM 请求。Mock 只支持严格转移模板与明确的 home/回原位指令；其他输入返回 CLARIFY，不默认执行运动，不代表自然语言理解。

恢复仅对明确的定位/抓取失败执行一次 observe 后重试，且夹爪/对象状态明确、任务仍有效且 boot/epoch 未改变；新尝试使用新 action_id。UNKNOWN、权限/前置条件错误与停止未确认不重试。测试可用 grasp_once/localization_once 注入瞬时失败；这不是物理故障恢复认证。

参考源码 .references/RPent、HoloAgent、DimOS 只读搜索，不是运行依赖或 submodule，不上传到父仓库。借鉴机制和 commit/license 记录在 docs/SOURCES.md。
