# 依赖与 Git submodule 决策

## 1. 结论

V1 默认只有 `third_party/wrs` 一个 Git submodule。submodule 用来记录独立源码仓库的确定提交，不是“让系统看起来更模块化”的工具。父仓库的 gitlink 记录具体 commit；只写 `.gitmodules` 并不能创建真实 submodule。[S04]

HoloAgent、RPent、DimOS 是设计参考，不是本项目运行依赖。Zenoh 是确定采用的通信库，但 Python 绑定应作为软件包安装，不因使用它就克隆其 Rust 源码进项目。[S02]

## 2. 依赖清单

| 对象 | V1 引入方式 | 必需程度 | 说明 |
|---|---|---|---|
| 用户指定 chenhaox/WRS2 | `third_party/wrs` submodule | WRS profile 必需 | 固定 2bb014b747833c2fd9345115fbe26ffb11376f20；保留本地修改 |
| eclipse-zenoh | Python 包，真实 lockfile | 核心必需 | 固定已测试版本，核对当前 Python API |
| zenohd | 官方发行二进制，版本与校验值写清单 | 默认部署必需 | 不作为 submodule；只在回环地址启动本地 router |
| pydantic | Python 包，v2 系兼容版本由测试锁定 | 核心必需 | 消息/Skill 参数边界校验 |
| asyncio、sqlite3、dataclasses、graphlib、argparse、tomllib | Python 标准库 | 按使用需要 | 不为同样的基础功能重复安装框架 |
| httpx | `glm` 可选依赖及 dev 夹具依赖 | GLM profile 必需 | 0.28.1，直接映射智谱 Chat Completions HTTP；不引入自动工具 Runner |
| anthropic | 后续可选依赖组 | V1 非必需 | Claude 使用原生协议适配，不能假设与 GLM 完全同构 |
| sounddevice、sherpa-onnx | `speech` 可选依赖组 | 真实语音 profile 必需 | 软件包而非 submodule；锁定与目标设备兼容的版本 |
| ASR/KWS/VAD/TTS 权重 | 显式资产清单与本地缓存 | 按语音 profile | 固定 revision、checksum、来源、体积和授权；不放主 Git，不自动下载 |
| numpy、WGPU、MuJoCo、WRS 相关依赖 | 独立 WRS 环境或可选组 | WRS profile 按需 | 不把 README 中所有可选依赖灌入 core |
| pytest、pytest-asyncio、ruff | 开发依赖组 | 开发必需 | 排除 third_party；不要重格式化 WRS |
| HoloAgent/RPent/DimOS | 文档、源码局部阅读 | 设计参考 | 本地忽略的 `.references/`，不递归安装全套依赖 |
| LeRobot/openpi/其他 VLA 平台 | 未来独立模型服务或可选包 | V1 不引入 | 真正要维护源码 fork 时再评估 submodule；权重与代码分开 |
| `wrs-skills` 独立技能仓库 | 未来可选 submodule/包 | V1 不拆 | 仅在多个项目共享、独立版本发布时才值得拆库 |

常规包通过 pyproject 与工具生成的 uv.lock 固定。具体版本必须在目标环境实际解析和测试，本文不伪造“兼容最新版”或已测试版本号。uv 支持依赖与可选依赖管理；lockfile 应由工具生成。[S16]

## 3. WRS 的重要现状

指定 WRS2 fork 具有标准 setuptools pyproject.toml，要求 Python >=3.12，采用 WGPU 查看器；不适用早期 WRS 的归档/无包装假设。[S01]

M0 必须首先识别用户自己的 WRS 分支。若已有工作拷贝，不要覆盖，不要强行改 upstream URL，不要擅自把未提交修改搬进 submodule。新项目中可以引用用户已维护的远程；以后要修复 WRS，应在受控 fork 中修改并提交，然后单独更新父仓库 gitlink。

WRS 的 Python 导入与 Git submodule 是两件事。若目标 commit 有正确 pyproject/setup.py，才使用 editable 安装；否则仅在 WRS Environment 的启动进程使用明确的 PYTHONPATH 或受控安装包装。不在十个模块中散落 sys.path.append，不污染系统 Python，不给 core 测试强制导入 WGPU。

