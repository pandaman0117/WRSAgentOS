# Voice：从文字入口到常驻中文语音

Voice 已是独立 Zenoh 节点，处理已识别的文字、停止意图和控制路由。麦克风/ASR 使用独立输入进程；它离线或重启时，UI 文字入口、Agent 和其他动作节点仍可运行。现阶段不再增加一个必须注册的 ASR 节点类型。

## 先理解入口：不用麦克风

| 文件 | 内容 |
|---|---|
| [01_text_stop_task.py](01_text_stop_task.py) | 文字“停止”取消正在执行的 WRS 任务 |
| [02_text_stop_speech.py](02_text_stop_speech.py) | 文字“别说了”只停止模拟 TTS，WRS 继续 |
| [03_text_query.py](03_text_query.py) | 文字查询任务进度 |
| [04_text_goal.py](04_text_goal.py) | 确定性规划模板展示 goal 句柄，不访问在线模型 |

这些是控制语义例子，不录音；02 的模拟 TTS 不出声。真实播放看 [TTS 例子](../tts/README.md)。

## 本地短指令：不需要云端

[05_start_wrs_voice.py](05_start_wrs_voice.py) 启动 WRS、Qwen TTS、Agent、Voice，播报启动提示；[06_push_to_talk.py](06_push_to_talk.py) 按回车收音，将“向上/下/左/右/前/后”等完整短词映射成确定步骤，运动与预合成播报并行。

```powershell
# 终端一；与 wrs/05 二选一
./scripts/run.ps1 examples/voice/05_start_wrs_voice.py
# 终端二：浏览器 http://127.0.0.1:8000
./scripts/run.ps1 examples/wrs/07_viewer.py
# 终端三：使用 ASR 环境；-m 仅用于 Python 定位模块，不是例子的模式参数
.local/venvs/qwen-asr/Scripts/python.exe -m examples.voice.06_push_to_talk
```

本机 `D:\code\venv312\.venv` 已安装 ASR，IDE 直接运行 06 或 08 时可继续使用它；原 `.local/venvs/qwen-asr` 也可用。终端从仓库根目录用该解释器加 `-m examples.voice.06_push_to_talk`（或 08 模块）启动。默认模型路径固定为项目根目录下 `.local/models`，不需要因工作目录不同重新下载。

地址 `7449 / wrs-demo`。完整词表在 [commands.py](commands.py)；未知词不交给 Mock Planner。“停止”直接控制任务；`s` 也可发送停止，`q` 退出观察。节点重启/中断时，旧录音识别出的运动指令会被拒绝。

## 循环收音：自然语言目标交给 GLM

[07_start_glm_voice.py](07_start_glm_voice.py) 使用真正的在线 GLM Planner，不做离线回退。启动它前配置 `GLM_API_KEY`、`GLM_MODEL`、`GLM_BASE_URL`，安装 `glm` 依赖；凭据不写代码，`.env` 不自动加载。执行语音目标可能产生模型费用。

```powershell
# 终端一：不要同时保留另一套 Qwen 语音服务，避免额外占用显存
./scripts/run.ps1 examples/voice/07_start_glm_voice.py
# 终端二：浏览器 http://127.0.0.1:8001
./scripts/run.ps1 examples/voice/09_viewer.py
# 终端三：启动即循环收音，不再按回车
.local/venvs/qwen-asr/Scripts/python.exe -m examples.voice.08_listen_goals
```

这组使用独立地址 `7451 / voice-goal` 和口令分组，避免误连到确定性规划例子。

说“机器人，移动到 B”或“机器人，向上移动两厘米”。普通目标必须以“机器人”开头；“停止”“停止播报”“状态”无需唤醒，直接走已有 Voice 控制/查询入口。说“机器人，移动后播报”时，是否加入 speak 由 Planner 提议，再由 Runtime 校验。澄清、拒绝、任务结果显示在终端。

收音循环只等待目标受理；规划与任务结果由另一个有界观察协程显示，所以云端模型慢时仍能收音并发送停止。同时只处理一项规划/任务，新的目标不积压；要改目标，先停止，确认结束后说新目标。收音过程中实例或控制 epoch 改变，会丢弃这次迟到的运动目标。

这是“语音下达任务”，没有新增多轮聊天历史或通用聊天机器人；这些以后应放在 Agent 的对话层，Voice 保持输入和控制职责。

## 当前收音边界

Qwen ASR 0.6B 常驻，中文，句尾默认 250 ms 低能量截句。循环收音每句最多 4 秒；超时或过长整句丢弃。语音超出范围时缩短指令，不能把截断文本当作完整授权。识别/换句期间有短暂间隙，当前不是无缝流式或全双工通话。

“机器人”是识别后的文字前缀，不是新的声学唤醒模型；建议使用耳机防止扬声器回声。未实现回声消除、声纹鉴权和远场抗噪；低能量分句不等于停止意图。录音只在内存，不默认保存或上传；唤醒后的目标文本会发给 GLM。Ctrl+C 结束收音/观察，不隐式取消远端执行；先说“停止”并确认，再关闭输入进程。

安装、依赖隔离、模型大小和已有实测见 [Qwen 语音指南](../../docs/QWEN_SPEECH.md)。
