# 技能库

技能是系统会做的事情，例如抓取或播报。普通脚本用 `system.skills("播报")`
查看当前可用技能，用 `system.action("speak", text="你好")` 提交一次动作。

`__init__.py` 中的 `SKILLS` 是一张显式 Python 注册表。每项 `Skill` 把三件事放在一起：
`spec`（技能说明与约束）、`arguments`（参数模型）、`handler`（实际处理函数）。
其中 `SkillSpec` 定义参数、所需能力、资源、验证和恢复约束；参数 Schema 直接由模型生成。
没有单独的 FUNCTIONS/METADATA/SPECS 表，也不由模型或 Markdown 动态加载函数。
`robot/SKILL.md` 和 `speech/SKILL.md` 是给 Planner 的短说明书。
它们采用 Agent Skills 的 `name` / `description` YAML 头部和 Markdown 正文形式，
按机器人和播报分组，不改变现有 `pick`、`place` 等可执行技能名称。

启动时只读这两份随包安装的文档。检索按当前节点能力筛选后，Runtime 将
候选的参数和 `instructions` 一起放入已有 `PlanRequest.skills`。
Planner 只提出计划，Runtime 和执行节点仍检查原有结构化契约。
文档进入技能签名；改变说明后，依赖旧定义的计划缓存不能继续命中。
本项目不实现任意外部技能安装、脚本运行或完整 Agent Skills 客户端。

添加技能时，在同一处定义参数、`SkillSpec` 和函数，加入 `SKILLS`；执行节点再显式选择
自己实现的条目，例如 TTS 使用 `skills={"speak": SKILLS["speak"]}`。WRS 用同一合同绑定
自己的 FK 处理函数，不运行 Mock 处理函数。能力声明、参数校验和分派都使用节点这张表。
启动时拒绝名字、参数 Schema 或函数不一致的注册。

`spec.version` 是该技能合同的正整数版本。能力与节点目录只声明 `{"speak": 1}`，
不复制另一份参数 Schema；绑定配置仍只选择节点。客户端、Runtime 预检和节点准入
检查同一个版本，候选检索及计划缓存也排除版本不匹配的技能。参数或结果语义不兼容时
提升合同版本，单纯更换兼容后端不必提升。当前为精确匹配，不自动协商或降级。
详见 [错误与技能版本](../../docs/errors_and_versions.md)。

处理函数形式为 `handler(state, args, stop, progress)`。`args` 已通过参数模型校验；
确认后置条件后返回 bool。短 Mock 函数直接返回，长操作可以使用 async 函数，检查 stop、
通过 progress 报告进度。阻塞的设备调用仍必须由后端隔离；取消协程不等于设备停止。

最后在 `configs/bindings.toml` 中允许该技能绑定到执行节点。仅修改 TOML 不能让节点执行
未注册的函数；缺少实现仍拒绝。Planner 只接收注册项的 spec（含说明和参数），不会接收函数。
技能描述只说明会做什么；TOML 是执行节点绑定的唯一来源，没有隐含的默认节点。
说明书只解释使用方法，不能重复定义一套不同的权限或参数规则。
当前 WRS FK 节点只支持观察和命名姿态；抓取/放置只在 Mock 验证。

格式参考：https://agentskills.io/specification 。本地参考来源和已知限制见
项目根目录的 `docs/api_simplification.md`；没有复制 HoloAgent 的控制脚本。

自定义技能与独立节点的完整例子见 [开发交接](../../docs/DEVELOPMENT.md)：共享参数合同、静态注册、TOML 绑定、Runtime 调度及取消；先按 [节点示例](../../examples/README.md#nodes) 分别启动节点，再运行 `examples/nodes/03_call_skill.py`。
