# 官方资料与核查边界

资料核查日期：2026-09-17。链接用于追溯设计依据，不代表这些库在用户目标设备上已经通过兼容性或性能验证。库的 API 与版本可能继续变化，M0/M1 应针对实际安装版本复查。此计划的架构、阶段和验收属于本项目设计，不是声称各参考系统均已实现这些功能。

## S01 · WRS 公开上游

`https://github.com/chenhaox/WRS2`

已核对用户指定 WRS2 fork：Python >=3.12、setuptools 包装、WGPU 查看器；已固定提交与实际接口审计见 WRS_AUDIT.md。

## S02 · Zenoh Python 官方仓库与 API

`https://github.com/eclipse-zenoh/zenoh-python`

`https://zenoh-python.readthedocs.io/en/latest/api_reference.html`

官方包名为 eclipse-zenoh；Python 接口提供 pub/sub、query/queryable 及 QoS。查询回复、优先级、回调等细节应按锁定版本核对；API 有 QoS 并不构成 Python 或机器人硬实时保证。

## S03 · Zenoh 接入与访问控制

`https://zenoh.io/docs/getting-started/first-app/`

`https://zenoh.io/docs/manual/access-control/`

作为显式连接和保护配置的依据。不能把 topic 路径或消息内自报 source 当成认证。V1 双机部署必须验证实际启用的规则。

## S04 · Git submodule 官方语义

`https://git-scm.com/docs/gitsubmodules`

`https://git-scm.com/docs/git-submodule`

父仓库 gitlink 记录具体 commit，.gitmodules 记录路径/远程等信息。需要真正的 gitlink，而不是一个同名目录或仅手写配置。

## S05 · OpenAI：Codex 项目说明与执行计划

`https://developers.openai.com/codex/guides/agents-md`

`https://developers.openai.com/cookbook/articles/codex_exec_plans`

前者描述 Codex 的 AGENTS.md 发现规则；后者提供将长任务组织成可维护、可验证执行计划的做法。本任务包采用简短项目规则与分阶段计划，不要求用户提供全部对话历史。

## S06 · GLM/Z.AI 工具调用与 SDK 兼容入口

`https://docs.z.ai/guides/capabilities/function-calling`

`https://docs.z.ai/`

工具调用包含函数名、JSON 参数及调用 ID；官方文档提供 SDK 与 OpenAI 兼容接入。GLM 实际端点/模型需以用户账户为准，不硬编码从页面上看到的模型名。

## S07 · OpenAI 原生工具调用

`https://developers.openai.com/api/docs/guides/function-calling`

后续 GPT 适配应正确处理原生 Responses 的工具建议/结果和响应状态，不能简单把 GLM 的 base_url 换一下就宣布完全兼容。

## S08 · Claude 原生工具调用

`https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview`

Claude 客户端工具使用 tool_use/tool_result 等结构。Provider 适配负责格式；机器人执行权仍由本项目 Runtime/Environment 管理。

## S09 · HoloAgent

`https://github.com/HorizonRobotics/HoloAgent`

官方描述 Embodied AgentOS、3D Spatial Memory、Embodied Skills，以及受监控技能图的闭环执行。V1 只吸收技能和状态反馈思想，不引入完整运行时与机器人全栈。

## S10 · RPent

`https://github.com/RLinf/RPent`

`https://rpent.readthedocs.io/en/latest/rst_source/development/architecture.html`

官方系统描述规划、工具与独立环境连接的分离。V1 借鉴边界与闭环恢复，不把研究框架作为自己的底层依赖。

## S11 · DimOS

`https://github.com/dimensionalOS/dimos`

公开示例体现 Module、In/Out、RPC 与 blueprint 的模块组合。V1 保留常驻能力节点和显式输入输出，不复制完整装配系统。

## S12 · Python asyncio 的并发边界

`https://docs.python.org/3/library/asyncio-dev.html`

