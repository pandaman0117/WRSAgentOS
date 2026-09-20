# API 小步简化记录

最新接口见 [任务句柄与完整调用链](task_handles.md) 和 [错误与技能版本（协议 v3）](errors_and_versions.md)。此前章节保留阶段历史；旧导入兼容层现已移除。

## 基线和本阶段范围

2026-09-17；checkout：`b69bd7abe1e16049651908f080d1571cd0c34535`。
上一阶段开始时 `git status --short` 为空；2026-09-18 本轮承接其未提交改动。
两轮均没有切分支、reset、commit 或 push。最新切片见文末，以下接口表已同步。
历史报告是 160 项通过；本轮结果单独记录，不把历史结果当作复测。
保留 TOML 配置与现有 Python 启动代码。本阶段完成目录、技能说明、同步检索示例和
接口语义审计后停止；不实现新的 Agent Loop、启动框架或并发客户端。

## 普通脚本怎么用

入口已经是 `from wrs_agent import launch`，内部已有同步包装。
一次动作只需操作两个对象：`system`（系统入口）、`action`（这一次执行）。
不需要用户创建 Runtime、Planner、传输对象或控制授权。

```python
from wrs_agent import launch

with launch() as system:
    action = system.action("move_named_pose", pose="B")
    result = action.wait()
    print(result.state, result.verification)
```

进入 with 启动 Zenoh、Agent、Mock WRS、Mock TTS、Voice replay，检查 ready；退出清理
自己启动的进程。`launch()` 本身不发任务或付费模型请求。`bindings=` 仍读取现有
`configs/bindings.toml`；它描述节点/技能对应关系，尚不是完整启动清单。

本轮用户代码变化是技能检索，动作代码保持原样：

```python
# 之前：异步读取各节点能力，再手工交给 lookup_skills。
async with LocalStack(runtime=False) as stack:
    caps = {name: await RobotClient(bus).capabilities()
            for name, bus in stack.node_transports.items()}
    skills = lookup_skills("播报", caps)

# 现在：复用已经启动的系统，普通同步调用。
with launch() as system:
    for skill in system.skills("播报"):
        print(skill.name, skill.description)
```

## 返回时间、结果和失败

| 方法 | 何时返回、返回什么 | 失败/注意点 |
|---|---|---|
| `system.action(...)` | 节点受理后返回 Action；首次 receipt.status 是 ACCEPTED | 不保证已开始运动；拒收抛 ValueError；提交超时按原 ID 查询，仍不明则抛 UNKNOWN 错误，不盲重发 |
| `system.start(*steps)` | Agent 接收后返回固定 ID 的 TaskHandle | 这是任务状态；后台节点预检查和动作可能还没开始；参数错误或任务忙会拒绝 |
| `system.goal(text)` | 返回 GoalHandle，规划在后台进行 | 确定计划后才产生 task_id；revision=0 仅作兼容，默认 Mock 不是通用语言理解 |
| `action.status()` | 返回当前 ActionStatus，找不到可为 None | 传输错误/超时会抛异常 |
| `action.wait()` | 返回终态 ActionStatus | FAILED/CANCELLED/UNKNOWN 也作为结果返回；并非只返回成功；状态缺失抛 RuntimeError(UNKNOWN) |
| `task.wait()` | 返回指定任务的 TaskStatus 终态 | HELD 不是完成；超时不取消执行 |
| `goal.wait()` | 返回规划结果，可带已接收任务的句柄 | 不等待任务执行 |
| `action.cancel()` | 返回 ControlReceipt，包含 accepted、phase、reason | STOPPING 表示仍在停，STOPPED 才确认；拒绝通常是 accepted=False，不自动抛异常；重复请求返回原回执 |
| `hold(...)` | 下层 RobotClient 返回 ControlReceipt；Runtime.hold 返回任务字典 | 任务级 hold 必须指定 task_id；设备 stop 不依赖任务；接收不等于已停止 |
| `system.resume()` | 返回 ControlReceipt | 只重新允许新动作，不续跑旧动作；停止未确认会拒绝 |
| `result()` | 当前没有这个方法 | 示例中的 result 只是变量，保留 wait 一个等待名字 |

所有 wait 的 TimeoutError 都只结束等待，不隐式取消设备动作。成功需查看
`state == "SUCCEEDED"` 和 `verification == "PASS"`。控制回执不是不断更新的状态对象；
重复 cancel 可能仍返回原 STOPPING，应另查 status 或 wait。RPC 的拒绝可表现为
RemoteError，不能把网络错误当作设备已停止。

## 不调用 API / 等待期间能否继续处理

- **独立节点进程**：可以继续。`launch()` 的 Agent/WRS/TTS/Voice 各有循环；普通
  `time.sleep()` 期间远端动作仍完成，已有真实 Zenoh 集成测试覆盖。
- **调用端本地协程**：当前 Runner 只在同步方法内部运行。调用端休眠、或 watch
  迭代后在用户代码中计算时，本地处理暂停；Python/Zenoh 后台线程仍可能接收并缓冲数据，
  不能把这一点称为本地 asyncio 处理一直在推进。
