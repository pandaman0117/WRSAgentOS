# 本地中文语音：Qwen ASR + TTS

本机 RTX 5060 Laptop，显存 8151 MiB，选择 Qwen3-ASR-0.6B 与 Qwen3-TTS-12Hz-0.6B-CustomVoice。两者使用 CUDA / BF16，固定中文，TTS 使用内置 Vivian 音色。先验证小模型的识别与响应，再决定是否需要更大的模型。本机已完成下文模型检查；真实麦克风与播放延迟仍需现场测量。

## 安装和下载

从仓库根目录执行；核心依赖和 WRS 按原有 bootstrap 准备。

```powershell
$env:WRS_AGENT_PYTHON = "D:\code\venv312\.venv\Scripts\python.exe"
./scripts/setup_speech.ps1
.local/venvs/qwen-asr/Scripts/python.exe scripts/download_speech_models.py
```

安装脚本由现有 Python 3.12 创建两个项目内环境，不修改共享 venv。Qwen 官方 pip 包分别固定 Transformers 4.57.3 / 4.57.6，不能装在同一环境。`pyproject.toml` 中的 `qwen-tts` / `qwen-asr` extras 明确互斥；`uv.lock` 由工具生成。两个环境通过现有 Zenoh 连接，不增加远程推理服务。Linux 可使用 `UV_PROJECT_ENVIRONMENT=.local/venvs/qwen-asr uv sync --locked --no-default-groups --extra qwen-asr`，TTS 同理；本轮尚未在 Linux 验证。

选择 Torch/Torchaudio 2.9.0 + CUDA 12.8，以覆盖本机 Blackwell GPU；不默认安装 vLLM、FlashAttention 或强制对齐模型。官方 SDK 自身会带入 Gradio 等依赖，但核心 Runtime 不安装这些 extras，也不会启动其 Web UI。权重共约 **4.08 GiB**，TTS 已含 speech_tokenizer，不需要另下 1.7B、Base、VoiceDesign 或克隆音色资源。安装包与 CUDA 运行库还需要额外磁盘空间。

下载脚本显式访问官方 Hugging Face，固定提交、核对每个文件的 SHA256（LFS）或 Git blob SHA1。资源声明 Apache-2.0，详见固定模型卡。默认下载到项目根目录下 Git 忽略的 `.local/models/`，加载时也使用这个绝对位置，不受 IDE 工作目录影响。中断后可重跑；更改位置可设置 `WRS_AGENT_MODELS`，下载和运行时保持一致。显式配置的相对路径按当前工作目录解析，跨进程使用建议填写绝对路径。完成后生成本地校验凭据。启动只接受校验过、大小和修改时间未变的本地文件，并启用 Transformers/HF 离线模式；缺失文件直接报错。没有 API Key 要求，不上传录音。官方包可能打印缺少 SoX 或 FlashAttention 的提示；当前 CustomVoice 合成与数组 ASR 已在未安装这些二进制扩展时验证，不需要为本例额外安装。

## 运行 WRS 语音示例

先关闭你自己启动的 `05_start_node.py`，Voice/05 使用同一端口与 namespace，二者只运行一个。已有 07 viewer 可以观察同一实例；节点重启后重新连接 viewer。

```powershell
# 终端一：WRS + Runtime + Voice，Qwen TTS 用独立环境启动
./scripts/run.ps1 examples/voice/05_start_wrs_voice.py

# 终端二：WRS 原生网页场景；浏览器打开 http://127.0.0.1:8000
./scripts/run.ps1 examples/wrs/07_viewer.py

# 终端三：使用 ASR 环境，避免 scripts/run.py 注入另一套依赖
.local/venvs/qwen-asr/Scripts/python.exe -m examples.voice.06_push_to_talk
```

本机已按用户要求将 ASR 依赖安装到 `D:\code\venv312\.venv`，IDE 的 Voice/06、08 可以继续使用这个解释器。项目内 `.local/venvs/qwen-asr` 仍可选用；TTS 继续使用单独环境，因为两个 SDK 要求的 Transformers 版本不同。模型共用已下载文件，无需再下载。终端从仓库根目录运行公共解释器：

```powershell
& 'D:\code\venv312\.venv\Scripts\python.exe' -m examples.voice.06_push_to_talk
```

IDE 运行脚本时将项目根目录加入源码路径；终端优先使用上述 `-m` 形式，避免脚本所在子目录影响项目包导入。ASR 用普通 Python 启动，不使用会隔离 site-packages 的 `scripts/run.py -S` 路径。

等待 Voice/05 和 06 完成加载/预热。05 会播放启动提示，并检查播放结果。回车开始收音，说“向上”“向下”“向左”“向右”“向前”“向后”（2 cm）、“回到初始位置”“停止”“停止播报”或“状态”。停止之后的新方向指令只创建新任务，不恢复旧计划。运动期间不要连续排队目标；先停止、确认结束，再说新指令。`s` 直接发送停止，`q` 退出观察，不隐式取消远端任务。

建议耳机与近讲麦克风。本版是显式开始收音、短句结束后识别：20 ms 音频块，默认 250 ms 连续低能量结束；最多 3 秒，超过时整句丢弃。能量阈值需要按麦克风环境调节；它只用于分句，不能作为停止意图。06 为按键收音；另外提供循环收音和文字唤醒入口，见 [Voice 示例](../examples/voice/README.md)。没有回声消除或流式中间结果派发。Qwen ASR 官方 Transformers 接口执行整段推理，官方流式接口依赖 vLLM，此 Windows V1 暂不引入。

