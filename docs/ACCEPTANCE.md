# WRS-Agent V1 验收合同

> 本文件按日期保留历史验收命令。2026-09-20 示例已全部重写，旧路径和旧参数仅供历史审计；当前运行入口见 [示例目录](../examples/README.md)，本次结果见文末“全部示例重写”。

完整 V1 矩阵仍按阶段验收；最新结果见文末及 reports/cancel_summary.json；旧阶段报告为历史证据，未运行项不视为通过。报告必须区分 PASS、FAIL、SKIP、BLOCKED 与 UNVERIFIED。SKIP/BLOCKED 不算通过。

## 1. 环境层级

A：离线单元测试，无网络、模型凭据、麦克风和 WRS。

B：真实 Zenoh 本机多进程集成，使用 Mock Environment。

C：真实 WRS 虚拟环境，使用实际 robot/model 与规划接口，但不宣称真实接触成功。

D：显式开启的真实 GLM 与音频测试，不连接真实动作设备。

E：人工监督的实际机器人测试，必须另行 opt-in；不作为无人值守 Codex 默认动作。

软件发布报告必须列出各层级状态。不得以 A/B 通过宣称 C/D/E 通过。

## 2. 最小自动化矩阵

| ID | 层级 | 情景 | 通过标准 |
|---|---|---|---|
| T01 | A | 未知消息版本/字段、非有限数值 | 拒绝，不产生动作 |
| T02 | A | 不存在技能、参数类型或范围错误 | 明确错误，不动态导入或执行代码 |
| T03 | A | 计划依赖环、重复节点、缺失依赖 | 拒绝，无部分动作提前启动 |
| T04 | B | 两个进程 publish/query | 使用真实 Zenoh 通信得到匹配结果 |
| T05 | B | query 超时 | 可取消等待，主控制循环仍工作 |
| T06 | B | 长动作运行时查询状态 | 返回 RUNNING，不阻塞至动作结束 |
| T07 | B | 长动作中 hold | 先撤权，再确认停止；两种反馈可区分 |
| T08 | B | 重复 interrupt_id | 同一停止请求只处理一次控制版本切换 |
| T09 | B | 重复 action_id、参数相同 | 不重复执行，返回同一动作状态 |
| T10 | B | action_id 相同、参数不同 | 明确拒绝 |
| T11 | B | hold 后迟到动作/轨迹 | 旧 boot/epoch 动作拒收 |
| T12 | A/B | 修改目标后旧模型结果返回 | 旧 revision 结果丢弃，不重新开启运动 |
| T13 | B | 设备 hold 后没有 allow_actions | 新动作不能自行越过设备关闭准入状态 |
| T14 | B | allow_actions | 仅允许新动作，不续跑旧轨迹 |
| T15 | B | 同机械臂两个技能 | 资源互斥，不并发下发冲突动作 |
| T16 | B | 停止时运动资源被占用 | 控制通道不等普通动作锁释放 |
| T17 | B | 收到动作但回执丢失 | 使用 status 恢复，不创建新 ID 盲重试 |
| T18 | B | 设备执行状态不明 | UNKNOWN，后继依赖阻塞，禁止重试 |
| T19 | B | Environment 重启 | 新 boot_id，旧动作不恢复 |
| T20 | B | 两个相同 env_id 服务启动 | 独占检查失败，不允许多写同设备 |
| T21 | A/B | 执行 COMPLETE 但物体未持有 | verification FAIL，任务不算成功 |
| T22 | A/B | 验证 INCONCLUSIVE | 不解锁依赖持物成功的下一步 |
| T23 | A | Provider 输出截断/拒绝/非法 JSON | 不提交任何物理动作 |
| T24 | A | 流式参数只到一半 | 不执行；完整后仍做 Schema 校验 |
| T25 | A | 更换第二个 ModelClient 测试实现 | 不修改 Runtime、Skill、Environment |
| T26 | A | Provider 不支持指定参数 | 启动/请求构建时明确失败，不静默伪装支持 |
| T27 | A/B | GLM 请求永不返回 | 本地停止路径仍然工作 |
| T28 | A/B | 相同适用任务再次执行 | 模型调用减少，动作 ID 与授权重新生成 |
| T29 | A/B | 否定词/数量/目标/时序改变 | 错误缓存不复用 |
| T30 | A/B | 技能、能力或标定版本改变 | 相关缓存失效并记录原因 |
| T31 | A/B | 物体位姿改变 | 重新绑定与规划，不播放旧轨迹 |
| T32 | A/B | 无关物体变化 | 不无条件失效；路径变化仍需几何检查 |
| T33 | A | semantic shadow 命中 | 仅记录，不直接触发动作 |
| T34 | A/B | 已知可恢复抓取失败 | 重新观察后最多一次重试，再验证 |
| T35 | A/B | UNKNOWN 或停止未确认 | 不进入恢复重试 |
| T36 | A/B | “嗯，对” | 不取消当前机器人动作 |
| T37 | A/B | “做到哪一步了” | 并行回答，不改变控制版本 |
| T38 | A/B | “做完再拿另一个” | 入队，不抢占当前动作 |
| T39 | A/B | “停，换成蓝色那个” | 受控停止并改任务，不沿用旧计划 |
| T40 | A/B | 只有 VAD/noise | 不直接拥有运动取消/修改权限 |
| T41 | A/B | “不要放进去”/引用“停”字 | 不误生成被否定的物理动作；谨慎暂停与新动作授权分开 |
| T42 | B | 相机流/日志/计算负载 | 内存有界，停止路径仍可处理 |
| T43 | B | 断线、恢复连接 | 不自动重发旧物理动作 |
| T44 | B | 事件乱序或丢失 | 通过版本和 status 判断，不倒退状态 |
| T45 | B | 未授权来源伪造 priority/operator | 不获得动作执行权 |
| T46 | B | 日志回放 | 只读/Mock，不发送到实机 namespace |
| T47 | C | WRS import、实际 robot/model、虚拟运动 | 是真实 WRS 接口，不是 mock 冒名 |
| T48 | C/E | stop/flush 能力缺失 | 硬件交互模式拒绝启用 |
| T49 | D | 模型真实调用 | 真实端点/模型有记录；生成计划但默认不动硬件 |
| T50 | D | 麦克风输入、模型挂起时说停 | 本地识别并发控制请求；不是文本回放 |
| T51 | D | TTS 与用户插话 | 播报和机器人中断行为可分开，记录回声限制 |
| T52 | A–D | 没有 API key、缺语音模型 | 明确缺少条件，不 fallback 后谎称接通 |

## 3. 三个最终场景

场景一：执行 A→B，期间查询当前进度，之后追加 D。进度查询不中断运动，D 排队。不得为只读查询变更环境控制 epoch。

场景二：执行 A→B，期间说“停，改放到 C”。记录旧 task revision、旧控制 epoch、停止接收、实际停止、更新世界状态、新计划和最终验证。持物状态必须保留，不能因为 cancel 就打开夹爪。

场景三：重复一个适用任务以验证缓存减少模型调用，然后改变目标位置或技能版本，观察缓存重新绑定/拒绝复用。在同一段演示里证明快路径和失效路径都存在。

上述场景在 B 和 C 分别运行。在 C 中若使用虚拟抓持规则，应明确标注。E 层涉及实际执行时必须人工监督，报告实际停止反馈与验证传感器。

## 4. 性能测量

首轮本机工程目标：可信控制事件发送到 Environment 接收并撤权确认的 RTT，P95≤20ms，P99≤50ms。这是未测目标，不是保证。达不到时报告真实结果和原因，不更换计时边界来美化结果。

固定记录机器、系统、CPU、内存、Python、Zenoh 包、zenohd、WRS commit、配置和采样数量。至少测试空载、持续观测流、模型等待和 CPU 工作负载。测试期间不发送真实硬件控制。

建议基线载荷：小控制请求 256B–2KiB、100Hz 状态消息、15fps 图像背景流，记录实际编码与图像体积。控制延迟采样不少于 1000 次；稳态前先预热，冷启动单列。阈值需注明负载定义，不能从无负载结果推断高负载性能。

在线图像消费者使用最新数据和有界缓冲；报告数据年龄、丢帧和队列高水位。可靠控制请求遇到拥塞应明确处理，而不是静默丢弃。

跨机没有时钟同步时只测请求方 monotonic RTT；不相减两台机器的 monotonic_ns。需要报告单程延迟时，另行说明时钟同步、偏差和精度。

模型 latency、ASR latency、软件控制 latency 和真实设备停止 latency 分开。缓存报告命中率、拒绝原因、模型调用节省与错误复用率。虚拟状态不能验证真实制动时间和距离。

## 5. 报告产物

在实现仓库生成 `reports/acceptance.json` 与 `reports/benchmark.json`。每项带 test_id、profile、status、命令/配置、结果摘要和证据路径；不要生成没有真实运行来源的 PASS。

最终 README 给出能复现的最短命令。自动测试清理自己启动的进程，不杀掉用户其他服务，不扫描和驱动未明确指定的硬件。


## 6. 2026-09-17 能力节点增量验收

实际命令：`./scripts/run.ps1 scripts/verify.py`。44 单测、6 真实 Zenoh 集成测试、两个示例、Ruff、doctor 通过；0 failed / 0 skipped。输出及 JUnit 在 reports/。

| 用户增量要求 | tests/integration/test_nodes.py 中的实际测试 | 结果 |
|---|---|---|
| 独立能力节点并行 | test_parallel_nodes_dependency_and_resources | PASS：WRS/TTS 同时运行，pick 等 observe、place 等 pick |
| 模型挂起时查询/直连控制 | test_hung_model_direct_voice_cancel_and_stop | PASS：挂起的是 MockClient，无 GLM API 调用 |
| 查询不中断、TTS 取消独立 | 同上及 test_cancel_tts_allows_robot_branch_to_finish_and_queue_runs_after_success | PASS：WRS epoch 不变，完成自己的分支 |
| 幂等与迟到结果 | test_dedup_missed_terminal_and_authentication、挂起模型测试；单测 test_late_model_revision_is_rejected | PASS：旧 epoch/revision 拒绝，重复动作执行一次 |
| 漏终态后查询恢复 | test_dedup_missed_terminal_and_authentication | PASS：两节点不订阅终态，以原 ID 查询 SUCCEEDED/验证结果 |

