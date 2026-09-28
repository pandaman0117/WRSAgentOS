# Node：实现、配置与启动

当前实现采用一层继承：WrsNode、TtsNode、AgentNode、VoiceNode、AsrNode 直接继承 Node。
Node 负责生命周期和通信资源，执行器、Runtime、Planner、设备后端仍通过组合使用。
普通使用者继续使用 launch/connect/step；只有开发节点时才需要接触 Node。

本文替代之前尚未实现的 NodeSpec 草案。没有引入 Module/NodeModule、Blueprint 类、
自动连线、插件发现或新的传输。DimOS 的参考版本与取舍见 [SOURCES](SOURCES.md)。

## 写一个节点

完整可运行的例子在 [speaker](../examples/nodes/01_start_speaker.py)。
其中 create_speaker 创建现有 ActionExecutor，Node 子类只需：

```python
from wrs_agent.nodes import Node
from wrs_agent.nodes.serve import serve_node

class SpeakerNode(Node):
    action_service = True

    async def setup(self):
        self.actions(create_speaker(self.journal))

# 在 async main 中运行；Router 地址和会话凭据与同环境节点一致。
await serve_node(
    SpeakerNode,
    node_id="speaker",
    endpoint="tcp/127.0.0.1:7448",
    env_id="node-demo",
)
```

节点通过 action_service 声明动作服务，执行器绑定技能后自动发布合同，不需要写入共享 TOML。
多个同类型节点可以共存，由 node_id 区分；每个动作节点仍独占自己的执行端点。
需要按角色选择 Agent、Voice 等服务时，可以用 peers 指定 node_id；未指定时只接受唯一的在线角色。
LocalStack/launch 的本地便捷配置仍限制每个内置角色一个进程，独立启动的节点不受这个清单限制。

自定义类只从受信任的本地 Python 传入，不接受配置文件中的类路径、网络插件或自动导入。
LocalStack/launch 当前只自动启动五类内置节点；自定义节点用自己的脚本调用 serve_node。

## 启动清单与运行时发现

`bindings.toml` 是 launch 的部署输入：决定启动哪些节点、使用什么后缀，并把本节点参数传给子进程。
Node 和 Agent 不保存完整部署清单；默认 `System.connect()` 也不读取它。
独立节点只需要自己的 node_id、通信域 site/env_id、Router endpoint 和业务 options。
默认服务地址是 env_id + "-" + node_id；suffix 可以显式覆盖。

| 对象 | 职责 |
|---|---|
| launch / LocalStack | 读取部署清单，启动、等待和关闭自己拥有的进程 |
| Node | 初始化本节点，发布描述和在线声明，持有本节点的资源 |
| NodeRegistry | 发现同一通信域内的节点，查询身份、地址、动作能力、技能及就绪状态 |
| Runtime | 选择执行节点，将节点实例和授权固定到具体任务，调度并记录结果 |

Registry 是持有者内部的普通对象，不是新增的注册中心进程。节点在统一的发现域声明在线状态；
Agent 和客户端可以各自查询目录，并直接连接实际的服务地址。
建立连接不会启动目标节点，也不等于目标已准备好。
`await registry.wait_for("speaker")` 用于等待加入；`registry.transport("speaker")` 取得已发现连接。
节点业务代码可用 `self.discover()` 获得由 Node 清理的目录，再等待依赖、调用 `self.connect(node_id)`。

晚加入节点的可运行示例是 [06_late_node.py](../examples/nodes/06_late_node.py)：
先启动 Agent 和客户端，再启动未写入部署文件的 GreetingNode，同一个客户端能直接调用，Agent 也能调度它。
节点退出后目录暂留离线描述，描述缓存满时回收离线项；相同 node_id 重启会产生新的 boot_id，旧任务不会沿用新实例。
重复身份或多个动作节点共用服务地址会使目录拒绝调度，本机还会在启动阶段检查实例锁。
不同 site/env_id 的发现互相隔离。

目录最多保留 64 项节点描述；全部在线时拒绝额外描述请求并报告
`discovery_capacity_exceeded`，已有不同地址节点继续工作。在线声明单独跟踪，最多 1024 个节点名、每名 16 个实例，
因此超额节点仍参与同址冲突检查。超出声明跟踪范围时暂停普通调度并报告容量不足，
下次刷新重新同步，容量恢复后可以继续使用。
回收描述不关闭旧任务仍持有的连接；连接仍按既有 128 个目标预算保留到目录关闭。
每技能只保留原提供者或歧义标记（最多 4096 项），不随历史节点数量无限增长。