- **同进程 Runtime**：如果依赖这个 Runner，暂停调用也会暂停它；新增测试直接用
  本地 Runtime/Mock Planner 验证。不能用“远端在执行”证明本地协程仍运行。
- **同一同步客户端**：wait 阻塞所属调用线程；另一线程调用被明确拒绝。
  因此当前不能在一个同步 wait 尚未返回时，通过同一同步 Session 发控制。
  可以用短超时后发取消；需要同客户端并发时使用现有异步 System。
- **同一异步客户端**：wait 会让出事件循环，可并发发 cancel/status；新增真实 Zenoh
  测试在 Planner 挂起时等待并取消动作，验证共享客户端没有全局等待锁。
- **模型与锁**：Runtime.goal 只启动后台规划，模型等待不占 RPC worker；GLM 是异步
  HTTP。普通动作锁按节点分开，hold 不取它；SQLite 写入和 WRS FK 已移到各自工作线程。
  自定义 Planner 若在 async 方法中执行阻塞计算仍能堵本地循环，不能靠 async 关键字解决。
- **尚存的串行点**：每个 Transport 两个普通 worker、一个控制 worker；单个控制
  handler 若等待外部节点，会阻塞该控制队列。Voice 等 TTS 回复可能拖住后来的 WRS stop。
  这不是本轮已修复问题，也不能称为最快响应。旧诊断单次约 251ms，不是 P95 或实机制动。

后台线程不是被禁止的方案。本阶段保留已验证的同步单线程使用范围，不默默改变
线程所有权；以后若要求同步 wait 期间共享同一客户端控制，应单独实现并验收。

## 优先问题（最多 8 条）

| 分类 | 问题 | 本阶段处理 |
|---|---|---|
| 同步入口 | 技能示例要求手工组装异步客户端 | 已增加 system.skills(query)，09 示例改为普通 Python |
| 同步入口 | 本地循环暂停、同一同步客户端不能并发控制容易被误解 | 已记录并测试；并发同步客户端留待单独切片 |
| 语义和命名 | ACCEPTED、任务 RUNNING、取消受理容易被当作完成 | 修正文档字符串并列出真实返回语义；不更改协议 |
| 语义和命名 | Voice 的一条控制请求可能等待另一节点 | 记录为待修复；直接节点控制与模型等待隔离回归保留 |
| 删除冗余 | 机器人适配目录名称长，旧客户端别名混淆 | 主实现迁到 env；WRS 用 RobotClient，TTS 用 ActionClient；旧导入仅转发 |
| 删除冗余 | 根 skills/README 与 skills.py 分散 | 归入一个 skills 包，附两份实际供 Planner 使用的说明 |
| 文档 | 技能格式来源和可执行权限不清楚 | 核查 Agent Skills/HoloAgent，说明格式兼容不等于执行授权 |
| 文档 | README 过早出现内部术语与完整启动清单误解 | 增加小例子和本记录入口；保留现有 TOML，未新建 launch 文件体系 |

已经合理、不需修改：单 Planner；独立节点并行；统一 Action/Query/Event；同步薄包装
调用原异步实现；明确 step(after=...)；动作和控制 ID 去重；boot/epoch/执行身份校验；
停止确认；丢回执后状态查询；UNKNOWN 不盲重试。没有新增 TaskHandle 或通用基类。

## 文件、公开名字和中间层

- 实现 `environments/mock.py,wrs.py` → `env/mock.py,wrs.py`；旧路径保留函数转发，
  WRS 导入仍只有 env/wrs.py。旧模块内部符号的 monkeypatch 不属于兼容保证。
- `skills.py` → `skills/__init__.py`；`from wrs_agent.skills import ...` 保持可用。
  技能函数与 Mock 状态暂时保留在同一模块，避免本阶段连带拆解执行实现。
- 新增 `skills/robot/SKILL.md`、`skills/speech/SKILL.md`，根技能 README 移入包。
  pyproject 声明随包资源；没有动态目录扫描或外部代码加载。
- 新增用户方法：同步 `Session.skills(query="")`、异步 `System.skills(query="")`。
  返回当前 ready 节点支持的 SkillSpec 副本，不调用 Planner 或执行动作。
- 新增描述字段 `SkillSpec.instructions`。现有 PlanRequest.skills 自动携带；
  原生 GLM HTTP 离线夹具检查实际收到说明；说明变化使旧计划缓存失效。
- 删除公开名字：无。顶层 launch/System/step、现有动作/任务方法保持。
  新增导入路径 env；原 environments 与 nodes/environment 兼容入口暂保留。
- 新增运行中间层：无。只有两份旧路径的直接导入转发；不增加 Manager、后台
  调度线程、依赖或自动装配。测试/示例/doctor 的路径修改为机械迁移。包内 Python 净增加 43 行（含文档字符串和兼容导入）。

## 参考资料

- HoloAgent `ef14d3152ca6246d8ae64920694c6c74581d246c`，
  `agentic_robot/agentOS/holoagent_skills/README.md`、`skills/arm-skill/SKILL.md`：
  借鉴短说明与目录组织。其 name/description + Markdown 形式与公开 Agent Skills
  相似；没有验证整个 HoloAgent 技能集合的规范合规性，不声称官方认证。