另测：独占进程、超时/取消等待、callback 线程桥接、router 重连不重提动作、停止不等磁盘写入、UNKNOWN 禁止恢复、过期授权拒绝。

这不是完整 M8 矩阵通过声明。真实 WRS 仅 import/FK 通过；Vision、GLM 服务、真实音频、实机、远程 ACL、断网中运动的自动安全停车和高负载百分位均 UNVERIFIED。

## 2026-09-17：GLM 协议与版本管理增量

真实命令：`./scripts/bootstrap.ps1 -Extra glm`、`./scripts/run.ps1 examples/04_glm_task.py --dry-run`、`./scripts/run.ps1 scripts/verify.py`。

最终结果：92 项单元测试、8 项真实 Zenoh 集成测试通过，0 failed、0 skipped；roundtrip、并行中断、GLM 离线示例、Ruff、doctor 均 PASS。报告仍仅保存在本地 reports/。指定 Python 3.12.0、Zenoh/router 1.9.0、httpx 0.28.1，锁文件由 uv 0.12.15 生成。

另外从 Git 暂存区导出独立快照，使用相同项目依赖与 router，设置 RUST_LOG=info 执行 `./scripts/run.ps1 -m pytest -q tests/unit tests/integration -m 'not live_model and not audio_live and not hardware and not wrs'`：100 passed；GLM 离线示例和 Ruff 通过。快照包含已验证的 router 版本解析修复。

新增 GLM 证据：原生单工具计划、纯文本回答、多工具/未知工具拒绝、权限字段和依赖环拒绝、截断/拒绝/非法 JSON、配置能力限制、总超时/取消、HTTP 错误脱敏、响应大小上限、无重定向/计费端点回退；GLM HTTP 夹具迟到结果仍受 Runtime revision 栅栏限制。工具建议从不直接执行。

真实 GLM 请求仍 UNVERIFIED：用户确认国内账号，未确认可用模型及自建 Runtime 的套餐授权，本轮未联网调用。Claude 格式、流式输出、GLM TTS、真实音频和实机未验证。默认节点继续使用 MockClient；没有把离线夹具称为真实服务验收。

## M3–M5 本轮结果（2026-09-17）

最终命令：`./scripts/run.ps1 scripts/verify.py --wrs`。117 单元、19 真实 Zenoh/Mock 集成、5 真实 WRS 虚拟节点集成，共 141 passed，0 failed / 0 errors / 0 skipped。按 marker 分组的 deselected 不算跳过或失败。既有测试保留，新增 41 个测试用例。

01/02/04 原有示例、03 正常完成与 --cancel、05_cache_reuse、09_skill_library、Ruff 和 doctor 均 PASS。本地证据 reports/acceptance.json、unit.xml、zenoh.xml、wrs.xml、m3_m5_summary.json 及对应 .txt；报告不上传 Git。

关键新增验证：
- 真实 WRS Lite6：ACCEPTED/进度、snapshot/status、关节与 FK 后置条件、cancel/hold、停止后状态稳定、resume 仅恢复准入、旧 epoch/revision 拒绝、幂等、Runtime 调度与进程清理。
- 单元慢 FK：同步调用未返回时可收 hold，但 stop_confirmed=false；返回后才确认停止。异常进入 UNKNOWN，硬件使能拒绝。未支持的 WRS pick 使整个计划在任何 TTS 副作用前失败。
- GLM 原生 HTTP 夹具→ModelPlanner→Runtime→真实 Zenoh→Mock 节点闭环；HTTP 等待期间可查询、只取消 TTS、独立停止 WRS，迟到结果和迟到错误不可恢复执行。
- 技能别名/标签检索与能力过滤；缓存拒绝否定、数量、时序、目标/相关位置/标定/能力/技能/绑定/Schema 变化，无关对象变化仍适用。命中后的动作 ID 全新，失败任务不写入可用条目。
- 一次恢复：grasp_once/localization_once 成功；持续失败只重试一次；UNKNOWN/inconclusive、前置条件错误不重试；恢复观察期间停止后无新抓取。

缓存示例实际 model_calls=1→1→2→3，第二次命中减少一次 Mock ModelClient/Planner 调用。另有原生 GLM HTTP 夹具三次任务只生成两次 HTTP 请求，全部动作仍走真实 Zenoh 和验证。未发送真实 GLM，因此不报告付费请求节省或云延迟。

WRS 限制：headless FK 虚拟运动，固定模型单线程所有权；每个 FK 不可抢占，仅边界协作停止，没有控制器队列。pick/place/接触验证/碰撞规划/IK/RRT 动作链和实机均未验证或 unsupported。已有科学环境可运行，干净机器完整科学依赖重建未验证。真实 GLM 模型/用途授权尚未落实，流式输出、音频、硬件、双机保护与负载基准未验证。

## System Structure Consolidation 验收（2026-09-17）

命令：./scripts/run.ps1 scripts/verify.py --wrs。
120 unit + 26 真实 Zenoh/Mock + 5 真实 WRS FK = **151 passed**，
0 failed / errors / skipped；原 141 项保留，新增 10 项。
01/02/04/05/09/10 示例、03 完成/取消两模式、Ruff、doctor 全部 PASS。
证据：reports/consolidation_summary.json、acceptance.json、unit.xml、zenoh.xml、wrs.xml。

新增测试 tests/unit/test_registry.py、tests/integration/test_system.py 覆盖：
- 四节点身份/启动版本/ready、Vision 只声明、视图过期/离线/重启/错误身份与能力拒绝；
- 配置中的 WRS provider 改名后，Runtime 执行与停止不依赖名称；
- WRS/TTS 并行、查询不打断、Voice 局部取消和直控停止；
- Agent 退出后直连仍有效；离线/held provider 使任务在任何分支副作用前拒绝；
- 泛化 ActionContext 无物体字段、TTS 无 hold/resume、去重与重复取消；
- 不订阅终态也能按 ID 恢复状态，丢提交回执后查询补偿且只执行一次；
- Runtime 控制通道不调用普通 capabilities 查询。

WRS 仍仅验证 Lite6 FK 虚拟运动、停止边界和准入；没有新增机器人能力。
GLM 仍仅离线 HTTP 夹具；没有真实调用（账号模型/适用服务授权未落实）。
真实 ASR/TTS/Vision/硬件/双机 ACL 未验证。没有推进 M6/M7/M8 功能。
缓存算法未改，05 仍为 Mock model_calls 1→1→2→3。

## 同步脚本 API 验收（2026-09-17）

使用普通 with launch()、action/status/wait/cancel；主示例 03/10 不需要 async/await。
原 System.local() 异步入口保留。同步模块 105 行，无新增依赖、后台事件循环线程、
调度器、消息协议或设备实现；方法转发到原 System/Action。

实际运行 ./scripts/run.ps1 scripts/verify.py --wrs：
125 unit + 30 真实 Zenoh/Mock + 5 真实 WRS FK = **160 passed**，
0 failed/errors/skipped；原 151 项保留，新增 9 项。
最终 full run 的 Ruff 对一个参数化测试的 timeout 参数名报错；
仅改名 wait_timeout 后，单独重跑 tests/unit/test_sync_runner.py 为 5 passed，
ruff check wrs_agent tests examples scripts 为 PASS。未重复或降低功能测试。
所有示例、WRS 完成/取消、doctor 通过。

证据 reports/sync_api_summary.json、acceptance.json、JUnit；
先前 lint 输出保留 reports/sync_lint_before.txt，后续实测结果在 lint.txt。
新增覆盖：调用端 time.sleep 期间节点并行完成、wait 超时不取消动作、
TTS 局部取消/WRS 停止、任务依赖/进度迭代、异常/KeyboardInterrupt 退出清理、
启动失败、异步环境/跨线程/关闭后误用、watch 不跨 yield 取消调用者，
以及 timeout=None 兼容。

仍仅 Mock 音频与 WRS FK 虚拟结果；没有真实 GLM、ASR/TTS 或硬件调用。


## API 小步简化（2026-09-17）

基线 b69bd7a；实际 verify --wrs：134 unit + 32 Zenoh/Mock + 5 WRS virtual =
171 passed，0 failed/errors/skipped。示例、doctor、Ruff 通过；客户端命名清理后网络回归
32 passed，02/05 示例和 Ruff 再次通过。语义、公开名字、命令和限制统一记录在
[api_simplification.md](api_simplification.md)，证据 reports/api_simplification_summary.json。
未调用真实 GLM、音频或硬件；没有新增延迟保证。按要求未 commit/push。


## 不可变任务身份与 Zenoh Liveliness（2026-09-18）

命令：`./scripts/run.ps1 scripts/verify.py --wrs`。
**144 unit + 37 Zenoh/Mock + 5 WRS virtual = 186 passed**；0 failed/errors/skipped，保留前轮 171 的行为回归，新增 15 用例。
37 项网络组运行时 deselect 5 项 WRS；WRS 组独立运行全部 5 项，未将 deselection 计为通过。
所有示例、Ruff、doctor PASS。报告 reports/task_liveliness_summary.json、acceptance.json、JUnit。
02 示例验证 replacement 的新 ID 与 supersedes；新网络测试为 test_task_identity.py、
test_liveliness.py，覆盖旧控制/规划拒绝、重启和能力缓存失效、重复实例、在线但 held、
无关 TTS 离线不被机器人动作查询。原 Registry 过期测试迁移为原生离线事件测试；
进程退出后等待网络离线通知，不能把 terminate 返回当作通知已经送达。

完整 API 变化、兼容字段、命令及限制见 [api_simplification.md](api_simplification.md)。
WRS 仍只验证虚拟 Lite6 FK；未新增 pick/place 或实机能力。GLM 仅离线夹具，缓存调用
计数仍为 1→1→2→3；未访问真实模型/音频/硬件。控制 worker 排队问题和延迟测量留待后续。


## 分级同步教程与职责精简（2026-09-18）