技能选择与进程启动分开：`System.connect(skill_bindings={"greet": "speaker"})` 为客户端的
`action()` 和 `skills()` 明确选择服务提供者。`system.start()` 提交的任务由 Agent 自己选择提供者，
需要在 `serve_node(AgentNode, skill_bindings={"greet": "speaker"}, ...)` 中传入相同选择，
或在 launch 部署文件的 `[skills]` 中配置；客户端的选择不会隐式修改 Agent。
同名技能有多个已发现提供者时需要明确选择；某个提供者离线不能悄悄变成故障转移。
已有任务保留开始时选定的提供者、技能合同和启动实例。
显式传入旧 `bindings=` 的兼容入口只做边界转换，不把该文件作为动态发现的白名单。

## features、skills 和 options

- `features`：节点提供哪些功能，用字符串标签说明，例如 `task.coordinate`。
- `skills`：节点可以实际执行哪些操作，例如 `speak@1`。
- `options`：节点的启动设置，例如后端与预加载文本。

普通节点在类上声明功能：

```python
class AgentNode(Node):
    features = ("task.coordinate",)
```

动作节点通过 `self.actions(executor)` 装配，实际提供的技能从注册表生成。
features 是节点声明的功能标签，用于展示；不再从技能的要求反推出节点能力。
技能准入依据实际合同及执行器状态，动作授权仍由执行端检查。

`system.nodes()` 返回的节点信息使用 `features` 字段；底层动作客户端的
`await client.features()` 返回 `FeatureSnapshot`，包含完整技能 specs、版本、资源、boot_id、skill_revision 和停止范围。

动态技能接口与纯参数预检见 [技能库](../wrs_agent/skills/README.md)。

## 子类与基类各负责什么

| 接口 | 使用方式 |
|---|---|
| setup() | 子类初始化设备/模型，登记服务；完成后才公布节点存在和初始化完成 |
| teardown() | 可选业务清理；初始化失败或协程取消时也可能调用，须容忍部分初始化 |
| on_close(callback) | 获得资源后立即登记同步或异步清理；自动逆序执行 |
| actions(executor) | 绑定已有 Action 协议并接管执行器的关闭；类声明 action_service = True，或显式传 actions=True |
| add_skills(*skills) | 显式追加已绑定技能，启动和运行期间共用；拒绝同名覆盖，下一次查询可发现 |
| discover() / connect(node_id) | 创建并复用运行时目录 / 连接已发现节点；先等待依赖加入 |
| spawn(coroutine) | 管理后台协程；退出时取消并等待收尾，运行异常使节点退出 |
| transport | 既有 Transport，可登记 Query 和发布/订阅消息；消息边界仍用 Pydantic |

子类不需要调用 super().setup()/teardown()。构造函数只校验本节点参数，不开连接、
不加载模型、不启动线程；资源在 setup 中创建。同步阻塞设备操作仍在受控工作线程执行，
不能因继承 Node 就放进事件循环。常驻循环用 spawn 管理。
Voice、ASR 在 setup 中等待所需节点加入，等待可被取消，不另设短于依赖初始化的期限。
LocalStack 统一管理全栈启动期限：普通后端为 10 秒；任何已启用节点使用 Qwen 后端时，
所有节点及其间接依赖共享 300 秒的初始化预算。超时会取消等待并清理本次启动的进程。
独立调用 serve_node 时，由调用者管理启动等待期限或取消运行。

清理顺序为：teardown → 已登记资源逆序清理 → 所有连接 → 实例锁。
一项清理抛异常仍尝试其余资源，异常向调用者报告；节点关闭后不能重新连接或重复运行同一实例。
动作节点的停止与结果确认仍由 ActionExecutor/Environment 处理，取消后台协程不等于设备停止。
动作编号、epoch、幂等、UNKNOWN 和 Runtime 调度未另建一套实现。

Node 的资源、后台任务和默认列表都属于实例；不同 Node 不共享可变状态。
节点有界输入、普通请求和控制请求继续使用 Transport 原有隔离路径。

## 内置节点

| 类及文件 | 组合的业务对象 |
|---|---|
| [WrsNode](../wrs_agent/nodes/wrs/node.py) | WRS 或 Mock Environment |
| [TtsNode](../wrs_agent/nodes/tts/node.py) | Qwen 或 Mock 播报执行器 |
| [AgentNode](../wrs_agent/nodes/agent/node.py) | Runtime、Planner 和节点目录 |
| [VoiceNode](../wrs_agent/nodes/voice/node.py) | 文本分类与独立控制入口 |
| [AsrNode](../wrs_agent/nodes/asr/node.py) | 采集/识别后端与按键会话 |

