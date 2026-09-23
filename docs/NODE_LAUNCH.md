# 节点启动：每个节点带自己的配置

本文件是启动设计与取舍记录。**状态：设计已确认，代码尚未实现，本文件中的签名和文件名都是待实现的合同，没有任何命令被运行过。** 当前可运行的入口仍是 `launch(backend="wrs", tts_backend=..., ...)`，迁移完成前以代码为准。

## 现在为什么死板

问题不是 `launch()` 参数多，而是节点选项被拉平成一个全局命名空间，同一条规则在六个文件里各写一遍。

一个节点选项今天要穿过 `sync.launch` → `System.launch` → `LocalStack.__init__` → `LocalStack.node_command` → `serve_node` → `__main__` 六层转发。`launch()` 的 13 个参数里有 9 个是某一个节点的（backend、scene、duration、tts_backend、tts_python、tts_prepared_texts、model_provider、live_model、deferred_planner），只有 4 个是部署范围的（bindings、port、site、env_id），而签名看不出哪个属于谁。

具体后果：

- `node_command` 无条件给每个角色都加 `--duration`。`duration=4.0` 原意是 WRS 仿真运动时长，同时也会把 Mock TTS 的每句播报拉到 4 秒。同一个名字在不同角色表示不同的东西。
- `{"mock", "wrs"}`、`0 < duration <= 30`、在线模型的 live-model opt-in 在 `LocalStack.__init__`、`serve_node`、`__main__` 的 argparse 里各有一份。`tests/unit/test_processes.py` 的 `test_cli_rejects_unsafe_configuration`、`test_python_node_entry_rejects_invalid_configuration`、`test_removed_wrs_backend_name_fails` 分别盯着这三份副本。PLANS.md 要求「相同语义只保留一套定义」，这里没做到。
- 角色特例散在启动器里：qwen TTS 用独立解释器是 `node_command` 中间一句替换 `result[result.index("-m"):]` 的隐藏动作，它的默认路径在 `LocalStack.__init__`，它的 300 秒就绪超时是 `_wait_ready` 调用点的一个内联条件。
- 命名已经开始漂：`LocalStack(deferred=...)` / `serve_node(deferred_planner=...)` / `--deferred-planner` 是同一件事的三个名字。

## 目标与不做的事

目标只有三条：选项跟着它的节点走；每条规则只有一份定义；加一个节点选项只改一处。

明确不做：不引入节点基类、自动装配、按名字推断连线、entry-point 发现、多实例命名空间、传输覆盖或协调器。不改动作协议、Runtime 调度、Transport、消息合同和 `System.connect()`。

## NodeSpec 与四个构造函数

一个冻结的数据类加每个已实现角色一个普通函数，风格对齐固定 WRS 提交里 `UR7E(pos=..., rotmat=...)` 的显式构造，以及本仓库已有的 `step()`。

```python
# wrs_agent/blueprint.py
@dataclass(frozen=True)
class NodeSpec:
    role: str                 # wrs / tts / agent / voice
    node_id: str | None       # 默认取 TOML 中该角色的唯一实例
    options: Boundary         # 已按 OPTIONS[role] 校验
    explicit: frozenset[str]  # 调用者真正写出的键，来自 options.model_fields_set
    python: Path | None       # 显式覆盖解释器；不写则按最终 options 推导

def wrs_node(*, backend=..., duration=..., scene=..., fault=..., node_id=None): ...
def tts_node(*, backend=..., duration=..., prepared_texts=..., python=None, node_id=None): ...
def agent_node(*, provider=..., live_model=..., deferred_planner=..., node_id=None): ...
def voice_node(*, node_id=None): ...
```

校验用每个角色一份 Pydantic 模型，是这些规则的唯一定义处，`extra="forbid"`：

```python
class WrsOptions(Boundary):
    backend: Literal["mock", "wrs"] = "mock"
    duration: float = Field(0.4, gt=0, le=30)
    scene: FilePath | None = None
    fault: Literal["grasp", "grasp_once", ...] | None = None

OPTIONS = {"wrs": WrsOptions, "tts": TtsOptions, "agent": AgentOptions, "voice": VoiceOptions}
```

构造函数立即校验，因此非法 backend、越界 duration、不存在的 scene 文件在任何进程启动前失败。`wrs_node(scene=...)` 在自己的构造函数里调一次 `load_scene()` 做 fail-fast——这个知识跟着 WRS 角色，不再是启动器里的一个 `if`。

`explicit` 用 Pydantic 现成的 `model_fields_set` 记录调用者真正写出的键，不额外维护哨兵值。它的作用见下面的合并顺序。

用户写出来是这样：