如果 `wrs/__init__.py` 会导入大量可选组件，应根据真实源码决定最小安装或在用户 fork 中做小型兼容修复。不得在主仓库偷偷重写第三方源码并不记录补丁。

## 4. submodule 初始化合同

本轮已创建并固定真实 submodule；下面用于审查/复现，不重复 add。

    git status --short
    git submodule status
    git remote -v

用户已指定唯一远程，当前真实 gitlink 可直接检查：

    git -C third_party/wrs remote -v
    git -C third_party/wrs rev-parse HEAD
    git -C third_party/wrs status --short
    git ls-files --stage third_party/wrs

固定地址为 `https://github.com/chenhaox/WRS2.git`，提交为
`2bb014b747833c2fd9345115fbe26ffb11376f20`。

预期最后一条显示模式 `160000` 和实际 SHA。父仓库提交时应包含 `.gitmodules` 与 gitlink；版本提交和 push 需用户授权；2026-09-17 用户已指定父仓库 https://github.com/chenhaox/WRSAgentOS.git 并要求版本管理和上传排除。助手指令、本地计划、reports、IDE 配置和真实凭据不进入提交。

复现：

    git clone --recurse-submodules https://github.com/chenhaox/WRSAgentOS.git
    git submodule update --init --recursive

不要在 bootstrap、CI 或每次启动里执行 `git submodule update --remote`。升级 WRS 应作为独立变更：取新提交、审计差异、运行 core 与 WRS 验收、更新锁定记录。[S04]

## 5. 常规依赖与多环境

项目要求 Python 3.12。本机开发验证使用 `D:\code\venv312\.venv\Scripts\python.exe`（3.12.0），这个绝对路径不是其他机器的运行要求。Windows 的 run.ps1/bootstrap.ps1 默认调用当前 `python`；如需明确选择，设置 `$env:WRS_AGENT_PYTHON = "本机 Python 3.12 的路径"`。

普通虚拟环境中的 Runtime 子进程继承 `sys.executable` 并正常加载该环境的 site-packages。使用 `python -X utf8 -S scripts/run.py ...` 时，子进程保留相同的开发隔离模式，通过 scripts/run.py 加载项目 .local/deps。WRS adapter 通过标准库 site 获取当前平台的科学包路径，仅追加路径，不执行 .pth。版本见 WRS_AUDIT.md 和 reports/doctor.json。

    ./scripts/bootstrap.ps1
    ./scripts/install_router.ps1
    ./scripts/run.ps1 scripts/doctor.py --probe-wrs

Router 查找顺序是 `WRS_AGENT_ZENOHD` 指定的文件、仓库 `.local/zenoh-1.9.0/zenohd.exe`（Windows）或 `zenohd`（POSIX）、系统 PATH 中的 zenohd。显式路径无效时直接报错，不回退到另一份程序；启动前始终核对版本 1.9.0。可执行文件路径含空格时也作为一个独立参数传递。

PowerShell 安装脚本只覆盖 Windows x64。Linux/macOS 需准备对应平台的依赖和 Router；启动器已使用 POSIX 文件锁，但这些平台尚未实际验收。当前仍以源码 checkout 运行，configs、scripts 与 .local/runs 位于仓库中，未验证独立 wheel 部署。

bootstrap 用项目本地 uv 0.12.15 从 uv.lock 导出带哈希 requirements，再同步至 .local/deps。router 固定官方 1.9.0 并校验 SHA256。脚本可重跑，不更新 WRS 远程指针、不修改共享环境。

当前已实现 core/dev/glm；httpx 同时列入 dev 以运行无网络的协议夹具。部署仅 core 不含 httpx。speech 在真实接入时加入 pyproject 并重新生成锁文件。没有空 extras、默认付费调用或权重下载。表中未接入项仍是后续合同。

## 6. 什么时候才增加第二个 submodule