[nodes/node.py](../wrs_agent/nodes/node.py) 是唯一公共基类；
[nodes/serve.py](../wrs_agent/nodes/serve.py) 集中内置名称到类的映射 NODES、
启动参数转换 node_options，以及选择、构造并运行节点的 serve_node。
AsrNode/VoiceNode 的请求处理是实例方法，setup 登记方法，teardown 收尾业务线程/任务。
Agent 的运行状态仍由 Runtime 拥有；agent/rpc.py 只保留无状态的 register_runtime 消息适配。
动作消息同样复用公共 action_rpc.py，不把执行器的状态机重复写进每个节点。

## VoiceNode 的职责

VoiceNode 接收已经识别或键入的文字，按本地规则分类并去重，再转成任务或控制请求；
它没有麦克风、识别模型或扬声器。ASR 负责声音转文字，TTS 负责文字转声音。

- 普通目标提交 Agent，查询读取任务状态。
- 明确停止通过独立控制通道交给 Runtime；仅停止播报则直接取消 TTS。
- 部分识别、含糊或否定的停止不执行控制；相同输入编号重试保持原目标。
- ASR 节点将普通识别结果交还调用方，由调用方决定何时提交；明确停止则立即转发 Voice。

这层可供语音和键盘共用。具体规则与回执见 [识别文本与任务中断](VOICE_INPUT.md)。
键盘等入口可独立于 ASR/TTS 模型发出控制请求，Voice 处理停止也不等待 Planner。
普通显式任务仍可直接使用 System API。

## 目录与扩展位置

```text
nodes/
  node.py                 # 共用生命周期与连接
  action_rpc.py           # 共用动作协议
  options.py              # Texts / Duration 共享约束
  model_assets.py         # 模型文件校验与离线 GPU 加载要求
  asr/
    node.py               # AsrOptions / AsrNode：配置、按键会话、结果、停止转发
    capture.py            # 麦克风录音 / 脚本文字采集
    qwen.py               # QwenASR
    assets.json           # ASR 固定模型清单
  tts/
    node.py               # TtsOptions / TtsNode：配置、装配动作执行器
    backend.py            # 播报状态、声卡播放、合成/播放协调、离线播报
    qwen.py               # QwenTTS
    assets.json           # TTS 固定模型清单
  wrs/                    # node.py：WrsOptions / WrsNode
  agent/                  # node.py：AgentOptions / AgentNode；rpc.py：Runtime 协议
  voice/                  # node.py；没有额外配置就不建空 options.py
```

各包的 __init__.py 只导出 Node 类；仍可 `from wrs_agent.nodes.asr import AsrNode`。
WRS Environment 适配器继续留在 env/，它是机器人动作的唯一入口。
技能参数与合同继续留在 skills/robot、skills/speech，供客户端与执行后端共同使用。

ASR 的旧 register_asr 曾同时持有会话、锁和 RPC，Node 只调用它，造成两个状态入口。
现在这些成员归 AsrNode，begin/end/result/health 是直接可测试的方法；
teardown 释放按键并等待采集线程退出。替换捕获后端可覆写 create_capture，
复用同一套幂等、过期输入与停止转发规则。
Voice 的去重记录与处理方法也归 VoiceNode，清理仍等待已持有的任务收尾。

TTS 通过 SpeechBackend 组合 render/play，把设备逻辑留在后端；TtsNode 只选择实现。
这与 WRS 的“公共机制、具体类、本地组件组合”相同；不需要新的 SpeechNode 基类或 mixin 层。
构造后端不自动下载模型；资源清单分别随节点打包，共用 model_assets.py 做校验。

## 每个节点的选项

配置类与 Node 放在同一个 node.py，先定义 Options，再定义使用它的 Node；未知字段被拒绝。
[公共 options.py](../wrs_agent/nodes/options.py) 只提供 Texts/Duration 两个共享字段约束；
场景文件校验归 WrsOptions，AgentOptions 的 live_model 控制是否创建 LLMClient。
自定义节点可设置 options_type 为自己的 Boundary/Pydantic 模型，通过 self.options 读取。

| 节点 | options 字段 |
|---|---|
| WRS | backend、duration、scene、fault |
| TTS | backend、duration、prepared_texts |
| Agent | live_model（默认 false，只接受显式计划；true 启用 LLMClient） |
| Voice | 无额外选项 |
| ASR | backend、script、vocabulary |

例如：

```python
await serve_node(
    "tts",
    options={"backend": "mock", "duration": 0.2},
)
```

配置复用使用普通 Python 数据，例如 SPEECH_OPTIONS 字典；不创建额外配置框架。
传输地址、身份、日志路径与业务 options 分开；options 不能覆盖节点身份、动作服务声明或技能选择。
凭据仍只从环境读取，在线模型须显式 live_model=True。未启用时 goal() 返回
planner_unavailable_or_busy；start()/action()、查询和控制仍可用。没有默认模型替身。