```python
async with System.launch(
    wrs_node(backend="wrs", duration=4.0),
    tts_node(backend="qwen", prepared_texts=[GREETING, *SPEECHES]),
    bindings=CONFIG,
    port=7449,
    env_id="wrs-demo",
) as system:
```

`launch` / `System.launch` 只保留 `*specs` 加 `bindings`、`port`、`site`、`env_id`。

## 选项怎样跨进程

**一份 options 载荷，不再是 N 个命令行 flag。** `LocalStack` 把合并并校验后的选项写到 `.local/runs/<env_id>/<node_id>.options.json`，命令退化成完全通用的形状：

```
python -m wrs_agent wrs --node-id wrs --endpoint tcp/127.0.0.1:7449 --site local \
    --env-id wrs-demo --journal <run>/wrs.sqlite3 --options <run>/wrs.options.json --bindings <path>
```

走文件而不是内联 JSON 的理由是实打实的：`prepared_texts` 是任意长度的中文短句，Windows 命令行长度和引号转义都不可靠；同时不把参数暴露在进程表里。

`node_command` 因此不再有任何 `if role ==`；`__main__` 删掉 9 个 flag（`--backend/--tts-backend/--tts-prepare/--scene/--duration/--fault/--model-provider/--live-model/--deferred-planner`），只留 7 个通用参数加 `--options`。`serve_node` 的角色到 builder 选择变成一张本地函数表，和现有 `SKILLS` 同一个套路：

```python
BUILDERS = {"wrs": build_wrs_executor, "tts": build_tts_executor}
```

**校验仍然是两次，规则只有一份。** 子进程不信任启动器，`serve_node` 拿到 options 后用同一个 `OPTIONS[role]` 重新解析。options 里不允许出现可导入的模块路径或回调名，符合「只接受本地代码中的明确回调」；`action_factory` 继续只从同进程 Python 传入。options 也碰不到 `suffix`/`actions`/`enabled`/技能绑定。

`python` 和就绪超时在合并后由最终 options 推导，推导表和 options 模型放在一起：`backend == "qwen"` 时使用 `.local/venvs/qwen-tts` 的解释器（因而不加 `-S scripts/run.py` 的依赖垫片）并给 300 秒就绪预算，其余用调用者的 `sys.executable` 和 10 秒。`LocalStack` 只剩 `spec.python or python_command()` 一句。

## TOML 与 Python 的分工

TOML 继续是**授权记录**：哪些 node_id 存在、suffix、是否提供动作、是否启用、哪个技能允许交给哪个节点。这一层不能被示例脚本覆盖。

TOML 新增可选的 `[nodes.<id>.options]`，作为该节点的**默认选项**，使 profile 文件自描述、CLI 不需要任何后端 flag：

```toml
[nodes.wrs]
type = "wrs"
suffix = ""
actions = true
enabled = true

[nodes.wrs.options]
backend = "wrs"
duration = 4.0
```

```powershell
python -m wrs_agent launch --bindings configs/wrs_voice.toml
```

最终取值顺序是 **模型默认 ← TOML options ← spec 的 explicit 键**，逐键合并。有了 `explicit`，`wrs_node(duration=4.0)` 只覆盖 duration，不会把 TOML 里的 `backend = "wrs"` 打回默认的 mock。

`-m wrs_agent launch --model-provider llm --live-model` 由此变成一个 profile 文件里的 `provider = "llm"` / `live_model = true`。付费调用的实际门槛不变：仍然是 `LLM_API_KEY` 等环境变量，没有凭据就在 `LLMConfig.from_env`/`LLMClient` 明确失败；`scripts/verify.py` 不加载这类 profile，自动验收依旧不产生付费请求。

## 几条语义规定

这些规定的作用是把「蓝图是普通值」的好处留下，同时不带上隐式装配：

- **spec 不改变启动成员。** 成员仍由 TOML 的 `enabled` 决定；spec 只覆盖某个已启用节点的选项。给未声明或未启用的节点传 spec 直接报错。因此 `launch()` 裸调用和 `launch(wrs_node(backend="wrs"))` 都还是一行。
- **参数顺序不决定启动顺序。** 启动顺序仍是固定的 `wrs → tts → agent → voice`（voice 依赖前三者），写成模块常量后对 spec 排序，把 `voice_node()` 写在第一个也不会坏。
- **同一 node_id 出现多次时后写覆盖**，用于局部改掉共享 profile：`launch(*WRS_VOICE, tts_node(backend="mock"))`。
- **命名 profile 不需要新机制**：`WRS_VOICE = (wrs_node(...), tts_node(...))` 就是一个模块级元组，用 `launch(*WRS_VOICE, ...)` 展开。

## 从 DimOS 借什么、明确不借什么