## 为什么这样接

```text
麦克风 -> ASR 0.6B（独立客户端进程）-> 完整中文文本
  停止 / 查询 -> system.send_text -> Voice 节点 -> Runtime 控制入口
  明确方向   -> 示例中的固定映射 -> system.start(motion, speak)
                                      |             |
                                  WRS 节点      Qwen TTS 节点
                                      |
                                  07 viewer 显示
```

ASR 同时接收这组明确的中文指令词汇提示，减少短词同音混淆；识别后仍严格匹配，不把“想上”模糊改成“向上”。方向映射留在例子里，可以直接阅读，不改 Planner、不调用云端模型、不把任意识别文字当作运动命令。UI 文字仍可走同一文本入口；通用自然语言规划沿用已有 goal 接口。本例不提供未经校准的 ASR 置信概率：Qwen 接口没有返回该分数；只对用户显式收音且完整匹配的文本调用可信输入入口，不能把这个选择当作 100% 识别准确率。

控制循环不运行同步模型推理或声卡调用。ASR 一次处理一句，没有录音待执行队列；识别期间若机器人实例或控制 epoch 改变，迟到的运动指令丢弃。TTS 模型只加载一次，固定反馈在就绪前预合成到有界内存缓存，播放时无需争抢 GPU 推理；运动和“正在上移”等反馈并行，不等待播报完成再运动。任意新文本仍需完整合成，首句可能明显较慢，不宣称流式 TTS。

Qwen TTS 0.1.1 包装层没有转发通用 `stopping_criteria`；适配用 talker 的 PyTorch forward 前置 hook 在生成边界检查停止。合成结束后先回到控制循环检查停止，再派发播放；即使线程停止转发尚未调度，已取消合成的迟到音频也会丢弃。播放器每 20 ms 音频块检查停止并 abort 自己的输出流；收到受理只是 STOPPING，后端返回确认后才结束。输出/关闭失败进入 UNKNOWN。成功仅表示本机音频输出已排空，不验证人是否听到。语音停止不是实机急停，本例只控制 WRS 仿真。

## 检查响应速度

Voice/06 分别打印识别推理耗时和指令处理耗时；总延迟还包括说话、250 ms 截句、驱动缓冲等。首次加载与预热不计为稳态响应；不能用批处理吞吐代替单条停止延迟。优先测短中文指令、背景噪声、TTS 同时播放，以及 GPU 被 WRS 界面占用时的情况。

无需麦克风/扬声器的模型检查：

```powershell
.local/venvs/qwen-tts/Scripts/python.exe scripts/check_speech_models.py tts
.local/venvs/qwen-asr/Scripts/python.exe scripts/check_speech_models.py asr
```

前一项只将合成音频写到 `.local/speech-check/`，不播放；后一项识别这些本地样本，不录音。报告包含加载时间、短句推理时间与当前进程显存；这仍不能代替真实麦克风、端到端停止和多进程同时运行的验收。

来源：[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)、[ASR 固定版本](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/tree/5eb144179a02acc5e5ba31e748d22b0cf3e303b0)、[TTS 固定版本](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/tree/85e237c12c027371202489a0ec509ded67b5e4b5)。


## 本机实际证据（2026-09-22）

模型、两个独立环境均已安装，全部固定文件哈希校验通过，uv pip check 无依赖冲突。Torch 2.9.0+cu128、Qwen ASR 0.0.6、TTS 0.1.1，BF16 / SDPA。以下只是少量本地合成样本的实测，不是实时性或真实麦克风准确率承诺：

- TTS 加载 8.35 秒；生成“向上。”4.64 秒（首句）、“停止。”2.55 秒。示例预合成 7 句，完整 WRS/Voice/TTS 服务约 44 秒就绪，此后缓存播报不再执行模型合成。
- ASR 预热后，WRS/TTS 常驻时识别两个样本分别 0.178 / 0.124 秒；ASR 单进程模型加载约 9 秒。
- 同时运行时，nvidia-smi 采样整张 GPU 占用峰值 5457 MiB，包括桌面等其他占用，不能当作本项目独占显存需求。
- 实际 Qwen 合成中请求停止，约 0.302 秒后返回未生成可播放结果；没有打开音频设备。
- 首次“向上”合成样本曾识别为“想上”，严格匹配拒绝它。加入指令词汇提示后复测，两个样本均精确匹配，推理分别 0.132 / 0.129 秒；这是模型识别结果，不是事后改字。两条样本不足以评估噪声、方言或整体准确率。

默认自动检查不使用声卡。真实播放完成/停止、麦克风分句阈值、回声、现场端到端延迟和持续运行仍待验证。证据保存在本机 Git 忽略的 reports/qwen_*.txt/json 与 .local/speech-check 中；安装和下载脚本供其他同学复现。


## 示例目录

[WRS](../examples/wrs/README.md) 仅包含机械臂和查看器；[Voice](../examples/voice/README.md) 包含文字输入、按键收音、循环收音与 GLM 目标；[TTS](../examples/tts/README.md) 提供独立启动播报、调用和取消。启动提示是常规 speak 动作，预合成用于模型预热，实际播放用于检查输出设备；播放失败不宣布就绪。
