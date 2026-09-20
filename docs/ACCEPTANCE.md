# WRS-Agent V1 验收合同

完整 V1 矩阵仍按阶段验收；本轮实际结果见文末及 reports/acceptance.json，未运行项不视为通过。报告必须区分 PASS、FAIL、SKIP、BLOCKED 与 UNVERIFIED。SKIP/BLOCKED 不算通过。

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
| T13 | B | hold 后没有 resume | 新动作也不能自行越过暂停状态 |
| T14 | B | resume | 仅恢复接收资格，不续跑旧轨迹 |
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
