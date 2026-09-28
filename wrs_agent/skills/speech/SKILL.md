---
name: speech
description: Plan a spoken status message with the available speak skill while independent robot work continues.
---

# 播报技能

用 `speak` 播报简短信息，文本放在 `text` 参数中。
播报务必简洁，优先控制在 20 字以内：只说结论，不复述参数细节、坐标或数值列表。
这不是风格偏好。Qwen TTS 逐个音频 token 生成，合成耗时与文本长度成正比，
每个汉字约 0.67 秒，40 字就要接近半分钟，期间到来的新指令会取消这次播报。
如果内容不依赖机器人动作结果，播报步骤不必等待机器人完成。
只有已确认的结果才适合表述为“完成”，否则说明正在进行或需要澄清。

播报由独立 TTS 节点执行。取消播报只针对这次播报动作。
Mock TTS 只验证模拟状态，不产生真实音频。可选 Qwen TTS 在本地合成并播放；
成功表示输出流已经排空，不表示听者确认听到。具体后端与停止范围查询节点 features。
参数和验证约束以一起提供的 SkillSpec 为准。