至少满足以下实质条件之一，并写决策记录：需要长期修改第三方源码；需要独立维护与本项目协同的 fork；依赖无法通过正常包/服务使用，且确实属于运行时必要组件。

“论文里用了”“学生需要看源码”“仓库看起来重要”都不是理由。用于复现的 RPent/HoloAgent 应独立环境运行；核心项目只保存参考路径、commit 与借鉴点，避免整套依赖互相污染。

参考仓库中的 Skill 文档不能不经审查自动成为模型的高权限指令。少量源码复用记录来源与授权。机器人模型网格、数据和模型权重的授权可能不同于顶层代码许可证，应分别登记；本文件不是对未审计资产的商用授权承诺。

2026-09-17：GLM 使用 httpx 异步客户端直接发送 OpenAI 兼容 JSON；原计划 openai SDK 为候选，未引入。可运行 `./scripts/bootstrap.ps1 -Extra glm`；锁文件由 uv 0.12.15 重新生成，不修改共享 Python。只有非流式/auto 工具模式经离线协议测试，真实账号模型及 GLM TTS 未验证。

M3 科学包路径补充：指定 venv 的 pyvenv.cfg 设置 include-system-site-packages=true。WRS adapter 仅在自己的进程向 sys.path 后部追加该 venv 与基础解释器的 site-packages；项目锁定 core 包优先，固定 WRS submodule 位于前部并检查真实模块路径。不执行 .pth、不升级或修改共享包。M3 干净机器科学依赖重建仍未验证。

## Qwen 语音可选依赖

实际选用 Qwen3-ASR-0.6B、Qwen3-TTS-12Hz-0.6B-CustomVoice；qwen-asr 0.0.6 与 TTS 侧 faster-qwen3-tts 0.4.0 的 Transformers 精确依赖冲突（4.57.6 与 5.15.1），通过互斥 uv extras 与两个 .local/venvs 环境隔离。Torch/Torchaudio 2.9.0 CU128；核心默认依赖不增加模型 SDK。固定模型资源、校验与安装入口见 [Qwen 语音指南](QWEN_SPEECH.md)。普通 pip 也可分别安装两个 extra，但复现版本以 uv.lock 与 setup_speech.ps1 为准。


2026-09-23：TTS 后端由官方 qwen-tts 0.1.1 换为 faster-qwen3-tts 0.4.0（MIT，CUDA graph 加速），实测短句提速 4.8 倍、41 字长句 6.4 倍，详见 [Qwen 语音指南](QWEN_SPEECH.md)。它硬依赖 `qwen-tts-hf` 0.1.1.post1 顶替官方 `qwen-tts`（同名 `qwen_tts` 包不可共存）并要求 Transformers 5.x；Transformers 固定 5.15.1，因为 5.17.0 会在其 rope 兼容层对 Mimi codec 配置抛 AttributeError。变更限于 `.local/venvs/qwen-tts`，ASR 的 Transformers 4.57.6 与共享环境不受影响；uv.lock 由工具重新生成，`uv pip check` 93 包全部兼容。`qwen-tts-hf` 自述为非官方临时兼容构建，PyPI 仅一个版本、无授权声明、无仓库链接，作者字段沿用上游而非实际维护者；接受此来源风险是用户的明确决定，登记在此以备复核。

2026-09-22：用户明确要求将 ASR 装入已有 `D:\code\venv312\.venv`。使用 uv pip install 增量安装 qwen-asr 0.0.6、torchaudio 2.9.0+cu128、sounddevice 0.5.6，并约束保留已有可见依赖；未对该共享环境运行 sync。Transformers 4.57.6 要求 huggingface-hub<1，因此仅将已有 hub 1.3.2 调整为 0.36.2，其余原包保留。SDK/语音依赖仍在 pyproject 的 qwen-asr extra 中；默认 setup_speech.ps1 继续提供隔离安装，TTS 使用原独立环境。共享环境已有两项与此次无关的缺失：joycon-robotics 的 hid 与 scipy-stubs 的 optype；安装后未新增依赖检查错误。
