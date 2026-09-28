# 技能：声明一次，只在执行端注册

普通脚本通过 `await system.skills()` 查看技能，通过
`await system.action("speak", text="你好")` 提交动作。
客户端和 Agent 从节点发现合同，不导入具体技能包，也不注册处理函数。

## 定义与注册

技能作者只提供参数模型、实现函数及必要的动作说明：

```python
GREET = Skill(
    name="greet",
    arguments=GreetArgs,
    handler=greet,
    description="在控制台打印一句问候",
    resources=("speaker",),
    verification="console_text_complete",
)

executor = ActionExecutor(
    journal, state=state, backend="console", skills=[GREET],
)
```

`GreetArgs` 是 Pydantic 参数模型，`greet(state, args, stop, progress)` 是普通处理函数。
完整可运行代码见 [greet](../../examples/nodes/greet_skill.py)、
[SpeakerNode](../../examples/nodes/01_start_speaker.py) 和
[晚加入节点](../../examples/nodes/06_late_node.py)。

`Skill` 自动从参数模型生成 JSON Schema 和通信数据 `SkillSpec`，作者不再嵌套构造
SkillSpec 或手动传 Schema。资源等集合在构造时固定；`skill.spec` 返回独立的描述副本，
外部修改不会改变已注册合同。注册接收技能序列，不再接受重复填写名字的字典。

## 共享合同与多后端

同一个动作由 Mock、WRS 或实机分别实现时，定义可以省略 handler，在执行端配对：

```python
from wrs_agent.skills.robot import SKILLS

executor = ActionExecutor(
    journal, state=state, backend="my_robot",
    skills=[SKILLS["move_relative"].bind(move_relative)],
)
```

bind 返回新对象，不修改共享定义。单一实现可以直接写在 Skill 构造器中。
参数或动作语义变化时提升 version；修改尚未注册的定义可用标准库
`dataclasses.replace(skill, version=2, arguments=NewArgs)`，通信 Schema 同步生成。

一个包可以定义多个动作，一个 Node 可以提供多个包的动作。包不对应进程。
robot/definitions.py 与 speech/definitions.py 保存各领域定义，包内 SKILLS 只是普通集合。
contracts.py 定义 Skill；catalog.py 提供发现结果的纯检索函数，没有全局注册表。
新增技能不用修改 Agent、客户端、中央目录或普通部署文件。

## 哪些字段改变行为

| 字段 | 使用位置 |
|---|---|
| arguments | 执行端参数校验，包含 Python 跨字段 validator；同时生成 Schema |
| handler | 执行实现，确认后置条件后返回 True |
| name / version | 发现、路由与合同版本匹配 |
| resources | Runtime 检查共享资源的步骤是否声明先后关系 |
| timeout / recovery | Runtime 的动作等待期限与已实现恢复规则 |
| description / instructions / preconditions / verification | 给规划者和使用者的说明；不自动执行检查 |

前置条件与结果验证由后端实际执行；写入字符串不会安装校验器或授予权限。
SKILL.md 是指导材料。技能是否提供由实际注册表决定，不再使用 required_features
反向生成能力并检查自身。没有实现多种停止策略，因此不暴露 interrupt_mode 配置。
停止继续由执行器与后端确认，取消协程不等于设备停止。

机器人实现留在 env/，只有 WRS 适配模块导入 WRS；TTS 实现在 nodes/tts/backend.py。
处理函数不导入模型 SDK 或 Zenoh，阻塞设备调用由后端隔离。

## 启动与动态添加

执行器构造时的 skills 参数和运行期间的 `Node.add_skills(*skills)` 进入同一个校验入口：

```python
self.add_skills(GREET)
```

添加是整批原子操作；同名拒绝覆盖，无效批次不会留下部分注册。
只追加，不提供运行中替换/卸载。接口在执行器所属线程调用，关闭后拒绝添加；
外部线程需通过既有线程安全桥接回到事件循环。
每节点最多 64 项，并校验合同总字节数。追加增加 skill_revision，使目录刷新合同缓存。
不扫描文件、不重载 Python、不从网络安装执行代码。
已有任务保留原合同、提供者和 boot_id；追加不会重定向旧动作。

## 发现、部署与选择

节点的 request/features 从实际注册表发布 specs、版本、资源、boot_id 和 skill_revision。
普通配置中的 `[nodes.*]` 决定 launch 启动哪些进程，不是节点接入白名单。
独立节点可在相同 site/env 中加入，不需要预写入 Agent 配置。

唯一提供者自动选定；多个提供者同名时需要显式选择：

```toml
[skills]
speak = "preferred_speaker"
```

覆盖只选择提供者，不能增加节点能力。已经观察到的提供者离线不会自动切换到其他设备；
目录回收离线描述时仍保留选择/歧义信息。
System.connect(skill_bindings=...) 只影响客户端调用；Agent 的任务选择由其启动参数决定。
LocalStack 的便捷启动清单每个内置角色一个，独立启动的节点不受此限制。

## 预检与升级

step() 提交时从提供者解析并固定版本。Runtime 检查计划结构与资源顺序，
再按节点批量执行纯参数预检；所有步骤通过后才执行任何分支。
预检不创建动作、日志或 lease，不预测未来物理状态，也不授予权限。
实际提交仍检查 boot、epoch、参数、状态与停止条件；缓存不保存动作授权。

同一启动会话不覆盖已有技能；升级需要重启提供节点。
本次开发接口删除 required_features / interrupt_mode，节点和客户端应同批更新。
验证入口：tests/unit/test_skill_registration.py、tests/unit/test_registry.py、
tests/integration/test_skill_discovery.py、tests/integration/test_developer_examples.py。