- RPent `902ac6beef674559787d77ec130ed5e6834fc61b`，`rpent/planner/base.py`、
  `docs/source-en/rst_source/development/interfaces.rst`：借鉴入口、参数、返回值和预算
  写清楚的接口表达，不复制其 solve 循环、Toolkit 继承或工具 Runner。
- DimOS `29dfda595892dffb91c79f379eb44d1c737f9caf`，`docs/usage/modules.md`：
  借鉴从一个模块开始、明确输入/输出和 start/stop 的教程写法，不移植框架。
- [Agent Skills 开放格式](https://agentskills.io/specification)及
  [官方介绍](https://agentskills.io/home)，2026-09-17 读取成功：
  SKILL.md 包含 name/description 头部与正文，可配资源；格式已被多种工具采用。
  本项目只借鉴说明文件格式，不提供通用 Agent Skills 执行器，也未运行 skills-ref。

上述本地仓库顶层为 Apache-2.0；只借鉴接口表达，未复制非平凡实现。
`robot`/`speech` 是说明分组，原可执行技能名不变；说明不新增权限。

## 实测结果与未验证

- 针对性命令：`./scripts/run.ps1 -m pytest -q tests/unit/test_sync_runner.py tests/unit/test_skills.py tests/unit/test_cache.py tests/unit/test_wrs_boundary.py tests/integration/test_sync_api.py tests/integration/test_system.py tests/integration/test_glm_runtime.py`：**52 passed，46.17s**。
- 完整命令：`./scripts/run.ps1 scripts/verify.py --wrs`：**134 unit + 32 Zenoh/Mock + 5 WRS virtual = 171 passed**，0 failed/errors/skipped；原 160 项保留，新增 11 项。
- 01/02/04/05/09/10 示例、03 完成和取消、doctor、Ruff 全部 PASS。
- 最后将示例/测试的 TTS 改用通用 ActionClient 后，执行 `./scripts/run.ps1 -m pytest -q tests/integration -m 'zenoh and not wrs' --junitxml=reports/zenoh.xml`：**32 passed，5 deselected，81.12s**。deselected 是独立 WRS 分组，非失败或跳过。
- 同时重跑 `./scripts/run.ps1 examples/02_mock_interrupt.py`、`./scripts/run.ps1 examples/05_cache_reuse.py` 和 `./scripts/run.ps1 -m ruff check wrs_agent tests examples scripts`：均通过；缓存模型调用仍为 1→1→2→3。
- 初次 Ruff 发现新测试一处导入顺序和一处长行，已修正并复测；未删除旧测试或降低断言。
- 证据：`reports/api_simplification_summary.json`、`acceptance.json`、`unit.xml`、`zenoh.xml`、`wrs.xml`。指定 Python 3.12.0，Zenoh/zenohd 1.9.0；WRS 指针未变。

新增测试覆盖本地 Runtime 暂停、失败/取消/未知终态、缺失状态、同步检索无副作用、
同一异步客户端在模型挂起时等待并取消、包内技能说明和旧导入兼容、说明变更使缓存失效。
原有 GLM 离线网络测试增加了实际请求中技能说明的断言。

未验证：真实 GLM、真实 ASR/TTS、实机、跨机部署、延迟分位数、安装 wheel 后
脱离 checkout 的独立运行。WRS 只验证既有虚拟 FK 能力；本轮不扩展抓取能力。


## 2026-09-18：任务身份和原生在线视图

基线仍为 b69bd7abe1e16049651908f080d1571cd0c34535，保留上一阶段全部未提交改动。
原实现有 Runtime.task_id/revision 两套执行身份，hold/replace 只改 revision；无目标的
旧 hold 可影响后来启动的 Task。本轮不再递增 revision。

现在的 Task 是一次确定计划的执行：ID、JSON 计划快照和 supersedes 固定，运行状态可变。
规划期间只有 request_id；回答/澄清不创建 Task。替换、排队任务各有独立 ID；一次有限
恢复仍属于原 Task，但采用新 action_id。调用方修改原始参数或依赖列表不会改变任务。
旧规划、旧动作异常与旧控制不能更新/停止新 Task。替换会等所有旧受控节点确认停止，
然后只恢复新计划需要的机器人准入；resume 仍不续跑旧动作。

普通动作代码不变：

```python
with launch() as system:
    action = system.action("move_named_pose", pose="B")
    result = action.wait()
```

高级任务控制的变化：

```python
# 之前：只标识这条请求，不能区分要停止哪个任务。
{"request_id": "stop-a"}
# 现在：明确控制已知的执行；不匹配就拒绝，不重新解释为控制当前任务。
{"request_id": "stop-a", "task_id": task["task_id"]}
```

原 hold/replace 服务名称保留；Voice 修改目标会读取并绑定目标 ID。无 ID 请求返回
`task_id_required`，迟到目标返回 `stale_task`。重复同 ID 请求仅返回原回执。
`TaskControl.task_id` 是唯一必需的新增请求字段；状态新增 supersedes/planning_request_id，
goal 回执新增 request_id。Runtime.revision/recovery_revision 内部变量删除；历史和线路的
revision/task_revision 暂保留为 0，ActionExecutor 仍拒绝旧客户端的旧版本。
没有新增公开方法、TaskHandle、result 别名、ROS 依赖或新的执行中间层；内部仅新增冻结 _Task 数据记录。

NodeRegistry 使用现有会话的 `presence/{node_id}/{boot_id}` Liveliness token，
`history=True` 查询已有实例并订阅变化，不再维护 checked/两秒在线过期判断。
首次等候已有 token 最多 0.3s；这只是初始化等待，不是周期心跳或响应速度指标。
配置仍决定 skill→node 和唯一服务地址；token 不授予权限，也不自动绑定陌生节点。
同名多实例拒绝选择；超过 16 个并存实例使视图保持 unknown，需重新创建视图。
能力按 boot_id 缓存，上下线立即使缓存失效。ready 是最近一次查询的状态；执行前仍读取
当前 context 并验证实例、epoch、短期授权。查询失败但 token 尚在时是 unknown，不是可执行。
直接动作及已知计划只查询相关节点；控制队列、QoS、Action 状态机和同步包装保留。

关键实现：runtime.py、registry.py、schemas.py、nodes/agent.py、nodes/speech.py、system.py。
02 中断示例新增替换 ID/来源验证；新增 test_task_identity.py、test_liveliness.py，扩充原
Runtime/Registry 单测；旧停止与节点离线测试按新的目标身份和原生事件语义迁移，保留行为断言。
实测完整命令：`./scripts/run.ps1 scripts/verify.py --wrs`。
结果：**144 unit + 37 Zenoh/Mock + 5 WRS virtual = 186 passed**；0 failed/errors/skipped，相比 171 增加 15 个用例。
所有 01/02/04/05/09/10 示例、03 完成/取消、Ruff 和 doctor PASS；另外单独执行
`./scripts/run.ps1 examples/02_mock_interrupt.py` 通过。
证据：reports/task_liveliness_summary.json、acceptance.json 和 unit/zenoh/wrs.xml。
缓存示例仍为 Mock model_calls=1→1→2→3，算法未改。

未验证：真实 GLM（只有离线 HTTP 夹具，未启用 live-model）、真实音频/硬件、双机权限、
网络分区检测时延和端到端性能。Voice 等待 TTS 时可能拖住随后 WRS stop 的已知问题未在
本切片修复；下一步自然入口是这个控制执行隔离问题。没有宣称最快响应。
本阶段完成并停止，未 commit/push。


## 2026-09-18：从入门示例开始，分开观察与执行准备

基线仍为 b69bd7abe1e16049651908f080d1571cd0c34535，保留前面各阶段未提交改动。
本轮没有切分支、reset、commit 或 push。用户明确选择同步迁移本仓库旧 snapshot 凭证调用方。

### 为什么改：两个具体例子

**看看位置，不应该顺便领一张开动许可。** 原 snapshot() 每次查看状态都会签发一张
两秒有效的执行凭证，只保存最近 64 张。另一个人频繁查看进度，可能把准备执行的那张
凭证挤掉，导致动作被拒绝。现在 snapshot 只读；真正准备提交动作时调用 context。
普通用户的 system.action() 已经自动办好这件事，调用方法不增加。

**收取模型回复，与检查机器人计划，分给各自负责的代码。** 原 GLM 接入先解析检查计划、
重新写成 JSON，ModelPlanner 又解析检查一次。现在 GLMClient 检查服务响应是否完整、
是不是允许的工具；ModelPlanner 检查 JSON、计划步骤与依赖等决策合同。Runtime 随后仍
检查当前技能、节点能力与执行状态；节点仍检查权限、版本和资源。没有减少这些不同用途的检查。

### 普通脚本入口与示例

普通用户只需 System（入口）、Skill（能力）、Action（一次调用）、Task（一次计划执行）。
Node（执行进程）与 Planner（决定如何做）在扩展系统时再学。执行节点和模型服务商
分别称呼，不把两个不同的 provider 用法混在入门解释里。

```python
from wrs_agent import launch

with launch() as system:
    action = system.action("move_named_pose", pose="B")
    result = action.wait()
```

这段用户代码前后不变。调用会等待接收回执，不等动作完成；wait 才等待终态。
取消受理不等于物理停止，等待超时不会取消运动。同步 Session 仍只在所属线程调用；
远端节点在同步调用间继续运行，本地 Runner 不会在用户代码 time.sleep 时运行。
同一客户端需要一边等待一边发控制时使用现有异步 System；本轮不增加后台线程。

示例真正移入三组，旧路径不保留转发层；[示例导航](../examples/README.md) 是推荐学习顺序。

| 原路径 | 新路径 | 用途 |
|---|---|---|
| 新增最短示例 | examples/beginner/01_action.py | 一次动作、查询、等待 |
| examples/09_skill_library.py | examples/beginner/02_skills.py | 查询技能 |
| examples/10_system_nodes.py | examples/tasks/01_parallel_and_stop.py | 多步任务、并行和停止 |
| examples/05_cache_reuse.py | examples/tasks/02_cache_reuse.py | 同步目标与条件缓存 |
| examples/03_wrs_scene.py | examples/tasks/03_wrs_scene.py | 同步 WRS 虚拟模型 |
| examples/01_zenoh_roundtrip.py | examples/developer/01_zenoh_roundtrip.py | 通信验证，保留 async |
| examples/02_mock_interrupt.py | examples/developer/02_mock_interrupt.py | 故障验证，保留 async |
| examples/04_glm_task.py | examples/developer/03_glm_adapter.py | 模型适配，默认离线 |

缓存示例原先要组装 Runtime/ModelPlanner/客户端并等待本地协程，现在只使用 launch、
action、goal、wait、snapshot。MockClient 默认使用脚本化转移模板；其他输入保留固定
home 回复。显式传入回复的已有 MockClient 夹具不变。它不代表真实语言理解或 GLM 调用。

### 实现与接口迁移

- schemas.WorldSnapshot 不含 lease_id；ActionContext 在状态数据上增加必需凭证。
  TTS 的机器人可选状态为空，不增加 TTS 的 hold/resume 或机器人接口。
- actions.ActionExecutor.snapshot 只读，context 签发；进度事件也不签发或携带凭证。
  RobotClient 删除转发 snapshot 的 context 重写，复用现有通用方法。Runtime 的 WRS
  规划/观察/控制检查用 snapshot，动作提交前取 context；模型输入排除所有 lease_id。
- 底层旧调用 `context = await robot.snapshot()` 改为 `context = await robot.context()`，
  再使用原 action_request/submit。WorldSnapshot 中的 lease_id 字段有意移除，外部旧调用
  需同步升级；ActionRequest 及短期凭证字段名、boot/epoch/task/action 约束保持。
- GLMClient.parse_reply 保留原始工具参数；ModelPlanner 是模型决策解析校验的唯一位置。
  原始 message/tool_calls、usage、finish 状态仍保留。文本永远是回答，不能执行文本中的 JSON。
- 新增公开方法/包装类/运行中间层/依赖：均无。公开返回结构仅上述状态字段迁移；MockClient
  的 reply 参数允许省略，新增一个内部默认回复函数。Transport、控制队列与缓存算法不变。

保留已经合理的部分：同步/异步双入口、单 Planner、Zenoh 原生在线判断、节点直连、
动作去重、停止后旧命令失效和 UNKNOWN 处理。没有为了减少 async 而删去故障验证。

### 实测与限制

本轮预检同步单元/集成：15 passed，17.64 秒。
状态分离单元与真实网络：38 passed，17.17 秒，reports/state_context.xml。
Planner 单元与真实网络：53 passed，6.77 秒，reports/planner_boundary.xml。
首次 Ruff 发现 4 处长行和一处空行，修正后通过，未改动或降低行为断言。
完整命令：`./scripts/run.ps1 scripts/verify.py --wrs`。
实测 **146 unit + 42 Zenoh/Mock + 5 WRS virtual = 193 passed**，0 failed/errors/skipped；
相对 186 新增 7 个测试用例。三个分组耗时分别 2.443、92.564、12.847 秒。
所有分级示例、WRS 完成/取消、Ruff、doctor 均 PASS；缓存例子 model_calls=1→1→2→3。
证据 reports/api_levels_summary.json、acceptance.json、unit/zenoh/wrs.xml、plan_cache.txt。
外部底层客户端与节点应同步升级 snapshot/context 返回合同；没有自动兼容回退。

新增回归包括 100 次状态查询不签发/挤掉授权、100 条状态进度事件无凭证、80 次真实网络
查询后原授权仍可执行、非法 GLM 参数导致零动作，以及独立 Agent 的同步缓存调用与新 ID。
原非法参数测试改到实际决策边界，所有错误情形保留，并增加端到端零执行断言。

未验证：真实 GLM、ASR/TTS、实机、双机 ACL 和延迟分位数。WRS 仍为 Lite6 虚拟 FK，
没有新增抓取能力。Voice 的同一控制 worker 等待 TTS 时可能拖住 WRS stop，留待独立切片。
参考只借鉴 [Ray 的先提交再等待方式](https://docs.ray.io/en/latest/ray-core/examples/gentle_walkthrough.html)，
没有引入 Ray、装饰器或复制其实现；现有 API 已有相同使用方式。


## 2026-09-18：全库冗余清理

基线 HEAD 仍为 `b69bd7abe1e16049651908f080d1571cd0c34535`，以上一轮 193 项回归和
已有未提交代码为起点。没有分支切换、reset、commit 或 push。
先审查整个包的模块、导入和符号引用，再移除重复职责；没有引入依赖或框架。

上一轮两项已完成并继续通过回归：snapshot 只查看状态，context 才取得执行许可；
GLMClient 读取服务回复，ModelPlanner 统一检查计划。普通 action() 自动取得许可。

本轮 `wrs_agent` 的 Python 文件从 36 个减为 27 个，源码行数从 3753 减为 3696。
删除九个转发或过度拆分的文件，另将 speech.py 改名为 voice.py；数量只用于说明改动范围。

| 原位置或名称 | 当前唯一位置或名称 |
|---|---|
| environments/{__init__,api,mock,wrs}.py、nodes/environment.py | env/ 中的实际机器人适配；旧兼容别名删除 |
| nodes/api.py | nodes/actions.py：Action 协议、客户端、Zenoh 服务绑定 |
| planner/api.py、planner/model.py | planner/__init__.py：输入、决策、Planner、ModelPlanner |
| planner/providers/api.py | planner/providers/__init__.py：ModelRequest/Reply、ModelClient |
| nodes/speech.py、register_speech | nodes/voice.py、register_voice |
| load_nodes + load_bindings | load_bindings：返回完整节点配置和技能绑定，不再返回 suffix 投影 |
| SkillSpec.node 默认执行节点 | 删除；TOML 是唯一绑定来源，lookup_skills 显式接收 bindings |
| NodeRegistry.provider(skill) | node_for(skill)，明确返回执行节点 ID |
| LocalStack(runtime=False) | LocalStack(agent=False)，对应实际启动的节点 |
| CLI environment / runtime | wrs / agent；退出服务同步为 request/wrs/shutdown、request/agent/shutdown |

低层导入现在直接写 `from wrs_agent.planner import ModelPlanner, PlanRequest`，
或 `from wrs_agent.nodes.actions import ActionClient, RobotClient`，不再经过 api 转发。
外部使用旧路径、返回结构或命令行别名的调用方需要同步更新；仓库内调用已迁移。
节点错误名中的 provider 改为 node（如 node_not_ready）；模型 provider 名称保留。

System 复用 LocalStack 已读取的配置；不在节点启动后重新读取可能变动的 TOML。
启动改为一个明确的 wrs→tts→agent→voice 循环，关闭仍按相反顺序。
删除 CacheEntry 内重复的 signature（字典键已保存）和 decide_event 未使用的 state 参数。
`__main__.node` 改为 `run_node`，内部就绪检查改为 `_wait_ready(bus, key)`。
这些是现有职责的合并，没有新增公开方法或运行中间层。

**__main__.py 为什么保留：**它是 Python 识别 `python -m wrs_agent` 的标准入口。
它读取启动参数并启动节点；launch() 也通过它启动自己的子进程。任务协调和动作执行
仍在 Runtime 与各节点中，不在入口里再写一套循环。普通用户无须导入这个文件。

普通用户的前后代码完全相同：

```python
from wrs_agent import launch

with launch() as system:
    action = system.action("move_named_pose", pose="B")
    print(action.wait())
```

保留：同步包装和异步实现、单 Planner、执行端 ActionExecutor、Zenoh 本地控制隔离、
授权和停止确认、action_id 去重、旧 task/boot/epoch 拒绝。它们解决不同问题，不合并。

实际验证：`./scripts/run.ps1 scripts/verify.py --wrs`，
**151 unit + 42 Zenoh/Mock + 5 WRS virtual = 198 passed**；0 failed/errors/skipped。
全部分级示例、WRS 完成/取消、Ruff、doctor PASS；缓存计数仍为 1→1→2→3。
`./scripts/run.ps1 -m wrs_agent --help` 正常显示五种启动角色。
新增 2 项显式绑定测试、4 项 CLI 配置拒绝用例；现有网络测试增加配置只读一次的验证。
删除 1 项仅断言旧导入别名等价的兼容测试，因为这些入口已明确移除；动作行为断言保留。
首次网络检查出现 3 个旧 `_ready` 调用，修复调用后完整网络回归通过，没有降低断言。
证据：reports/library_cleanup_summary.json、acceptance.json 和 unit/zenoh/wrs.xml。

未验证：真实 GLM、音频、实机、跨机 ACL 和响应延迟。WRS 仍只验证 Lite6 虚拟 FK，
不支持本 profile 的真实抓取。Voice 控制 worker 等待 TTS 可能延迟后续 WRS stop 的
既有问题仍在；本轮不作最快响应承诺。没有付费调用或硬件连接。


## 2026-09-18：节点状态与技能注册

基线为同一 HEAD、现有未提交工作和 198 项回归。保留新增的 getting_started 文档及其他用户改动。
本轮采用两项建议的最小机制，不增加聚合器、插件系统、动态加载或依赖。

状态从 WorldSnapshot 改为 NodeSnapshot：共同部分保存 node_id、boot_id、captured_at_ns、
state_version、控制状态；data 用 RobotData / SpeechData 明确区分。TTS 不再有空的机械臂字段。
state_version 保留线路字段名，表达该节点业务数据版本；control_epoch 继续解决停止后旧授权失效。
采集时间是源节点 wall clock，不用于跨机许可过期判断；WRS 数据另保留实际 FK 观测时间。

```python
# 之前：只能查机器人，业务字段与控制字段混在一起。
pose = system.snapshot().pose
# 现在：同一个方法读取指定节点；省略参数仍查询机器人。
robot = system.snapshot()
pose = robot.data.pose
speech = system.snapshot("tts")
print(speech.node_id, speech.data.completed)
```

每次只返回一个节点的状态，不声称是全系统同步快照。Agent/Voice 暂无业务快照，显式拒绝。
NodeInfo 继续用于节点在线与 ready 查询。ActionContext 在 NodeSnapshot 上增加当前执行凭证；
ActionRequest、任务身份、节点 epoch/boot 与短期授权语义保持。Runtime、Voice 和取消动作前
读取 TTS 状态也改用 snapshot，不再顺便签发许可。低层 JSON 和属性调用需同步迁移到 data；
仓库中的 Runtime、缓存、示例与测试已迁移，没有保留重复平铺字段。

技能原 FUNCTIONS/METADATA/SPECS 三张表合为 SKILLS。每项 Skill 是冻结记录，包含
spec、arguments、handler；不是新的 Skill 基类。原 NoArgs 合并使用已有 Empty 参数模型。
节点显式选取自己实现的条目，WRS 绑定真实 FK 函数，Mock/TTS 绑定各自状态处理函数。
ActionExecutor 删除 perform/advance 两套入口，统一调用登记函数；同步短函数与异步长函数
均沿原 ACCEPTED、执行、验证、取消、终态流程。schema 与参数模型不一致时启动即失败。
validate_skill 仍在同一处处理名称、版本和参数；节点只使用自己的注册表。

Planner 继续只收到 SkillSpec；节点声明能力和 TOML 允许绑定分别校验。TOML 不能授予未实现技能。
公开调用 launch/action/start/goal/wait/skills 不变；snapshot 增加 TTS 支持，返回值迁移如上。
新增类型仅 Skill、NodeSnapshot、RobotData、SpeechData；删除 WorldSnapshot、NoArgs、
FUNCTIONS/METADATA/SPECS/ROBOT_SKILLS 及执行器 perform/advance 参数，没有新增运行层。

本地复核 HoloAgent 技能 README、RPent planner/base.py、DimOS usage/modules.md；只借鉴
合同与执行分开、节点提供能力的表达，没有复制非平凡实现或移植其框架。
状态切片 15 passed；注册和慢 WRS/停止/并发切片 36 passed。

完整验收：`./scripts/run.ps1 scripts/verify.py --wrs`。
**162 unit + 43 Zenoh/Mock + 5 WRS virtual = 210 passed**；0 failed/errors/skipped。
所有分级示例、WRS 完成/取消、Ruff 和 doctor PASS；缓存调用仍为 1→1→2→3。
新增 7 项快照边界、4 项注册校验与执行、1 项真实 Zenoh 错误部署绑定测试。
既有 TTS 空机器人字段断言改为类型隔离检查，其去重、取消和恢复断言保留。
证据 reports/typed_nodes_summary.json、acceptance.json、unit/zenoh/wrs.xml；
切片证据 typed_state_boundary.xml（15 passed）、registered_skills.xml（36 passed）。
未新增源码模块或依赖；既有示例迁移到 snapshot().data。公开字段迁移见 api_simplification.md 文末。
真实 GLM、音频、实机、跨机 ACL 和延迟未验证；Voice 单 worker 等待 TTS 的限制保留。
WRS 仅虚拟 Lite6 FK，无新增抓取能力。没有 commit/push。


## 统一客户端，分开启动与连接（2026-09-18）

基线：HEAD `b69bd7abe1e16049651908f080d1571cd0c34535` 和已有未提交实现，上一轮 210 passed。

原设计把协议分类 ActionClient 与设备分类 RobotClient 混在一起；后者只增加两个转发方法。
RobotClient 已删除。内部统一 ActionClient，负责消息编码、发送和回执校验；节点只注册其支持的控制。
WRS 支持 hold/resume，TTS 仍不提供这些服务。没有新增继承层、Client 工厂或依赖。
普通用户不构造 Client：

```python
# 之前（底层示例）：
bus = stack.transport
robot = RobotClient(bus)
tts = ActionClient(stack.node_transports["tts"])

# 现在（普通脚本）：
with launch() as system:
    motion = system.action("move_named_pose", pose="B")
    speech = system.action("speak", text="我正在处理")
    speech.cancel()
    print(motion.wait().state)
```

新增公开入口 `connect()` / `System.connect()`：使用已有节点，退出只断开自己的连接；
已接收动作继续执行。launch/System.local 仍负责启动并清理本地进程。两者复用同一 System，
同步入口共用现有 Runner；没有增加后台线程。新增 session.endpoint/site/env_id 便于明确连接目标。
凭据只从 WRS_AGENT_TOKEN 读取；launch 未配置时生成仅供自身子进程使用的临时凭据。

TOML enabled 决定启动节点，移除 LocalStack 的 agent/tts/voice 重复开关；新增 robot.toml、tts.toml。
允许技能绑定子集，未绑定技能不能执行。删除 LocalStack.transport/node_transports；低层代码
用 stack.system.clients[node_id]，需要协议消息时才读取该客户端的 transport。
System(stack) 改为 stack.system；System 不再依赖已启动 Agent，TTS 可独立使用。
连接已有配置节点不要求它们当场在线；Liveliness 检测晚到/离开，仍须核对 ready、能力和授权。
没有热加载 Python 技能，也没有自动信任未配置节点。

保留且不改：动作去重、任务身份、节点 boot/epoch、停止确认、取消范围、Action 生命周期、
Registry/Liveliness、现有 Planner 和缓存。等待超时不取消动作；同步脚本等待时仅占用调用线程，
同一客户端并发控制仍用异步 System，独立节点继续运行。

实际命令：

```powershell
./scripts/run.ps1 scripts/verify.py --wrs
./scripts/run.ps1 -m pytest -q tests/integration -m wrs --junitxml=reports/wrs.xml
```

首轮完整检查：173 unit、47 Zenoh/Mock、所有示例、Ruff、doctor 通过；WRS 4 passed/1 failed。
失败是旧测试遍历了新增默认启动的 Voice，误读动作计数字段；改为检查 WRS/TTS，原零副作用断言保留。
针对 WRS 组复测 5 passed。最终 **225 passed（173 + 47 + 5），0 failed/errors/skipped**。
另有 15 项系统/同步切片、27 项连接/启动切片通过。新增连接例子由测试作为独立 Python 进程运行。
证据 reports/launch_connect_summary.json、acceptance.json、unit/zenoh/wrs.xml；保留首次失败报告。

关键实现：system.py、sync.py、processes.py、bindings.py、nodes/actions.py、nodes/voice.py、
runtime.py、__main__.py。新增测试 test_connect.py，扩展 test_processes.py；迁移现有控制测试。
新增 examples/tasks/04_connect.py；developer 示例不再手工拼装 RobotClient/TTS Client。
只增加 connect 这一使用入口，没有新的运行层；底层 control(kind, request) 复用原控制通道。
真实 GLM、音频、实机、跨机 ACL、端到端延迟未验证；Voice 单控制 worker 的限制保留。
没有 commit/push。此切片完成，下一步可从连接示例使用已有节点。


## 统一启动动词（2026-09-18）

基线 checkout：`64c44785a5daa579387c68edfa3405c304edc7c5`，保留现有未跟踪文件。
异步入口由 `System.local(...)` 改为 `System.launch(...)`；同步仍用 `launch(...)`。
参数、返回对象、准备就绪和退出清理语义不变。不保留 local 别名，外部异步脚本需替换这个名称。

| 用途 | 同步脚本 | 异步程序 |
|---|---|---|
| 启动并管理本机节点 | `with launch() as system:` | `async with System.launch() as system:` |
| 连接已有节点 | `with connect() as system:` | `async with System.connect() as system:` |

内部 LocalStack 保留，Local 表示在当前电脑启动和回收进程；Stack 表示一起运行的配套进程。
不新增 LocalProcesses、Launcher 或中间层。公开名字只增 System.launch、删 System.local。
修改 system.py、sync.py，以及已有调用方和入门说明；没有新增源码模块、依赖或测试用例。
源码与测试中的旧调用已全部迁移；前文的 System.local 只保留为阶段历史。

本轮 **197 passed（173 unit + 24 真实 Zenoh/Mock），0 failed/errors/skipped**，83.23 秒。
命令：

```powershell
./scripts/run.ps1 -m pytest -q tests/unit tests/integration/test_system.py tests/integration/test_sync_api.py tests/integration/test_connect.py tests/integration/test_liveliness.py tests/integration/test_task_identity.py --junitxml=reports/launch_name.xml
./scripts/run.ps1 -m ruff check wrs_agent tests examples scripts
```

已运行 examples/beginner/01_action.py、examples/tasks/01_parallel_and_stop.py、
examples/tasks/03_wrs_scene.py，全部 exit 0；覆盖同步调用、并行取消和真实 WRS 虚拟启动。
示例经指定 Python -X utf8 -S scripts/run.py 执行，完整命令与输出见
reports/launch_name_summary.json、launch_name_examples.json 和对应 txt；测试明细见 launch_name.xml。
Ruff、git diff --check 通过。未增加测试用例；既有断言保留，仅迁移入口名。
真实 GLM、音频、硬件、跨机和延迟没有新增验证；没有 commit/push。



## 任务身份与协议 v2（2026-09-18）

完成四项已复现问题的修复：整个计划的实例/控制绑定、Voice 同 ID 重试与并发共享、按任务参与者停止及替换、已知终态的 Mock TTS 重启准入。连续替换仍等待原参与资源停止。

context 保留。公开 action_request 组装函数移除，ActionClient.submit 接收技能、参数和 context，生成 ActionRequest 并处理回复丢失。state_version 替代旧 world_version；信封与 Zenoh 前缀为 v2，无旧别名，需一起升级。底层故障注入测试仍可直接经 Transport 发送 ActionRequest。

start 返回 TaskHandle；goal 返回 GoalHandle。system.task(id) 支持重连，system.status 保留总览；无目标 system.wait/watch 已删除。同步与异步例子均使用句柄。Runtime 会话内有界保留每个任务及规划结果，满时拒绝新增，重启后旧 ID 不存在。

完整语义、版本原因、调用链、迁移用法见 [task_handles.md](task_handles.md)。验收结果见 ACCEPTANCE.md 本轮条目。本轮未增加动态节点接纳、依赖或硬件能力。