实际命令：`./scripts/run.ps1 scripts/verify.py --wrs`。
146 单元 + 42 真实 Zenoh/Mock + 5 WRS 虚拟 = **193 passed**，0 failed/errors/skipped。
相对 186 增加 7 个用例；原非法工具参数测试移到最终决策校验边界，没有删去错误情形。
新增高频状态读取不消耗/挤掉授权、进度事件无凭证、真实网络查询后准入、非法 GLM
计划零动作，以及同步入口通过独立 Agent 复用计划并保持新 task/action ID。
全部分级示例、Ruff 和 doctor PASS，缓存示例计数仍为 1→1→2→3。
报告 reports/api_levels_summary.json、acceptance.json、unit.xml、zenoh.xml、wrs.xml。
示例新入口见 [examples/README.md](../examples/README.md)，旧平铺路径已迁移；
03 的 WRS 完成/取消均在新 tasks 路径通过。历史章节中的旧命令仅记录当时执行位置。
WorldSnapshot 不含 lease_id，ActionContext 含当前状态和执行凭证；TTS 的机器人可选字段为空，
并没有新增机器人控制接口。GLM 原生协议解析与 ModelPlanner 计划校验分开，权限/执行检查保持。
仍未验证真实 GLM/音频/实机/双机身份与端到端延迟，不把这些列为 PASS。


## 全库冗余清理（2026-09-18）

命令：`./scripts/run.ps1 scripts/verify.py --wrs`。
**151 单元 + 42 真实 Zenoh/Mock + 5 WRS 虚拟 = 198 passed**，0 failed/errors/skipped。
全部分级示例、WRS 完成/取消、Ruff、doctor PASS；CLI --help 通过。
新增 6 项显式绑定/CLI 门禁用例；删除 1 项专门验证已移除导入别名的测试，保留动作语义检查。
已有自定义节点名的集成测试增加「节点启动后不重读配置」断言。
初次子集的 3 项失败均为旧私有启动函数引用，迁移后完整回归通过。
证据 reports/library_cleanup_summary.json、acceptance.json 和 unit/zenoh/wrs.xml。
目录和低层 API 迁移见 [api_simplification.md](api_simplification.md) 文末。
普通 launch/action/start/goal/wait 不变；缓存模型调用仍为 1→1→2→3。
未验证真实 GLM、音频、硬件、跨机 ACL 和延迟；没有新增机器人能力或外部服务调用。


## 节点状态与技能注册（2026-09-18）

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


## 统一客户端与启动/连接（2026-09-18）

`./scripts/run.ps1 scripts/verify.py --wrs`：173 unit、47 Zenoh/Mock、全部示例、Ruff、doctor 通过；
首次 WRS 4 passed/1 failed。旧测试遍历全部连接，误把 Voice 当动作节点；保留原断言并限定 WRS/TTS。
`./scripts/run.ps1 -m pytest -q tests/integration -m wrs --junitxml=reports/wrs.xml`：复测 5 passed。
最终 **225 passed（173 + 47 + 5），0 failed/errors/skipped**；首次失败证据未删除。
新增 15 项回归，包含单独 TTS、另一 Python 程序同步连接、客户端异常退出仍继续动作、
重新连接查询原 action_id、配置节点晚到，以及部分连接失败清理和输入校验。
WRS/TTS 共用 ActionClient，TTS 仍无 hold/resume 服务；既有抢占、并发、迟到结果、去重回归保留。
证据 reports/launch_connect_summary.json、acceptance.json、unit/zenoh/wrs.xml、launch_wrs_initial_failure.txt。
模型为 Mock/HTTP 夹具，音频为回放/Mock TTS，WRS 为 Lite6 虚拟 FK；实机、GLM 真实服务、
真实音频、跨机 ACL 与延迟指标未验证；不新增相关能力或测试主张。


## 异步启动名称对齐（2026-09-18）

System.local 改为 System.launch，LocalStack 保留；无启动或控制行为修改。
本轮现有测试 197 passed（173 unit + 24 Zenoh/Mock），0 failed/errors/skipped；
入门动作、并行停止、WRS 虚拟三个示例 exit 0；Ruff 和 diff --check 通过。
命令与证据：reports/launch_name_summary.json、launch_name.xml、launch_name_examples.json。
没有重跑全部 WRS 测试，WRS 本轮证据为虚拟示例；上一轮完整回归 225 passed 保留为历史。
真实 GLM、音频、硬件、跨机和延迟未新增验证；没有 commit/push。

## 示例配置路径修复（2026-09-18）

两个示例以脚本位置定位仓库配置，保留 API/CLI 相对路径语义；路径在模块加载时解析，不放入异步函数。
既有进程/绑定/连接/router 回归 **39 passed，0 failed/errors/skipped**：
`./scripts/run.ps1 -m pytest -q tests/unit/test_processes.py tests/unit/test_registry.py tests/integration/test_connect.py tests/integration/test_router.py --junitxml=reports/example_paths.xml`。
两个示例分别从仓库根、各自脚本目录和仓库外临时目录启动，6 次全部 exit 0；
TTS 客户端完成动作后服务仍在线，启动器退出后自有进程已清理。
通过指定 Python -X utf8 -S scripts/run.py 启动，具体绝对路径命令、cwd 和依赖版本见
reports/example_paths_summary.json；Python 3.12.0、Zenoh 1.9.0、Pydantic 2.13.5、pytest 9.1.1、Ruff 0.16.8。
`./scripts/run.ps1 -m ruff check wrs_agent tests examples scripts` 和 `git diff --check` 通过。

补充 IDE 方式：从 examples/developer 将仓库根目录加入 PYTHONPATH，直接用指定解释器执行
01_zenoh_roundtrip.py，通过；共享环境 Zenoh 1.10.1、Pydantic 2.12.3，未修改共享环境。
普通终端不设置导入路径时直接执行会报 ModuleNotFoundError，使用项目启动器即可加载项目与锁定依赖。
首次 Ruff 的 ASYNC240 已通过将路径解析移到模块级修复，原输出保留 example_paths_lint_initial.txt。
原始配置失败、无导入路径的直接运行失败和 IDE 成功输出均在 reports/example_paths_*.txt。
本轮无剩余失败/阻塞，无新增依赖或协议改动；未运行完整回归、WRS 虚拟、真实模型/音频/硬件验证。
下一入口：在 IDE 重跑 developer/01_zenoh_roundtrip.py；普通终端从仓库根使用
`./scripts/run.ps1 examples/developer/01_zenoh_roundtrip.py`。


## 执行绑定、控制重试与任务句柄（2026-09-18）

已实现四项修复、客户端内部构造 ActionRequest、state_version / 协议 v2，以及 TaskHandle / GoalHandle。context 保留，自动接纳配置外节点或技能未实现。任务整体预检绑定参与实例与控制版本，独立分支保持隔离；Voice 同 ID 并发共享与重试不产生半成品成功；hold/replace 按参与者确认，连续替换仍追踪旧资源；Mock TTS 仅在历史全为已知终态时重新准入。

最终执行 `./scripts/run.ps1 scripts/verify.py --wrs`：**243 passed**（187 unit + 51 真实 Zenoh/Mock + 5 WRS 虚拟），0 failed/errors/skipped。标记选择的 deselected 属于分组运行，两个集成分组共同覆盖全部集成测试。所有验收示例（含新 task_handles）、Ruff、doctor 通过。`git diff --check` 单独通过；现有 WRS_AUDIT 换行提示不影响检查。

新增回归覆盖重启后旧任务拒绝、已提交不明动作 UNKNOWN、控制查询失败/回复丢失/并发重试、无关 TTS 离线、TTS 历史恢复、独立版本校验、连续替换、排队结果、4096 容量、重连与多客户端按 ID 查询、Runtime 重启旧 ID 不存在、等待超时/关闭观察/断开客户端不取消执行，以及后续规划失败不改写旧结果。

证据：`reports/revision_summary.json`、`reports/acceptance.json`、`reports/unit.xml`、`reports/zenoh.xml`、`reports/wrs.xml` 及对应 txt。切片证据为 revision_slice1.xml、revision_unit.xml、revision_zenoh.xml、revision_handles.xml、revision_observation.xml。迁移中出现过 4 项旧 Action 导入失败，已修复并完整复测；原失败记录 revision_slice2.xml 保留。首次 Ruff 报告的导入位置及长行已修复，最终输出 All checks passed。

依赖未变：Python 3.12.0，Zenoh 1.9.0（router 同版），Pydantic 2.13.5，pytest 9.1.1，pytest-asyncio 1.4.0，Ruff 0.16.8；WRS 固定 2bb014b747833c2fd9345115fbe26ffb11376f20。无新增包、锁文件或 submodule 变更。

未验证：实机、真实音频、付费模型、跨机认证/ACL、延迟指标及真实抓取；WRS 证据限 Lite6 虚拟 FK。任务/规划历史为 Runtime 会话内存，重启不恢复；动作日志仍保留。协议 v2 无旧字段别名，外部客户端与节点需一起升级。当前授权范围无剩余失败或阻塞；context 改造与动态接纳按用户要求留待讨论。没有 commit/push。

关键文件：wrs_agent/runtime.py、actions.py、nodes/actions.py、nodes/voice.py、nodes/agent.py、schemas.py、handles.py、system.py、sync.py、transport.py；对应 unit/integration 回归和示例一并迁移。完整调用链见 [task_handles.md](task_handles.md)，下一入口：`./scripts/run.ps1 examples/tasks/05_task_handles.py`。


## 结构化错误与技能合同版本（2026-09-19）

本轮只实施高收益的两项：统一 ErrorInfo / AgentError，以及节点声明 name -> version 并校验技能合同。参数 Schema 仍来自唯一的本地参数模型，Node Registry 不复制合同。Runtime 整体预检、节点准入、技能检索与计划缓存都检查版本；不兼容时任何分支都不会开始执行。普通 step()/action() 自动采用本地注册版本。

错误保留 code、stage 和已知的节点/任务/动作身份。提交前超时为 FAILED；已提交且无法查询确认的动作才为 execution_unknown / UNKNOWN。服务不返回任意异常或验证输入，规划缓存诊断也只保存错误码。资源冲突不停止其他客户端的动作，既有节点内最终准入继续生效。同步和异步共用实现；未改造 context、start/bindings 名称，未增加自动接纳、多实例路由或设备所有权服务。

