# TTS：一个独立的播报节点

先完成 [Qwen 安装和模型下载](../../docs/QWEN_SPEECH.md)，再从仓库根目录运行。这里会真实播放声音，不需要 WRS、Voice 或云端模型。

| 文件 | 内容 |
|---|---|
| [01_start_node.py](01_start_node.py) | 加载 Qwen、合成预热、播放“语音播报节点已启动”，确认成功后等待 |
| [02_speak.py](02_speak.py) | 连接已有节点，说一句话，查询结果与完成次数 |
| [03_cancel.py](03_cancel.py) | 取消合成或播放，分别查看受理和终态 |

```powershell
# 终端一：服务一直运行
./scripts/run.ps1 examples/tts/01_start_node.py
# 终端二：依次体验，不要同时提交
./scripts/run.ps1 examples/tts/02_speak.py
./scripts/run.ps1 examples/tts/03_cancel.py
```

地址为 `tcp/127.0.0.1:7450`，环境 `tts-demo`；示例自动共享本机口令。TTS 子进程使用 `.local/venvs/qwen-tts`。启动提示是普通 `system.action("speak", text=...)`，有 action_id、结果与取消语义，没有绕过节点的特殊播放通道。

预热来自首次模型合成，实际播放还检查声卡输出链路；二者不是一回事。加载与预合成阶段还没有声音，不代表启动失败。播报失败/UNKNOWN 不打印“就绪”；不会自动重播未确认动作。客户端断开不停止服务或取消已提交播报。03 可能在合成阶段就取消，不能据此断言声卡停止已经验证。

历史日志只保留明确终态时可继续接单；存在 UNKNOWN 时先查明设备状态。不要在运行中删日志、或用重试盲目重播。核心库不会因 import 或普通 launch 自动发声，是这些脚本明确提交了启动提示。