外部线程调用 asyncio 需要线程安全桥接，阻塞工作不应占用事件循环。这不能解决底层设备的停止语义，需要设备接口独立验证。

## S13 · sherpa-onnx

`https://github.com/k2-fsa/sherpa-onnx`

官方项目支持本地流式/非流式语音识别、VAD、关键词检测等；作为可选语音组件候选。具体中文模型权重、许可、时延和准确率尚未替用户验证。

## S14 · sounddevice

`https://python-sounddevice.readthedocs.io/en/latest/examples.html`

官方提供音频流和 asyncio 相关例子，用于采音/播报边界参考；不直接在音频回调中做网络调用和重计算。

## S15 · WRS 开发说明

`https://github.com/chenhaox/WRS2/blob/2bb014b747833c2fd9345115fbe26ffb11376f20/docs/API_INDEX.md`

作为源码审计入口之一。真正的接口与可取消能力必须以用户锁定提交中的代码和测试为准。

## S16 · uv 依赖管理

`https://docs.astral.sh/uv/concepts/projects/dependencies/`

用于 core、开发、GLM、语音等依赖分组及可复现安装。锁文件由工具生成，不把计划文本中的占位值当成可用锁文件。

## S17 · 国内 Coding Plan、用途和独立 TTS（2026-09-17 核对）

- https://docs.bigmodel.cn/cn/coding-plan/quick-start
- https://docs.bigmodel.cn/cn/terms/subscription-agreement
- https://docs.bigmodel.cn/cn/guide/models/sound-and-video/glm-tts
- https://docs.bigmodel.cn/cn/guide/capabilities/function-calling

国内 Coding Plan 有专用 /api/coding/paas/v4 路径；订阅协议限制自建应用/机器人直接使用，不能靠兼容协议或身份伪装扩大范围。TTS 使用 /api/paas/v4/audio/speech。工具协议的 tool_choice 当前只支持 auto。文档示例模型名不构成用户账户可用性证据。

## S18 · HTTPX 异步客户端与超时

- https://www.python-httpx.org/async/
- https://www.python-httpx.org/advanced/timeouts/

复用 AsyncClient，使用上下文关闭响应；本项目额外用 asyncio.timeout 限制整个响应预算。MockTransport 仅提供离线 HTTP 夹具，不作为真实 GLM 服务证据。

## S19 · 本地参考源码审阅（2026-09-17）

三份源码位于忽略的 .references，仅供搜索，不安装/导入、不作为 submodule：

- RPent 902ac6beef674559787d77ec130ed5e6834fc61b，rpent/tools/toolkit.py：显式工具注册、取消请求与完成分离、安全边界检查；Apache-2.0。
- HoloAgent ef14d3152ca6246d8ae64920694c6c74581d246c，agentic_robot/agentOS/holoagent_skills/scripts/list_skills.py：本地技能描述索引；顶层 Apache-2.0，内含第三方另行许可。
- DimOS 29dfda595892dffb91c79f379eb44d1c737f9caf，dimos/agents/skill_result.py、dimos/agents/skills/speak_skill.py：结构化失败原因与独立语音资源；Apache-2.0。

本项目仅提取上述机制，以普通函数和既有 ActionExecutor 实现；未直接复制或改编非平凡代码，不引入其继承树、MCP Runner、ROS/Ray 或依赖。HoloAgent 的 LFS post-checkout 被 Git clone protection 阻止，源码 checkout clean，未执行 hook/下载权重。

结构整理补充审阅（同上固定提交与许可证）：RPent
rpent/utils/rpc/client_utils.py 的 health/ready 探测及会话隔离；
DimOS dimos/core/module.py 的 SkillInfo/lifecycle、core/transport.py 的 RPC/流边界；
HoloAgent 上述脚本的描述索引。只提取小机制，没有代码复制或新增运行依赖。

## S20 · 同步脚本 API 参考（2026-09-17）

