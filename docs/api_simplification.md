# 当前 API 与简化原则

普通脚本从 `launch()` / `connect()` 开始；已有事件循环用 `System.launch()` / `System.connect()`。同步入口复用现有异步客户端，不另建调度器。示例按难度排列在 [examples](../examples/README.md)。

## 使用者需要的接口

| 操作 | 接口与返回 |
|---|---|
| 一次动作 | `system.action(skill, **args)` → ActionHandle |
| 一项确定计划 | `system.start(*steps)` → TaskHandle |
| 请求模型规划 | `system.goal(text)` → GoalHandle |
| 输入已识别文本 | `system.send_text(text)` → TextReceipt |
| 重连查询 | `system.task(task_id)` / `system.planning(request_id)` |
| 观察指定任务 | `task.status()` / `task.watch()` / `task.wait()` → TaskStatus |
| 取消指定任务 | `task.cancel()` → TaskCancelReceipt；再 wait 确认结束 |
| Runtime 总览 | `system.status()` → 字典 |
| 节点与技能 | `system.nodes()` → 目录字典；`system.skills()` → 技能描述 |
| 只读节点状态 | `system.snapshot(node="wrs")` → NodeSnapshot |
| 设备级准入 | `system.allow_actions(node="wrs")` → ControlReceipt |

任务取消独立收尾：RUNNING → CANCELLING → CANCELLED 或 UNKNOWN。正常结束后按实际状态提交新任务。任务不提供 hold、replace 或续跑；删除 supersedes 和等待替换的状态。`start()` 不隐式抢占已有任务。`wait/watch` 超时、关闭迭代器和退出连接不会隐式取消执行；退出拥有本地进程的 launch 会清理服务。

设备 hold 仍然保留，它表示停止并关闭节点准入。allow_actions 只在停止已确认、状态有效时允许新动作；名称不再暗示续跑旧计划。普通任务取消会仅开放本次任务自身造成的停止锁止，另一次设备停止或未知状态仍需核实。

## 保留的必要边界

- Skill 是参数、资源、版本和验证的唯一合同；Node 声明实现了哪些技能版本；bindings 指定允许的执行者。
- Node 不要求统一继承。WRS/TTS 共用 ActionClient 与节点动作协议；WRS 独有的物理能力留在 Environment。
- Planner 只提出计划；Runtime 完成预检、实例绑定、资源调度和结果保存；节点执行准入是最后检查，不能只依赖 Runtime 锁。
- 消息边界用 Pydantic；内部优先普通函数和显式数据。`__init__.py` 不是把所有实现塞在一起的目标。
- Transport 负责 Zenoh 信封与收发。查询、事件和长期动作各有语义，不把动作成功等同于消息送达。

`context()` 暂不改造：它同时返回当前状态和节点签发的短期执行凭证。`system.action()` 自动获取它，ActionClient 内部一次性构造 ActionRequest；不再要求使用者调用组装函数。完整调用链和 control_epoch / state_version 的区别见 [任务句柄](task_handles.md)。

## 本次删除与暂缓

协议已升级到 v4：移除任务 hold/replace 端点及旧合同；设备 resume 更名 allow_actions，不保留旧别名。客户端与节点一起升级。详见 [错误与协议迁移](errors_and_versions.md)。早期实现与验收历史保留在 Git 和 [验收记录](ACCEPTANCE.md)，不再作为可运行用法展示。

保留 `start()`，不同时引入多个任务启动别名；现有 `bindings=` 配置入口暂不改名。结果有稳定类型，但不为了字段一致强行给目录和 Runtime 总览套一层类。

暂缓：自动接纳未配置节点/技能、通用插件加载、多实例负载均衡、设备所有权服务、订阅式 Task watch、独立 Planner 进程、多传输框架。DimOS 的概念映射和考虑接口的条件见 [节点与消息](NODES_AND_MESSAGES.md)。