`./scripts/run.ps1 scripts/verify.py --wrs` 全部通过：205 unit、53 Zenoh/Mock、5 WRS virtual，以及全部验收示例（含新增 errors_and_versions）、Ruff、doctor。末次审查将规划缓存诊断由异常原文改成错误码，新增一项回归后，`./scripts/run.ps1 -m pytest -q tests/unit --junitxml=reports/errors_final_unit.xml` 为 **206 passed**；规划、句柄、错误协议定向复测 **11 passed**，最终 Ruff 与 diff --check 通过。因此当前总数 **264 passed（206 + 53 + 5），0 failed/errors/skipped**，相对前轮新增 21 项测试；11 项复测不重复计数。各集成分组选中的 deselected 不算 skip。

新增证据覆盖：独立 TTS 进程重启后声明 speak@2，整个旧版本任务零执行；只用机器人的新任务不受影响；错误跨真实 Zenoh 和客户端重连保留身份；版本 2 匹配时可执行；旧计划缓存失效；离线/未就绪/歧义/未绑定/合同不兼容区分；提交前后故障、同资源冲突、原异常脱敏、规划结果不可被调用方修改。

证据汇总 `reports/errors_versions_summary.json`；完整验收 `reports/acceptance.json`、unit/zenoh/wrs.xml；最终复测 errors_final_unit.xml、errors_final_integration.xml、errors_final_checks.json。首次组合测试为 206 passed / 1 failed，旧 ActionHandle 测试夹具缺少 node_id/task_id，已补齐并加强身份断言；原始失败 errors_complete_targeted.xml 保留。自动审批曾拒绝整文件还原；改为精确匹配撤回本轮三处纯格式变化后通过，无待批准操作。

依赖无变化：Python 3.12.0、Zenoh/router 1.9.0、Pydantic 2.13.5、pytest 9.1.1、pytest-asyncio 1.4.0、Ruff 0.16.8，WRS commit 2bb014b747833c2fd9345115fbe26ffb11376f20。无新依赖、锁文件或 submodule 变更。未验证实机、真实音频、付费模型、跨机 ACL、性能基准和实际抓取；WRS 仅 Lite6 虚拟 FK。当前范围无失败或阻塞，没有 commit/push。

本轮消息合同不兼容：前缀为 wrs/v3/{site}/{target}，Envelope.schema_version=3，skills 从列表变为版本映射，RPC error 变为结构化对象；外部节点与客户端须一起升级。历史动作日志保留、不重播。主要修改 errors.py、schemas.py、transport.py、registry.py、skills/__init__.py、cache.py、actions.py、nodes/actions.py、runtime.py、system.py、handles.py 及对应测试。使用说明见 [errors_and_versions.md](errors_and_versions.md)。下一入口：`./scripts/run.ps1 examples/tasks/06_errors_and_versions.py`；context 和动态接纳继续留待单独讨论。


## 开发交接版：识别文本、节点/技能扩展与 GLM 执行链（2026-09-20）

本轮补齐识别文本 TextInput/TextReceipt、同步/异步 send_text、按规划 ID 重连、Runtime 当前任务中断入口。明确停止在本地控制路径执行，不等待 Planner；同时使待返回规划失效、清空追加队列，按参与资源停止。部分识别不占用去重编号，最终输入按稳定 ID 去重；重复停止不作用于后来的替换任务。Agent 不可达时尝试停止独立机器人动作，但仍报告 UNKNOWN，不能宣称整个任务已停止。

新增自定义 console TTS 节点和 greet 技能，客户端、Agent、节点共享同一合同，展示参数验证、静态绑定、直接 Action、Runtime 任务与取消。GLM 既有适配器增加规划错误保留；新端到端示例通过 HTTP 夹具执行到独立 Mock 节点，真实服务必须显式 --live-model。Mock 对不支持的输入改为 CLARIFY，不再默认生成 home 运动。WRS 复用现有真实 Lite6 FK 示例，不新增虚构抓取能力。

完整命令 `./scripts/run.ps1 scripts/verify.py --wrs`：**293 passed（226 unit + 62 真实 Zenoh/Mock + 5 WRS virtual），0 failed/errors/skipped**。集成标记的 deselected 属于两个分组选择，不是漏跑或 skip。全部验收示例（含 voice_control、custom_skill、glm_runtime）、Ruff 和 doctor PASS。相对前轮新增 29 项测试。

重点覆盖：最终文本输入与重连查询、同时识别/查询不打断、只取消 TTS、停止与显式替换、重复停止不重定向、模型挂起/迟到失效、控制端点鉴权、Agent 离线仍尝试机器人停止、仅 TTS 任务不依赖离线机器人、自定义节点从仓库外工作目录运行，以及 GLM HTTP 401 作为结构化规划错误返回且零动作执行。语音回归末次将停止确认断言改为有界等待，避免把 STOPPING 当 STOPPED；复测 `tests/integration/test_voice_text.py` **7 passed**，不重复计入总数。

交接示例另用两个独立 Python 客户端先后连接同一个自定义节点/Agent，各自完成直接调用、任务与取消；两次客户端退出后服务仍存活，启动器退出后全部自有进程已结束。证据 `reports/handoff_custom_connect.json`。没有创建新的插件平台或依赖注入容器。

本地证据：`reports/handoff_summary.json`、`reports/acceptance.json`、unit/zenoh/wrs.xml、`reports/handoff_voice_final.xml` 及各示例 txt；切片 handoff_text.xml（40）、handoff_extensions.xml（1）、handoff_glm.xml（40）。初次 Ruff 的两处格式问题已修复，最终 All checks passed；diff --check 通过。

依赖无变化：Python 3.12.0、Zenoh/router 1.9.0、Pydantic 2.13.5、pytest 9.1.1、pytest-asyncio 1.4.0、Ruff 0.16.8；WRS 仍固定 2bb014b747833c2fd9345115fbe26ffb11376f20，submodule 无修改。新增端点为 v3 的增量；此前 v3 技能版本/错误合同仍要求客户端和节点一起升级。

未验证/未实现：真实 ASR 与麦克风、有声 TTS、UI、真实 GLM 服务、WRS 抓放/碰撞、实机、跨机 ACL、性能指标和干净机器 WRS 全依赖恢复。context、动态接纳、设备所有权协调、持久任务恢复本轮不扩展。软件验收没有失败或阻塞，这些后续项目不记作已通过。语音输入是识别后的文本及保守词表，不是自然语言理解或硬件急停认证。

交接入口：[DEVELOPMENT.md](DEVELOPMENT.md)、[VOICE_INPUT.md](VOICE_INPUT.md)。后续开发者可分别接 WRS、TTS、ASR 和 UI，按文档合同交付各自的后端与实际证据。可运行命令：`./scripts/run.ps1 examples/tasks/07_voice_control.py`、`./scripts/run.ps1 examples/developer/05_custom_skill.py`、`./scripts/run.ps1 examples/developer/06_glm_runtime.py`。


## 删除任务替换与独立取消（2026-09-20，当前协议 v4）

删除 TaskHandle/Runtime 的 hold、replace，删除 supersedes、任务 HELD/RESUMING 和替换链。保留设备 hold；设备 resume 更名 allow_actions。任务通过 cancel → CANCELLING → CANCELLED/UNKNOWN 独立收尾；确认后 start 创建新任务。TaskCancelReceipt 的 STOPPING 仅表示受理；旧句柄、重复取消与重连始终绑定原任务。context 和自动接纳配置外节点/技能未改动。

最终 **303 passed（235 unit + 63 真实 Zenoh/Mock + 5 WRS 虚拟），0 failed/errors/skipped**。集成测试按标记分两组，deselected 不计为跳过。采用分组执行，已通过的组未重复运行；随后完成 verify.py 清单中的其余示例、Ruff 和 doctor 检查。

实际命令：

```powershell
./scripts/run.ps1 -m pytest -q tests/unit --junitxml=reports/cancel_unit.xml
./scripts/run.ps1 -m pytest -q tests/integration -m 'zenoh and not wrs' --junitxml=reports/cancel_zenoh_initial.xml
./scripts/run.ps1 -m pytest -q tests/integration -m wrs --junitxml=reports/cancel_wrs.xml
./scripts/run.ps1 -m ruff check wrs_agent tests examples scripts
./scripts/run.ps1 scripts/doctor.py --probe-wrs --output reports/cancel_doctor.json
```

其余检查由本地 reports/verify_cancel_remaining.py 顺序运行，17 项全部 exit 0（14 次示例运行，以及 WRS 测试、Ruff、doctor）。包含任务句柄、文本停止、自定义节点/技能、GLM 离线适配、WRS 完成/取消等全部验收示例；完整命令及输出文件列表见 reports/cancel_checks.json。

新增 10 项回归：取消空闲 TTS 时撤销在途旧动作；独立取消排队项；任务取消前/后另一次设备 hold 都不能被自动解除；取消中重启不控制新实例；原动作状态延迟、UNKNOWN、缺失、成功但未验证四种结果；真实 Zenoh 的取消回执丢失和并发重复不能误停新任务。既有资源隔离、旧任务跨重启、Voice 控制幂等、句柄重连与观察超时回归均迁移并保留。

开发者中断示例实际输出：持物停止后仍持 A、旧请求 stale_epoch、迟到模型失效；随后独立 start 的新 task_id 完成 A → C。普通任务例子使用识别后的文本，不使用旧的自动替换回放。旧的重复历史 API 说明已收敛为当前用法，Git 和本文件保留历史验收。

首轮 unit 为 225 passed / 1 failed：原测试在动作尚未 RUNNING 时就取消，却断言实际执行次数；恢复等待 RUNNING 的条件后，保留次数断言并通过最终 235 项。首轮 Ruff 格式与未使用导入已修复。初始 unit 证据 reports/cancel_initial_unit.xml 保留，未伪造为通过。

汇总与证据：reports/cancel_summary.json、cancel_checks.json、上述 XML、cancel_doctor.json 和各 cancel_*.txt。依赖未变：Python 3.12.0、Zenoh/router 1.9.0、Pydantic 2.13.5、pytest 9.1.1、pytest-asyncio 1.4.0、Ruff 0.16.8。WRS 固定 2bb014b747833c2fd9345115fbe26ffb11376f20，submodule 干净；没有新增依赖或锁文件变更。

协议使用 wrs/v4 与 Envelope.schema_version=4，外部客户端和节点需一起升级，无旧端点兼容层。真实硬件、GLM、ASR/有声 TTS、UI、跨机 ACL、性能与干净机器 WRS 依赖仍为 UNVERIFIED；不作延迟或安全认证声明。DimOS 仅核对参考源码，取舍见 [节点与消息](NODES_AND_MESSAGES.md)，未引入新 Module/Stream 框架或传输依赖。