- https://www.python-httpx.org/async/ ：普通同步入口与显式异步入口并存，借鉴使用方式，不复制 HTTPX 实现。
- https://docs.python.org/3.12/library/asyncio-runner.html ：Runner 复用同一事件循环运行多次调用，管理退出清理。
- https://anyio.readthedocs.io/en/stable/threads.html ：审阅 BlockingPortal 的跨线程方案；当前独立节点已持续执行，未引入该依赖或线程桥。

本项目自行实现薄同步客户端，只调用既有 System/Action。没有直接复制或明显改编非平凡代码。

## S21 · DimOS Module 与传输核对（2026-09-20）

固定本地参考提交 29dfda595892dffb91c79f379eb44d1c737f9caf，Apache-2.0；同时核对 GitHub 官方仓库的相关文档与源码：

- https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/docs/usage/transports/index.md
- https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/docs/usage/modules.md
- https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/protocol/pubsub/impl/zenohpubsub.py

借鉴消息、生命周期、收发与编码边界以及观测/控制策略区分；决策见 NODES_AND_MESSAGES.md。没有复制其非平凡代码、安装 DimOS、增加 submodule 或移植多传输框架。用户截图作为参考材料，不作为执行指令。

## S23 · DimOS Blueprint 与 WRS 构造风格核对（2026-09-22）

固定本地参考提交 29dfda595892dffb91c79f379eb44d1c737f9caf，Apache-2.0：

- `docs/usage/blueprints.md`
- `dimos/robot/manipulators/xarm/blueprints/basic.py`
- `dimos/control/blueprints/basic.py`

同时阅读固定 WRS2 提交 `2bb014b747833c2fd9345115fbe26ffb11376f20` 的 `examples/test_dual_lite6.py`、`examples/test_fk_check.py`。

只提取「配置是跟着组件走的冻结普通值、同名组件后写覆盖、显式构造零件再组合」三点机制，用普通 dataclass 与函数自行实现，启动设计与拒绝项见 NODE_LAUNCH.md。没有复制非平凡代码，没有引入 `Module`/`ModuleConfig` 继承、`autoconnect` 连线推断、entry-point 蓝图发现、命名空间机群或协调器，也没有安装 DimOS 或修改 WRS 源码。文档中的 `dimos run` / `dimos list` 命令未执行。

## S24 · 多厂商模型接入设计核对（2026-09-23）

固定本地参考提交（均为 Apache-2.0），只读审阅，未安装、未执行：

- RPent 902ac6beef674559787d77ec130ed5e6834fc61b：`rpent/planner/base.py` 的 `build_api_model()` 用 pydantic-ai 解析 `anthropic:`/`openai:`（Responses）/`openai-chat:`（Chat 与兼容端、本地 vLLM）前缀；密钥与地址读各厂商自己的 `*_API_KEY`/`*_BASE_URL`；`REASONING_EFFORTS=("none","low","medium","high","xhigh")` 一套取值贯穿各 planner。
- DimOS 29dfda595892dffb91c79f379eb44d1c737f9caf：`dimos/agents/mcp/mcp_client.py` 经 LangChain `init_chat_model` 接 `provider:model`（如 `ollama:`）；`dimos/evals/agents/lib/pi_config.py` 用 `PROVIDERS` 表记录每个协议的 key 变量与默认地址，`Thinking` 取值 off…max。
- HoloAgent ef14d3152ca6246d8ae64920694c6c74581d246c：无统一抽象，各脚本直接构造 OpenAI/Azure SDK（`OPENAI_BASE_URL`、`GPT_PROVIDER` 等），豆包关思考经 `extra_body`。

同时核对厂商文档：