补上 [节点与消息](NODES_AND_MESSAGES.md) 里 Blueprint 那一栏的具体取舍。参考版本与许可见 [SOURCES](SOURCES.md) 的 S23。

| DimOS 机制 | 是否借 | 原因 |
|---|---|---|
| 蓝图是冻结的、可组合的普通值，每个组件带自己的配置 | 借 | 正好治好选项拉平的问题，零新依赖、零新基类 |
| 同一组件重复出现时后写覆盖 | 借 | 测试和示例确实需要局部改一个节点 |
| `Module` 基类、`ModuleConfig` 继承、`.blueprint` classproperty | 不借 | 节点仍是 `serve_node()` 调用，V1 不需要共同继承 |
| `autoconnect()` 按 (属性名, 类型) 推断连线 | 不借 | 本项目连线来自 TOML 加 Zenoh key 后缀；靠名字推断等于让命名授予端点权限 |
| `dimos.blueprints` entry-point 发现、`dimos run pkg.name` | 不借 | 按外部包元数据加载代码，违反本仓库的技能/节点注册约定 |
| `.namespace()` 机群、`.transports()`、`.remappings()`、`ModuleCoordinator`、`BlueprintConfigParser` 的动态 `--module.arg` | 不借 | V1 单角色单实例、单传输；引入只增加故障组合与部署项 |

## 这次要消掉的重复

| 现在的位置 | 迁移后 |
|---|---|
| 三份 backend / duration / live-model 规则 | `OPTIONS[role]` 一份定义，进程两端各解析一次 |
| `node_command` 的 wrs / tts / agent 分支与解释器替换 | 无角色分支；`spec.python or python_command()` |
| `LocalStack.__init__` 的 tts_python 默认与 scene 预加载 | `tts_node` / `wrs_node` 构造函数与合并后的推导表 |
| `_wait_ready` 调用点的 qwen 超时条件 | 由最终 options 推导的 `ready_timeout` |
| `deferred` / `deferred_planner` / `--deferred-planner` | 单一键 `deferred_planner` |
| `__main__` 的 9 个后端 flag | `--options` 一个参数；profile 写在 TOML |

## 实施顺序与检查方法

一次一个可运行的纵向切片，不同时动协议和 Runtime：

1. `wrs_agent/blueprint.py`：`NodeSpec`、四个构造函数、`OPTIONS`、合并与推导函数，加单元测试（非法 backend / 越界 duration / 未知键 / 不存在的 scene / 给未启用节点传 spec / TOML 与 spec 的逐键覆盖顺序）。
2. `serve_node` 收 `options`，角色到 builder 换成函数表；`__main__` 删后端 flag、加 `--options`。此时旧 `LocalStack` 仍可工作，便于分步验证。
3. `bindings.load_bindings` 接受可选 `[nodes.<id>.options]` 并保持授权字段的原有严格校验。
4. `LocalStack` 改为吃 spec 列表，删除全部角色分支；`System.launch` 与 `sync.launch` 改签名。
5. 迁移 example 与测试，跑 `./scripts/run.ps1 scripts/verify.py` 与 `--wrs`，把三份重复规则的测试收成一份规则测试加两个进程边界测试。

每一步都要保留真实命令与输出摘要。迁移不得降低现有断言：幂等、停止确认、UNKNOWN、授权与 TOML 绑定检查全部保留。

## 未决与风险

- 公开名称定为 `wrs_node/tts_node/agent_node/voice_node`，避免 `wrs` 与第三方包及 `wrs_agent.env.wrs` 混淆；`agent_node(provider=...)` 取代 `model_provider`，按本仓库既有做法不保留旧别名，仓库内调用方同步迁移。
- `launch()` 的调用点很多（examples 与 tests 合计约 57 个文件），但绝大多数是裸调用或只带 `backend=`，迁移主要是机械替换；实际改动量要在第 5 步统计后记录。
- `[nodes.<id>.options]` 让配置有两个来源。风险由「TOML 只给默认值、spec 逐键覆盖、授权字段不可被 options 触碰」三条约束控制，实现时必须有覆盖顺序的回归测试。
- 本设计只整理本机进程启动。跨机部署、动态接纳未配置节点、一个角色多实例仍然不在范围内。
- 本文写成后新增了可选 `asr` 角色（麦克风与识别在自己的进程，见 [文本合同](VOICE_INPUT.md)）。它复用了同一套待重构的机制：`asr_backend/asr_python/asr_script/asr_vocabulary` 又穿过同样的六层转发，`node_command` 的解释器替换和 `_wait_ready` 的 300 秒条件都改成了 tts/asr 共用的查表。迁移时需要 `asr_node()` 与 `AsrOptions`，这两处共用逻辑应一起收进推导表，不要再按角色写第三份。