下一开发入口：[开发交接](DEVELOPMENT.md) 与 examples/developer/05_custom_skill.py；分别推进 WRS、TTS、ASR、UI，任务控制统一使用 cancel/wait/start。


## 2026-09-20：全部示例重写

本次把所有示例改成独立场景，删除旧 developer 组合脚本及参数切换方式。现在有 33 个入口文件、1 个共享技能文件；最长 Python 教学文件 54 行。普通动作/任务使用直接的同步代码，常驻服务和底层通信使用单一 async main。地址、目标和配置在文件中明确给出。

- 23 个可自行结束的离线示例：基础 4、任务 6、Voice 文本 4、WRS 虚拟 3、模型离线 2、传输 4。
- 8 个配对入口：connect 的服务/客户端 2 个；nodes 的 Router/Speaker/Agent/直接调用/任务/取消 6 个。测试启动真实 Router 和独立节点，从其他工作目录运行客户端，确认客户端退出后服务继续运行，最后清理自身进程。
- 2 个真实 GLM 入口默认关闭，只测试未经代码 opt-in 时拒绝运行；没有付费或外网模型调用。
- `greet_skill.py` 是唯一共享合同与实现，不是另一份启动脚本。

节点运行逻辑从 CLI 提取到 `wrs_agent/nodes/serve.py`，通过明确关键字参数调用；节点创建函数只接收日志路径。CLI 和 Python 示例复用同一逻辑，没有新增插件、传输、调度器或协议。Skill.arguments 仍表示技能参数合同，和已删除的示例命令行参数解析无关。

实际运行：

```powershell
./scripts/run.ps1 scripts/verify.py --wrs
./scripts/run.ps1 -m pytest -q tests/integration/test_task_identity.py::test_cancel_while_holding_keeps_effects_and_rejects_late_work --junitxml=reports/examples_interrupt.xml
./scripts/run.ps1 -m ruff check wrs_agent tests examples scripts
git diff --check
```

第一条完整验收：243 unit、64 Zenoh/Mock、5 WRS virtual，共 312 passed；23 份有限时长示例逐份运行，退出码和关键结果全部符合预期，Ruff / doctor 通过。`reports/acceptance.json` 共 28 项 PASS、0 FAIL；7 项未验证范围独立保留，不计入通过。

最终审阅将旧中断大脚本中的组合断言迁入一条正式回归，并单独运行通过：持有 A 时取消，保持已发生的抓取效果；停止前的动作凭证被拒绝；迟到模型结果失效；新任务只执行放到 C 和验证。最终唯一测试合计 **313 passed = 243 unit + 65 Zenoh/Mock + 5 WRS virtual**，0 failures/errors/skipped。不是声称新增测试已包含在前一次完整命令中；增量证据为 `reports/examples_interrupt.xml`。新增回归后再次执行 Ruff 和 diff 检查通过。

测试开发过程中，配对测试最初误查不存在的 request/agent/status，出现 1 failed / 41 passed；修正为现有 request/task/status 后两项配对测试通过，并在完整验收中再次通过。初始静态检查提示异步函数使用阻塞进程创建，已改为 asyncio subprocess；没有放宽检查规则或制造 PASS。

证据保存在本地 `reports/unit.xml`、`zenoh.xml`、`wrs.xml`、`examples_interrupt.xml`、`example_*.txt`、`doctor.json`、`examples_rewrite_summary.json`。修改过的 Markdown 相对文件链接全部有效；examples 中不存在 argparse、sys.argv 或 parse_args。旧故障语义保留在正式测试，不再嵌入教学脚本。

验证环境：Python 3.12.0；eclipse-zenoh / zenohd 1.9.0；Pydantic 2.13.5；pytest 9.1.1；pytest-asyncio 1.4.0；Ruff 0.16.8。WRS gitlink 仍为 `2bb014b747833c2fd9345115fbe26ffb11376f20`，submodule 无改动；WRS 探测依赖 numpy 1.26.4、scipy 1.16.2、mujoco 3.5.0、wgpu 0.32.0、websockets 15.0.1。未变更依赖或锁文件。

本次软件和示例无剩余阻塞。WRS 抓放、硬件、真实 GLM、真实 ASR/音频、独立 Vision、双机保护配置和性能仍未验证；默认无录音和权重下载。context、Blueprint、动态接纳继续留待讨论。交接下一入口为 `examples/nodes/greet_skill.py`、`examples/nodes/01_start_speaker.py` 和 `docs/DEVELOPMENT.md`。沿用用户选择，只保留本地提交，不上传。


## 2026-09-20：state 字符串枚举

公开导出 ActionState、TaskState、GoalState（Python 标准库 StrEnum）。ActionStatus、TaskStatus、TaskCancelReceipt、GoalStatus 和 GoalResult 返回对应枚举；Runtime / ActionExecutor 使用枚举成员表达状态变化，Journal 重启恢复显式写入 ActionState.UNKNOWN。TaskCancelReceipt 仍只允许原有五个状态，不放宽为所有 TaskState。

保持原字符串值、协议 v4、JSON 和 SQLite 文本格式。状态边界只转换合法字符串，Boundary 的 strict=True 保留，其他字段不放宽。model_dump() 保留枚举，mode="json" / model_dump_json() 仍输出字符串；旧字符串比较、打印、哈希查找可继续使用。Runtime 总览与节点目录保持原始字典；IDLE、步骤结果、控制 phase 和设备 admission 不纳入这三个结果枚举。

实际执行 `./scripts/run.ps1 scripts/verify.py --wrs`：**390 passed = 320 unit + 65 Zenoh/Mock + 5 WRS virtual**，0 failures/errors/skipped；23 份离线示例逐份通过，配对服务/客户端测试通过，Ruff、doctor、git diff --check 和修改文档的本地链接检查通过。verify 报告为 28 项 PASS、0 FAIL、7 项 UNVERIFIED。

新增 77 项参数化兼容性检查，覆盖所有原状态值从 Python 字典/JSON 解码、枚举身份、嵌套回执、原字符串比较与序列化、精确 Schema 合法值、无效/跨域状态、取消回执子集、其他字段严格验证及旧 SQLite 日志恢复。既有真实 Zenoh 同步/异步、watch、重连、取消、规划、WRS 测试增加枚举身份断言，同时保留既有字符串断言验证兼容。

开发首轮直接将枚举类传入 BeforeValidator，触发 Pydantic validator-signature 导入错误；改为显式单参数转换后，合同/执行器重点组 31 passed，枚举/Runtime/取消重点组 98 passed，随后上述完整验收通过。没有调整全局 use_enum_values、关闭 strict 或跳过失败用例。

证据：本地 reports/state_enums_summary.json、acceptance.json、unit.xml、zenoh.xml、wrs.xml、example_*.txt 与 doctor.json。环境仍为 Python 3.12.0、Pydantic 2.13.5、Zenoh/router 1.9.0、pytest 9.1.1、pytest-asyncio 1.4.0、Ruff 0.16.8；依赖、锁文件、WRS gitlink 未变。真实硬件/GLM/ASR/音频没有调用，既有未验证范围未改变。