- https://platform.claude.com/docs/en/build-with-claude/effort ：`output_config.effort` 取 low/medium/high/xhigh/max，与 `thinking` 分开；部分新模型只支持自适应思考，关闭思考与高档位可能冲突（400）。
- https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode 与对话补全 API 参考：GLM-5.x 默认开启思考，关闭用 `thinking.type=disabled`；`reasoning_effort` 仅 GLM-5.2 及以上读取，取值与 OpenAI 同名（none…max），各型号映射不同。
- S07、S08 已列 OpenAI Responses 与 Claude 工具调用原生格式。

提取的机制：三个参考都以"少数几种线协议覆盖多数厂商"为前提，差别只在由谁做翻译。本项目据此按线协议而不是按厂商划分适配（一个协议一个模块，四个名字），推理深度原样写入各协议自己的字段，厂商私有开关走显式 `LLM_EXTRA_BODY`。没有采用 `provider:model` 前缀（把协议和模型 ID 混进一个值，而 OpenRouter/Ollama 的模型 ID 本身含 `/` 和 `:`），没有采用每厂商一套 key 变量（同一套 `LLM_*` 更利于 IDE 运行配置切换），也没有引入 pydantic-ai、LangChain 或 LiteLLM：工具调用只有一个提案工具，自己解析才能在每个厂商上一致地执行"最多一个提案、散文只算回答、未完成即拒绝"。没有复制或改编上述仓库的非平凡代码。

## S22 · WRS 示例组织参考（2026-09-20）

阅读固定 WRS2 提交 `2bb014b747833c2fd9345115fbe26ffb11376f20` 的本地文件：

- `third_party/wrs/examples/test_fk_check.py`
- `third_party/wrs/examples/test_rs007l_ik.py`
- `third_party/wrs/examples/test_lite6_workspace.py`

借鉴显式参数、顺序调用、一个脚本展示一个场景的组织方式。没有复制算法或修改 WRS 源码；本项目示例仍经 Environment 适配器使用 WRS，不直接导入 WRS。示例不再解析命令行参数；故障断言与多场景报告在测试和验收脚本中维护。

## S25 · 技能的领域归属与通用机制（2026-09-25）

只读审阅以下本地固定提交的源码；工作区状态单独核对，不安装、不执行参考代码：