高层 launch/System.launch/LocalStack 使用 live_model=True 启用模型；model_provider 和 deferred 已删除。
其他参数在进程边界统一转换为各自的 options JSON。每个内置 Node 的 launch_options 只映射现有平铺参数到本节点字段，
serve.node_options 统一转换；LocalStack 不再逐个角色拼接后端参数，子进程按同一合同重新校验。
旧的 duration 参数仍同时用于 WRS 仿真和 Mock TTS；直接 serve_node 可以分别设置。
本轮未增加 NodeSpec 或新的 launch profile API。

CLI 保留 --backend、--tts-backend、--live-model 等便捷参数，也接受单节点 --options JSON。
两种业务配置写法不能混用；--options 不用于整组 launch。Python serve_node 的旧扁平后端参数
和 action_factory 已迁移：后端参数放 options，自定义执行器放子类 setup。

## 启动完成、动作准入与退出

LocalStack 在 Router 就绪后启动所有已启用的内置进程，再并发等待各自的
request/node/<node_id> 返回。启动不再依次等待 wrs → tts → agent → voice → asr；
进程创建顺序保留稳定，便于日志与诊断。

该查询在 setup 完成后才注册。成功回复表示初始化完成；回复中的 ready 仍沿用
“能否接收动作”的语义，HELD/UNKNOWN 不会被启动器偷偷改为 OPEN。
模型加载完成后才公布节点，默认等待 10 秒，Qwen TTS/ASR 为 300 秒。
launch 使用 requires 检查便捷启动清单是否完整；独立节点从目录等待所需角色，peers 可指定具体实例。
停止目标在初始化时确定，控制请求不会临时等待新一轮发现。

一项初始化失败或超时，TaskGroup 取消并等待其他就绪探针，LocalStack 清理自己启动的进程。
已有独立服务不会被接管。多个失败可能以 ExceptionGroup 返回。

生命周期退出入口统一为 request/node/<node_id>/shutdown，走原有控制队列并校验凭据。
旧 request/<role>/shutdown 已移除，仓库内调用同步迁移。
动作、任务和语音停止入口保持原样；退出受理不意味着物理停止已确认。

## 验证入口

```powershell
./scripts/run.ps1 -m pytest -q tests/unit/test_node_lifecycle.py tests/integration/test_custom_nodes.py tests/integration/test_dynamic_nodes.py
./scripts/run.ps1 scripts/verify.py --wrs
```

前者覆盖初始化失败、取消、清理异常、后台任务失败、并行初始化、custom 身份和独立退出，
以及没有共享部署文件的晚加入节点、重启授权失效、提供者选择、地址冲突和发现隔离；
完整验收还覆盖动作幂等、资源隔离取消、迟到规划、跨进程重连和 WRS 虚拟运动。
真实命令和结果见 [验收记录](ACCEPTANCE.md)。

## 功能名称迁移

为便于阅读，原 capabilities 统一改为 features：

| 原名称 | 当前名称 |
|---|---|
| Node.capabilities、NodeInfo.capabilities | Node.features、NodeInfo.features |
| SkillSpec.required_capabilities / required_features | 已移除；以实际注册的技能为准 |
| capabilities() | features() |
| CapabilitySnapshot | FeatureSnapshot |
| capabilities_extra | features_extra |
| request/capabilities | request/features |

仓库内的节点、客户端、Runtime、测试和示例已同步迁移，不保留旧名别名。
节点目录 JSON 和传给 Planner 的技能 spec 字段也一起改名，客户端与节点需要同批更新；
正在运行的旧进程需要重启。功能标签、技能名称和版本、动作参数及控制语义不变。

## 节点目录迁移

顶层 wrs_agent.speech 实现包已移除。ASR 的 QwenASR 从 nodes.asr.qwen 导入，
record_command/record_push_to_talk 从 nodes.asr.capture 导入；
TTS 的 SpeechBackend/make_speech_executor 从 nodes.tts.backend 导入，
QwenTTS 从 nodes.tts.qwen 导入。play_audio、SpeechState、make_mock_tts 同在 nodes.tts.backend；
make_mock_capture 与麦克风录音函数同在 nodes.asr.capture，旧 mock/state/playback 小文件已合并。

配置类由 nodes.<role>.node 导入，共用模型资源工具由 nodes.model_assets 导入。
旧 register_asr/register_voice 已移除；节点通过 setup/teardown 管理自己的方法和状态。
上面的 speech 包迁移仅描述历史目录调整。当前动态发现改动另行调整了 Node 构造参数、
节点描述字段和发现路径，并使 launch 清单与 connect 的运行时目录分离；用法见本文前半部分。
默认模型目录和语音解释器目录保持原样，已有模型校验回执仍可用。