本次无剩余实现阻塞；用法见 [状态枚举](task_handles.md#state-的字符串枚举) 和两个更新的取消示例。WRS backend 接口的待澄清项不影响本改动，也未因此连接其他 backend。沿用用户选择，只本地提交，不上传。


## 2026-09-21：进程启动可移植性

最终定向回归 56 passed / 0 failed / 0 skipped，覆盖另建含空格/中文路径虚拟环境、普通 site-packages 子进程、文件锁跨进程互斥/释放、自定义 Router、版本/凭据检查、独立节点示例及 TTS 取消复测。本轮 Python 文件 Ruff、git diff --check、PowerShell PATH 解释器入口通过；bootstrap 仅语法解析，未重装依赖。

全量 verify.py --wrs 实际 exit 1：332 unit passed、Zenoh 67 passed / 1 failed、WRS 虚拟 5 passed。TTS 取消等待超时在后续定向组中通过，初始失败原因未确定，保留原证据。运行期间另一任务修改 WRS 技能、示例和验收目录；旧进程持有原目录，遇到序列输出改变、缓存/离线模型示例删除，以及新模型示例的一条 Ruff 行宽错误。因此不宣称本轮完整验收通过。

原节点端口 7448 已占用，没有终止该服务；测试复制脚本到临时目录，仅替换端口/env_id 后独立运行，保留相同合同与处理函数。其他 WRS/示例改动保留；本轮 WRS 文件只调整科学依赖路径。

证据及完整命令：reports/portable_processes_summary.json、portable_final_tests.xml/txt、portable_full_acceptance.json、portable_verify.txt、portable_doctor.json。Windows/Python 3.12.0；Zenoh/router 1.9.0，Pydantic 2.13.5，pytest 9.1.1，pytest-asyncio 1.4.0，Ruff 0.16.8。Linux/macOS、独立 wheel、真实模型/音频/硬件未验证。未提交或推送。下一入口：并行改动完成后重跑完整验收，再在 Linux/macOS 验证原生文件锁和启动/退出。


## 2026-09-21：在线模型示例与实际 WRS 节点验收

models 收敛为 01_plan.py（在线提出计划）和 02_execute.py（在线规划后 WRS 执行），移除代码关闭开关与离线执行入口。固定 GLM 协议样本移至 models/fixtures，所有测试引用已迁移；旧 developer 缓存空目录删除。凭据只从环境读取，没有写入代码；GLM_API_KEY 与 GLM_MODEL 当前未配置，在线账号调用记为 UNVERIFIED。

所有机器人教学脚本显式使用 wrs_virtual；原 Mock 抓放示例改为命名姿态、相对位移、观察，Mock 缓存演示删除，缓存回归测试保留。方向移动由固定 WRS Lite6 实际 IK/FK 完成；世界坐标系每次非零总位移最多 5 cm，保持目标朝向、限制关节与近邻解，末端结果实测验证。控制循环不等待运动锁；停止期间迟到的 IK 不会执行；不可达明确 FAILED 并保留原状态。

新增独立 WRS 服务、方向控制客户端与只读 viewer；viewer 使用 WRS 原生页面，不另建前端框架。页面/场景推送在回环，停止观察不取消任务。节点按原规则带历史日志重启后 HELD，控制客户端先查询停止确认，再显式 allow_actions 允许新任务；UNKNOWN 不自动解除。集成测试使用临时端口、命名空间和示例副本，保留用户正在运行的服务与日志。

最终分组证据：**419 passed = 344 unit + 68 Zenoh + 7 WRS**，0 failures/errors/skipped；**21 份有限机器人示例**逐份通过，Ruff、doctor、git diff --check 与更新文档的本地链接检查通过。独立 WRS 节点/客户端/viewer、重启与退出清理包含在 7 项 WRS 中。额外捕获真实 scene_init 和 14 条 scene_update，任务 SUCCEEDED，关闭 viewer 后仍可查询节点。没有实际检查浏览器 GPU 画面，此项仍 UNVERIFIED。

原全量 `scripts/verify.py --wrs` exit 1，真实历史报告保留：unit 的 15 个失败来自一处以多个路径片段构造的旧 fixture 路径；WRS 的 1 个失败来自示例固定日志重启后仍处于 HELD。修复后分别运行 `-m pytest -q tests/unit --junitxml=reports/wrs_examples_unit.xml`（344 passed）及 `-m pytest -q tests/integration/test_wrs.py tests/integration/test_wrs_examples.py --junitxml=reports/wrs_examples_final.xml`（7 passed）。68 Zenoh、全部 21 示例和静态检查在全量中通过，未把原失败结果改写成成功；上面的最终数量由最终各组证据汇总。

所有 Python 命令使用 `D:\code\venv312\.venv\Scripts\python.exe -X utf8 -S scripts/run.py`。证据及完整命令见 reports/online_wrs_summary.json、wrs_examples_unit.xml、zenoh.xml、wrs_examples_final.xml、wrs_scene_evidence.json 与 example_*.txt。环境：Python 3.12.0、Zenoh/router 1.9.0、Pydantic 2.13.5、pytest 9.1.1、Ruff 0.16.8；WRS 科学依赖 numpy 1.26.4、scipy 1.16.2、mujoco 3.5.0、wgpu 0.32.0、websockets 15.0.1。固定 WRS gitlink 与依赖锁未变，未安装新依赖或连接硬件。实际抓放、碰撞规划、ASR/音频、跨机与性能仍未验收。

工作区另一路可移植性修改已保留，本轮未提交或上传。下一入口：配置真实 GLM 账号后先运行仅规划示例，再运行执行示例；浏览器打开 WRS viewer 检查 WebGPU 画面。

## 2026-09-21：GLM 环境配置错误提示

- [x] 复现只有 Key/地址、GLM_MODEL 为空时的 Pydantic string_too_short；原输出保留 reports/glm_model_config_before.txt。
- [x] GLMConfig.from_env 将缺失/空白模型、非法模型名/地址转成明确的 GLMError；GLM_API_KEY、GLM_BASE_URL 不代替模型选择，不猜测账号可用模型。
- [x] 01_plan/02_execute 在创建 HTTP 客户端或启动节点前，用对应环境变量的提示退出；不回显输入值。配置模板与示例文档补充 IDE 加载 .env 和 GLM_MODEL 的要求。
- [x] 指定解释器完整单元测试 **356 passed，0 failed/errors/skipped**；Ruff、git diff --check 通过。两个真实示例子进程在缺失模型的夹具环境下按预期 exit 1，仅打印清楚的配置提示，无 traceback。

命令前缀为 D:\code\venv312\.venv\Scripts\python.exe -X utf8 -S scripts/run.py；
单元命令尾部为 -m pytest -q tests/unit --junitxml=reports/glm_model_config_unit.xml；
Ruff 为 -m ruff check wrs_agent tests examples scripts。
全部命令、cwd、依赖版本和证据见 reports/glm_model_config_summary.json。
本轮没有读取或修改用户 .env/凭据，没有发送付费请求或运行 WRS/硬件；在线成功仍未验证。
下一入口：用户在 01_plan/02_execute 对应运行环境配置 GLM_MODEL 为账号实际可用的模型 ID，再运行在线示例。


## 2026-09-21：WRS 后端名称与可读 viewer 示例

用户确认保留真实 WRS 接入，将 wrs_virtual 统一为 wrs。CLI、LocalStack、serve_node、能力声明、当前示例和测试同步迁移；旧值在三处明确拒绝，不保留别名。仿真与实机区别仍通过 hardware=false、FK 验证与停止范围说明，不把真实 WRS 模型等同真实设备。

07_viewer.py 显式创建 World/Lite6/坐标轴，读取节点初始状态，在定时回调中检查启动实例和有效状态后更新 FK，最后关闭显示。show_wrs/create_viewer 包装已删除；viewer_hub 仅管理页面服务生命周期。并行任务新增的示例口令读取逻辑保留。

最终相关回归 85 passed（78 unit + 7 WRS），0 failures/errors/skipped；另在并行凭据改动到达后复测 viewer/独立节点/客户端组 1 passed，不重复计入总数。5 份代表性有限示例通过：beginner/01_action、tasks/01_sequence、voice/01_stop_task、transport/03_submit、wrs/04_move_relative。相关文件 Ruff、git diff --check 和修改文档链接检查通过。未重跑完整仓库测试；全仓库 Ruff 期间观察到另一组正在编辑的示例口令文件格式问题，未覆盖其工作。

首轮单元组 76 passed / 2 failed：并行 GLM 默认模型变更与缺失模型测试冲突；另一任务恢复显式模型配置后同一组重跑 78 passed，本轮未更改 GLM 行为。证据：reports/wrs_backend_rename_summary.json、wrs_backend_unit.xml（首次）、wrs_backend_unit_final.xml、wrs_backend_integration.xml、viewer_explicit_final.xml、wrs_backend_examples.json。命令使用固定 Python 经 scripts/run.py 执行，完整参数见汇总。依赖和 WRS gitlink 未改变，无硬件/在线模型调用；浏览器 GPU 画面仍未人工检查。未提交、未上传。

## 2026-09-21：本机示例自动共享口令验收

三组分进程示例（connect/nodes/wrs）已接入 examples/_session.py：首次由服务随机生成，原子写入 Git 忽略的 .local/example_tokens；配套客户端从同一仓库加载，设置当前进程环境。显式 WRS_AGENT_TOKEN 优先且不写文件；空值使用自动配置，非法值/损坏文件报错；不显示或记录口令。客户端首次先启动时，提示准确服务入口和显式配置的处理方式。模板/示例文档补充手动生成命令、启动顺序、重置步骤与本机范围。

**375 单元 + 9 集成 = 384 passed，0 failed/errors/skipped**（最终分组结果）。
单元命令：指定解释器 -X utf8 -S scripts/run.py -m pytest -q tests/unit --junitxml=reports/example_tokens_unit.xml。
集成组：tests/integration/test_example_token_connect.py、test_developer_examples.py、test_connect.py、test_wrs_examples.py，首轮 8 passed；自动口令测试随后扩展为 TTS/WRS 两个参数化场景，复测 2 passed，替换原 1 项自动口令场景后共 9 项，不重复计数。最终自动口令用例验证服务与客户端环境均没有 WRS_AGENT_TOKEN、实际动作成功、错误口令仍被拒绝、日志不含口令、客户端退出服务仍在运行。测试使用临时口令目录和独立端口/namespace，不修改用户 .env 或正在运行的服务。
新增 helper 单元检查 16 项，包含四个真实并发子进程首次生成时共享同一完整口令；最终针对 helper/自动连接的复测为 17 passed，WRS 参数化后自动连接组另有 2 passed。

Ruff 全仓库与 git diff --check 通过。测试开发中先修复 unit/integration 同名导致的收集冲突，再修正错误口令断言应匹配 AgentError（实际拒绝行为正常）；首次证据保留。命令、依赖版本、输出见 reports/example_tokens_summary.json、example_tokens_*.xml/txt。
当前 Windows 上验证；POSIX 权限断言仅在相应平台执行，Linux/macOS 未验证。核心 connect/Transport 权限规则未改，自动配置只用于受信任本机示例；未运行完整网络回归、真实模型/音频/硬件或浏览器 GPU 验证。下一入口：先运行 examples/wrs/05_start_node.py，再运行 06_control_arm.py 或 07_viewer.py；已有非空手动口令时仍需各进程一致。

## 2026-09-21：GLM 网络诊断与显式代理配置

新增脱敏 DNS/TLS/证书/代理/连接/协议错误码；通过异常类型和有限 cause/context 链分类，不记录异常原文、Key、响应体或代理凭据。01_plan 在请求失败时打印明确说明并正常清理节点/HTTP 客户端。原 Runtime 的结构化错误会保留新代码和静态说明。
新增可选 GLM_TRUST_ENV（默认 0）：1/true 使用 HTTPX 的系统/环境代理与 CA 配置；默认直连不读取代理或 CA 环境。核实 HTTPX 0.28.1 中显式 transport 会关闭环境代理发现，因此 opt-in 使用标准 transport；离线 MockTransport 始终禁用环境代理。未修改用户 .env、系统代理/DNS，也未关闭证书验证或切换模型端点。
scripts/check_glm_connection.py 使用无 Authorization 的 GET，只检查网络，不读取 Key、不调用模型、不启动机器人。--trust-env 用于单独比较代理路径；401/404 等也可表明已收到 HTTP 响应。

实测当前环境直连 cause=socket.gaierror、Windows 11001；系统代理 127.0.0.1:10808，首次探测为 SSLEOFError，后续诊断为 glm_timeout。两条路径均未收到 HTTP 响应，因此当前网络仍未连通，账号/模型调用未验证。没有修改或隐去这些失败结果。
最终相关回归 **400 passed，0 failures/errors/skipped**：指定解释器 -X utf8 -S scripts/run.py -m pytest -q tests/unit tests/integration/test_glm_runtime.py --junitxml=reports/glm_network_regression.xml。覆盖错误链分类、敏感输入不回显、异常后清理、显式代理选择、离线夹具隔离、无认证诊断及既有 GLM/Zenoh 软件行为。Ruff 全仓库与 git diff --check 通过；首次行宽问题仅格式修正。
证据：reports/glm_network_summary.json、glm_network_regression.xml/txt、glm_network_lint.txt、glm_network_probe.json、glm_dns_proxy_probe.json、glm_connection_direct.txt、glm_connection_system_proxy.txt。
下一入口：先让 check_glm_connection.py（直连或 --trust-env）取得 HTTP 响应，再在模型进程设置对应 GLM_TRUST_ENV 并重跑 01_plan。未发送真实模型请求、付费调用或硬件动作；不把离线回归通过视为外部网络已修复。


## 2026-09-22：Qwen 本地中文 ASR / TTS 与 WRS 语音例子

新增 qwen-asr/qwen-tts 互斥 extras 和真实 uv.lock，两个环境由固定 Python 3.12.0 创建到 .local/venvs；uv pip check 均通过（ASR 97 包，TTS 91 包）。核心不安装语音依赖。模型固定官方提交、Apache-2.0 声明与全部文件内容哈希，已显式下载并校验；没有 API Key、录音上传、硬件控制或默认声卡调用。

接入沿用 Voice 文本输入、Task 取消与 speak 动作合同。模型/设备调用在线程中，停止生成后丢弃迟到音频，播放 abort/close 无法确认时 UNKNOWN。固定中文指令精确匹配，有词汇提示但没有模糊运动授权；识别期间实例或 control_epoch 变化会拒绝旧输入。WRS 08 服务、09 ASR 客户端与 07 viewer 展示完整链条，播报与运动并行；固定播报启动前预合成。

核心最终全量单元 **429 passed**（reports/qwen_core_unit_final.xml）；原有 Zenoh/WRS 集成 **77 passed**，新增生产语音适配 + 真 WRS/Voice/Zenoh 的取消集成 **1 passed**，后者声音设备使用替身，不算真实声卡验证。另执行 voice/01_stop_task、wrs/04_move_relative 两个有限真实 WRS 例子通过。末尾补充查询显示后再对语音相关组复测，见最终汇总。Ruff、uv lock --check、默认 core requirements 导出与示例目录检查通过。

真实模型证据：Qwen TTS 加载 8.35 秒，两个样本生成 4.64 / 2.55 秒；生成中发出停止后 0.302 秒返回无音频结果。WRS/Voice/TTS 加载并预合成七句约 44.27 秒；同时 ASR 推理时整张 GPU nvidia-smi 采样峰值 5457 MiB（含桌面其他占用）。中文 ASR 加词汇提示后，两条合成样本“向上”“停止”均精确匹配，0.132 / 0.129 秒；不含收音与截句时间，不是统计性能承诺。初次无词汇提示的“向上”识别为“想上”，未把这一失败隐藏为成功，也没有将误识别映射为运动。

真实收音、声卡播放/取消、回声、方言/噪声准确率、现场端到端停止延迟仍 **UNVERIFIED**。该限制不通过 mock 结果替代。具体安装/启动命令见 QWEN_SPEECH.md；原始证据 reports/qwen_*.txt/json/xml 与 .local/speech-check。默认脚本只观察/检查，不自动开麦或播放。保留原有用户及并行更改，未提交或上传。


## 2026-09-22：WRS TCP 字段与并行感知设计

完成状态命名与语义迁移：kinematics.joints → qs，tip_position → tcp_pos；新增 tcp_name 与 tcp_rotmat。固定 WRS 的 Lite6 注册 flange TCP，适配器现在读取该具名 TCP，IK 和到位检查使用同一对象；修复原实现依赖最后连杆与零工具偏移重合的假设。所有当前示例、viewer、测试和 doctor probe 同步迁移，RobotData.pose 仍为命名姿态标签。消息封装/Zenoh v4 路径未变，但运动学字段不向后兼容，服务与客户端需同步更新重启。

真实命令（cwd 为仓库根目录）：
```powershell
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit tests/integration/test_wrs.py tests/integration/test_wrs_examples.py tests/integration/test_wrs_tcp.py tests/integration/test_example_token_connect.py --junitxml=reports/wrs_tcp_regression.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m ruff check wrs_agent tests examples scripts
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py examples/wrs/01_move.py
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py examples/wrs/04_move_relative.py
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py examples/tasks/01_sequence.py
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py scripts/doctor.py --probe-wrs --output reports/wrs_tcp_doctor.json
git diff --check
```

结果：**433 passed = 423 unit + 10 integration，0 failures/errors/skipped，63.70 s**。新增真实 WRS 工具偏移与旋转测试：TCP 不等于末连杆，TCP 相对移动/朝向保持正确；改变工具偏移后原到位目标不能继续通过验证。既有 IK 迟到停止、取消、任务、独立节点/客户端/viewer、自动口令配对通过。3 份有限示例的预期输出通过，Ruff、doctor、git diff --check 与修改文档本地文件链接检查通过；没有失败被改写或跳过。

环境：Python 3.12.0、Zenoh 1.9.0、Pydantic 2.13.5、pytest 9.1.1、Ruff 0.16.8；WRS 固定提交 2bb014b747833c2fd9345115fbe26ffb11376f20 未修改。科学依赖版本由 reports/wrs_tcp_doctor.json 记录。证据：reports/wrs_tcp_regression.xml/txt、wrs_tcp_lint.txt、wrs_tcp_example_*.txt、wrs_tcp_doctor.json/txt、wrs_tcp_summary.json（实际示例命令和输出检查）。

[状态与并行感知设计](SCENE_AND_PERCEPTION.md) 区分必要的坐标归属与暂不增加的 scene_revision，说明 Node 常驻/Skill 按需、相机独立发布与多个消费者并行订阅。DimOS 参考本地固定提交 29dfda595892dffb91c79f379eb44d1c737f9caf 的 CameraModule、Detection2DModule、backpressure 和 ObserveSkill，没有引入其依赖或复制实现。

SceneData、真实相机、视觉/抓取候选节点仍为设计，未运行模型/麦克风/硬件或真实抓取；浏览器 GPU 画面未人工检查。未重跑全部非 WRS 网络集成。保留其他任务的 Qwen/语音与依赖修改，不提交、不上传。本轮已授权的命名修正及调查完成；下一入口是按设计文档交付有界相机数据流，再扩展具体场景与抓取技能。


## 2026-09-22：启动播报、独立语音入口与示例整理

WRS 01–07 保留机器人/显示；原语音文件移动到 Voice 05/06，01–04 明确文字入口；新增在线 GLM 服务 07、循环短句收音 08 和完整 viewer 09。新增 TTS 01 独立启动/预合成/启动播报、02 提交、03 取消。各目录 README 提供无需模式参数的运行顺序。同步 launch 补齐 tts_backend/tts_python/tts_prepared_texts；核心库不会自动发声。

Voice 本来就是独立 Zenoh 节点；ASR 是独立输入进程，不新增另一套节点注册。普通目标要求“机器人”前缀，停止免唤醒；观察模型/任务的协程不阻塞收音。识别期间 boot_id/control_epoch 变化会拒绝迟到目标。仍为短句分段 ASR，有收音间隙，没有新聊天记忆/流式协议。

真实命令（固定解释器，仓库根目录）：
```powershell
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit --junitxml=reports/voice_examples_unit.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/integration/test_qwen_voice_wrs.py tests/integration/test_voice_text.py tests/integration/test_wrs_examples.py tests/integration/test_example_token_connect.py --junitxml=reports/voice_examples_integration.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit/test_voice_examples.py tests/integration/test_qwen_voice_wrs.py::test_continuous_voice_stop_invalidates_pending_plan_without_waiting_for_model --junitxml=reports/voice_examples_final.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/integration/test_qwen_voice_wrs.py::test_continuous_voice_stop_invalidates_pending_plan_without_waiting_for_model --junitxml=reports/voice_examples_stop_final.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m ruff check wrs_agent tests examples scripts
```

全量单元 462 passed；后续增量 32 unit passed，其中新增 1 项同步参数透传。集成首跑 11 passed/1 failed；新增测试断言先误用当前规划 ID，后未等模型实际进入。修正测试为等待 planner_calls==1，最终复测 1 passed，未改变控制实现。12 个相关集成已分别通过；不隐藏早期失败报告，不把增量重复计入总数。

8 份有限例子通过：Voice 01–04 与 WRS 01–04，真实命令、输出和预期核对见 reports/voice_examples_scripts.json。Ruff、本地文档链接、示例目录和 git diff --check 通过。测试不调用扬声器、麦克风或付费模型。

**UNVERIFIED**：实际启动音播放、声卡停止、循环收音/回声/现场延迟、在线 GLM 语音全链。自动审批拒绝了真实播放探针，理由为此次音频设备副作用缺少明确授权，未执行该命令。软件测试使用音频替身不能代替现场验收；模型安装与既有合成/ASR 数据见 [Qwen 指南](QWEN_SPEECH.md)。完整结果与依赖版本见 reports/voice_examples_summary.json。本轮无新增依赖/协议、不提交或推送。


## 2026-09-22：ASR 的 IDE 工作目录与解释器

修复下载/加载默认目录随 cwd 改变的问题：二者共用项目源码根目录下的绝对 model_root，显式目录与 WRS_AGENT_MODELS 可覆盖，保留版本及文件校验。选错解释器时先提示已准备的 qwen-asr 环境，不先加载 Torch 再报模块缺失。更新 Voice/Qwen 指南；未自动重下权重或改公共 venv。

```powershell
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit/test_speech.py tests/unit/test_voice_examples.py --junitxml=reports/asr_path_unit.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m ruff check wrs_agent/speech scripts/download_speech_models.py tests/unit/test_speech.py
# 下条实际工作目录为 examples/voice，仅加载模型和识别既有测试音频：
& 'D:\code\ch\agentOS\.local\venvs\qwen-asr\Scripts\python.exe' -X utf8 'D:\code\ch\agentOS\reports\asr_path_probe.py'
```

验证结果：64 项相关单元测试通过（speech + voice examples），Ruff 与 git diff --check 通过；首次 Ruff 仅多余空行问题，已修正。实际从 examples/voice 工作目录，用项目内 ASR 解释器完成离线模型加载 11.92 秒、预热 1.10 秒；两条既有合成样本“向上”“停止”均正确识别，推理 0.168/0.147 秒。ASR 与 TTS 资源均定位到项目根目录下既有模型，未重新下载，未绕过校验。公共解释器实际触发新的明确依赖提示。没有开麦、播放、云端请求、节点连接或硬件动作。
证据：reports/asr_path_before.json、asr_path_unit.xml/txt、asr_path_probe.py/json/txt、asr_path_base.json、asr_path_lint.txt。依赖 qwen-asr 0.0.6 / transformers 4.57.6 / torch 2.9.0+cu128，未安装/更新依赖。此修复完成；用户将 IDE 中 Voice/06、08 的解释器切换为 .local/venvs/qwen-asr/Scripts/python.exe 即可使用现有安装。持续收音/现场声音仍不属于本次验证。


## 2026-09-22：按用户要求将 ASR 安装到 venv312

用户明确要求使用已有 D:\code\venv312\.venv，覆盖此前不修改公共环境的默认选择。以 uv pip install 增量安装 qwen-asr==0.0.6、torchaudio==2.9.0+cu128、sounddevice==0.5.6。安装前记录全部可见包版本并作为约束（include-system-site-packages=true，应按 importlib.metadata.version 的实际可见优先级，不能用重复 distribution 的最后一项）；只放开 Transformers 必需的 huggingface-hub<1。最终新增 29 包，仅已有 huggingface-hub 1.3.2 -> 0.36.2；Torch 2.9.0+cu128、Torchvision 0.24.0+cu128、NumPy 1.26.4、SciPy 1.16.2、Pydantic/Zenoh 等原版本保留。没有 sync 清理环境、没有改 Python 基础环境或重新下载模型。TTS 继续使用既有独立环境，两个 SDK 的 Transformers 精确依赖仍不可合并。

实际命令（仓库根目录）：
```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.local/uv-cache'
& '.local/tools/bin/uv.exe' pip install --python 'D:\code\venv312\.venv\Scripts\python.exe' --torch-backend cu128 -c reports/venv312_asr_constraints.txt 'qwen-asr==0.0.6' 'torchaudio==2.9.0+cu128' 'sounddevice==0.5.6'
& '.local/tools/bin/uv.exe' pip check --python 'D:\code\venv312\.venv\Scripts\python.exe'
# 模型验证的实际 cwd 为 examples/voice；探针像 IDE 一样加入项目源码根目录：
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 'D:\code\ch\agentOS\reports\venv312_asr_probe.py'
```

模型验证通过：使用公共解释器离线加载 19.80 秒、预热 1.86 秒；已有合成样本“向上”“停止”正确识别，推理 0.151/0.160 秒。只识别本地样本，不开启音频设备、联网模型或运动节点；不是麦克风延迟实测。独立 WRS Lite6 加载/FK 检查通过。uv pip check 安装前后均只有两项原有缺失（joycon-robotics/hid、scipy-stubs/optype），没有新增冲突，不宣称整个共享环境完全健康。git diff --check 通过。

中间失败：离线 dry-run 因部分缓存缺失而无法解析，联网重试；首次快照重复包读取到系统 Torch 2.10，改为实际可见版本 2.9 后预检查通过；初次裸脚本模型探针没有 IDE 的源码路径，补充同等源码路径后成功；FK 探针首次漏传 tcp 名称，修正为 flange。均为探针/解析阶段问题，未以失败方案修改模型或底层接口。
证据 reports/venv312_asr_before.json、venv312_asr_constraints.txt、venv312_asr_dry_run*.txt、venv312_asr_install.txt、venv312_asr_check.txt、venv312_asr_probe_final.txt/json、venv312_asr_packages.json。Voice/Qwen 运行文档同步更新，不再要求本机用户切换 ASR 解释器。下一入口：IDE 按原命令运行 Voice/06；终端从仓库根目录用同一 Python 加 -m examples.voice.06_push_to_talk。此安装请求完成，无代码提交或上传。

## 2026-09-22：SceneData 快照、静态场景与 viewer

机器人节点的 NodeSnapshot.data 统一返回 SceneData：robot 保存 RobotData，objects 是有界的 ObjectData 映射，frame_id=world，单位 m；保留外层 boot_id/control_epoch/state_version 与执行准入。无重复 scene_revision。Mock 符号位置移至 objects[id].location，缓存/恢复检查同步迁移；SpeechData 不变。旧数据字段无别名，服务与客户端需一起更新重启。

WRS 接受显式 scene=本地 TOML，工作线程建立真实 Scene/SceneObject 并读回物体位姿；首个几何为 box。未知朝向/几何不补成已知，来源为 configuration 的静态物体不冒充传感器观测；物体上限 32，文件与快照受既有消息预算约束。同步/异步 launch、LocalStack、CLI 与直接 serve_node 透传配置。错误配置在启动前拒绝。05 加载 scene.toml 的工作台和方块，07 与 Voice/09 viewer 同步场景，新增 08_scene.py 可独立运行。未加入视觉节点/在线更新协议或碰撞规划；WRS pick/place 仍未实现。

真实命令（固定解释器，仓库根目录，完整参数和示例工作目录另见 reports/scene_summary.json）：
~~~powershell
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit --junitxml=reports/scene_unit_initial.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit/test_scene.py tests/unit/test_cache.py tests/unit/test_node_state.py tests/unit/test_speech.py::test_cancel_during_synthesis_does_not_play_late_audio tests/integration/test_wrs_scene.py tests/integration/test_wrs_examples.py tests/integration/test_example_token_connect.py --junitxml=reports/scene_focused.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit tests/integration --junitxml=reports/scene_regression.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m pytest -q tests/unit/test_scene.py tests/integration/test_wrs_scene.py --junitxml=reports/scene_final.xml
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py -m ruff check wrs_agent tests examples scripts
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py scripts/doctor.py --probe-wrs --output reports/scene_doctor.json
& 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py examples/wrs/08_scene.py
git diff --check
~~~

全量回归：**569 passed、1 failed、0 errors/skipped，316.90 s**（488/489 unit 通过，81/81 integration 通过）。唯一失败为现有 tests/unit/test_speech.py::test_cancel_during_synthesis_does_not_play_late_audio：停止已受理后，测试的假播放函数仍被工作线程调用。代码检查表明 asyncio stop 到线程 Event 的异步转发存在调度窗口；本轮未更改语音实现或掩盖失败，不声称该取消语义已通过。它在 focused 组复查通过，随后全量再次失败，按竞态记录，留给语音任务处理。

最后对 WRS 读回校验与没有 WRS 节点的错误场景配置补测：**21 passed（20 unit + 1 真实 WRS integration）**，是全量中的增量复测，不重复计入通过总数。此前 focused 组为 48 passed / 2 errors：同一个过大输入参数的 pytest 名称被写入 Windows PYTEST_CURRENT_TEST，造成 setup/teardown 环境变量过长；已改为短 ids，保留原失败 XML，后续全量/最终场景测试均通过该项。初始单元 468 passed / 1 speech failed 也保留原始报告。

5 个有限示例通过：beginner/01_action、transport/01_query、wrs/08_scene、wrs/04_move_relative、tasks/01_sequence。08 实际从 examples/wrs 工作目录启动，机器人与 table/A 坐标读回成功，无相对路径错误；命令、输出与预期核对保存在 reports/scene_examples.json 和 scene_example_*.txt。真实 WRS 测试覆盖 Scene 成员/旋转/位姿、未知几何不伪造、独立 viewer 的创建/更新/删除且不影响后端；独立 05/06/07 服务生命周期、动作/任务、缓存/恢复和 TCP 偏移回归通过。

Ruff、doctor WRS probe、git diff --check、示例目录与 123 条本地文档文件链接检查通过。Python 3.12.0、Zenoh 1.9.0、Pydantic 2.13.5、pytest 9.1.1、Ruff 0.16.8；WRS 固定提交 2bb014b747833c2fd9345115fbe26ffb11376f20 未修改，科学包版本见 reports/scene_doctor.json。无新增依赖。

未验证：真实相机/视觉/GraspNet、在线物体更新、实机、碰撞规划、浏览器 GPU 人工画面、真实音频设备、付费 GLM；本轮未调用这些能力。保留其他任务的语音/依赖修改，不提交或推送。后续入口：按 SCENE_AND_PERCEPTION.md 的并行订阅方案，完成有界相机流与可信观测接入，而非把图像塞入 SceneData。


## 2026-09-22：上传前完整验证与 TTS 取消竞态修复

上传整理保留既有四个本地提交；当前工作区的 WRS/SceneData、Qwen、GLM、示例与文档一起作为完整版本检查。发现前述 SceneData 验收留下的 TTS 取消竞态，先通过刻意延迟 stop relay 的确定性测试复现（1 failed，保留 publish_race_before.xml），再修复：合成与播放之间回到控制事件循环检查停止信号，已取消合成的结果不会因线程 Event 尚未同步而开始播放；取消期间仍等待工作线程退出，不把取消协程当作停止确认。没有新增消息协议或节点控制接口。

验证命令（仓库根目录；固定 Python 加 -X utf8 -S scripts/run.py）：
~~~text
-m pytest -q tests/unit --junitxml=reports/publish_unit.xml
-m pytest -q tests/integration -m "not live_model and not audio_live and not hardware" --junitxml=reports/publish_integration.xml
-m pytest -q tests/unit tests/integration/test_qwen_voice_wrs.py --junitxml=reports/publish_final_regression.xml
-m ruff check wrs_agent tests examples scripts
~~~

初次全量单元 489 passed；全部集成 81 passed。修复取消竞态后重跑全部单元及相关 WRS/Voice/TTS 集成，492 passed = 490 unit + 2 integration，0 failed/errors/skipped；两项集成已包含在前述 81 项，不重复计数。全部 22 个有限教学示例通过，逐条真实命令与输出核对见 reports/publish_examples.json。没有自动运行麦克风、扬声器、在线 GLM 或实机例子。

Ruff、uv lock --check --offline、当前本地文档链接、示例目录和暂存区 diff --check 通过；清理 viewer.py 末尾空白。扫描候选文件及既有未推送历史，未发现私钥/常见令牌模式；.env、本机口令、虚拟环境、模型权重、录音和 reports 保持忽略。第三方 WRS submodule 保持原提交且干净。模型缓存、ASR 环境安装与音频验证限制仍按各专题记录，不把软件回归替代真实设备验收。

证据 reports/publish_unit.xml、publish_integration.xml、publish_final_regression.xml、publish_race_before.xml、publish_examples.json、publish_lint_final.txt、publish_lock.txt、publish_scan.json；不上传本机生成的 reports。