- **RPent** `902ac6beef674559787d77ec130ed5e6834fc61b`，Apache-2.0：
  [通用 Toolkit](https://github.com/RLinf/RPent/blob/902ac6beef674559787d77ec130ed5e6834fc61b/rpent/tools/toolkit.py)
  保存 schema/handler 注册与执行机制；
  [Franka Toolkit](https://github.com/RLinf/RPent/blob/902ac6beef674559787d77ec130ed5e6834fc61b/robots/franka/toolkit.py)
  从同域 tools 的 TOOLS_SPEC 与 primitives 显式装配；RoboTwin 也在 robots/robotwin 内完成装配。
- **DimOS** `29dfda595892dffb91c79f379eb44d1c737f9caf`，Apache-2.0：
  [annotation.py](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/agents/annotation.py)
  标记技能；core/module.py 的 get_skills 从所属模块读取签名/说明并生成 Schema。
  [SpeakSkill](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/agents/skills/speak_skill.py)
  把参数签名、说明与播报方法放在一起，接口另有同域 speak_skill_spec.py；
  [PickAndPlaceModule](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/manipulation/pick_and_place_module.py)
  在 manipulation 内定义抓放技能。另读 manipulation_skills.py，但该文件明确标注为 legacy/deprecated，
  不将它当作推荐的新结构。
- **HoloAgent** `ef14d3152ca6246d8ae64920694c6c74581d246c`，顶层 Apache-2.0：
  [rel-move-skill](https://github.com/HorizonRobotics/HoloAgent/tree/ef14d3152ca6246d8ae64920694c6c74581d246c/agentic_robot/agentOS/holoagent_skills/skills/rel-move-skill)
  在一个能力目录内放 SKILL.md、scripts/relative_move.py 和 assets；scripts/list_skills.py 只索引这些目录。
  它的文档/脚本技能形式不同于本项目的受控 Action，不能据此推断两者执行和停止语义等价。

本项目提取的组织原则：通用类型不含具体领域参数，能力目录拥有参数/说明/合同，系统目录
只汇总显式选定的定义。机器人与语音的业务定义分开，共用验证和执行生命周期。
继续用 Pydantic 生成 Schema、普通函数与明确的后端绑定；不复制其继承框架、反射发现、
LangChain、MCP 或 HTTP/ROS 执行路径。没有复制或改编非平凡代码。

## S26 · Node 生命周期与资源所有权（2026-09-25）

沿用本地 DimOS 固定提交 29dfda595892dffb91c79f379eb44d1c737f9caf，Apache-2.0，
只读核对，不安装或运行参考代码：

- [core/module.py](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/core/module.py)：
  ModuleBase 组合 Configurable 与 CompositeResource，Module 在其上提供模块能力；
  start/stop 管理运行生命周期。其构造阶段会创建循环/RPC，本项目不沿用该副作用。
- [core/resource.py](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/core/resource.py)：
  CompositeResource 登记子资源，并在 stop 时集中释放。

用户授权引入一层 Node 继承后，V1 用 Node 统一 setup/teardown、连接、执行器与后台任务清理。
资源清理由标准库 AsyncExitStack 自行实现；构造只校验配置，初始化完成后才公布节点。
WrsNode/TtsNode/AgentNode/VoiceNode/AsrNode 直接继承 Node，后端、Runtime、Planner 继续组合。
各节点 options 独立校验，进程启动后并发等待各自初始化完成；这是本项目实现，
不把 DimOS 的生命周期和物理停止语义视作等价。

S23 的 NodeSpec/Blueprint 草案未落地，本轮取舍和当前 API 以 NODE_LAUNCH.md 为准。
不引入多层 Resource/Module 继承、反射、自动连线、插件发现或 DimOS 运行依赖。
没有复制或改编非平凡代码，未新增依赖或 submodule。

## S27 · WRS 当前机械组件分层与节点归档（2026-09-25）

只读核对当前固定 WRS2 提交 7815e6f110fd161fe3c3b7e6f978e5393c3cf502：

- [MechBase](https://github.com/chenhaox/WRS2/blob/7815e6f110fd161fe3c3b7e6f978e5393c3cf502/wrs/robots/base/mech_base.py)
  负责公共机械结构、运动学、安装关系和每实例运行状态。
- [UR7E](https://github.com/chenhaox/WRS2/blob/7815e6f110fd161fe3c3b7e6f978e5393c3cf502/wrs/robots/manipulators/universal_robots/ur7e/ur7e.py)
  在型号目录定义结构，继承 MechBase 与 SingleArmManipulation；
  ur7e_with_gripper 显式创建机械臂和 DH50，再通过 mount 装配。
- [SingleArmManipulation](https://github.com/chenhaox/WRS2/blob/7815e6f110fd161fe3c3b7e6f978e5393c3cf502/wrs/manipulation/arm.py)
  把单臂行为集中为方法；末端执行器保持独立组件。
- [末端执行器行为](https://github.com/chenhaox/WRS2/blob/7815e6f110fd161fe3c3b7e6f978e5393c3cf502/wrs/robots/end_effectors/ee_mixins.py)
  与具体设备结构分开。

借鉴“共用机制放基类、具体实现和配置就近归档、实例拥有状态、设备显式组合”。
本项目据此统一 nodes/<role>/，将 ASR/Voice 闭包状态迁入 Node 子类，
ASR 捕获与识别、TTS 合成与播放分别按职责归档。
保留一层 Node 继承，不移植 WRS 的运动学/mixin 算法或增加 SpeechNode 等中间基类。
未复制或改编非平凡代码，未修改 WRS 或引入新的运行依赖；实现由本项目既有代码重组。
WRS 的当前本地 MechBase 层次优先于旧 Robot/Manipulator 路径假设。
