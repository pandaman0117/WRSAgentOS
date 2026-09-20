# 节点与消息：V1 如何借鉴 DimOS

V1 保持现有 Node、Skill、Task，不再要求开发者学习另一套 Module/Stream/Topic 类体系。借鉴组件拥有自己的生命周期、消息合同与输入输出边界；目前没有必要搬入 DimOS 的自动连接、Blueprint、多传输及编码 mixin。

## 四个词对应什么

| DimOS 概念 | 本项目的理解 | V1 选择 |
|---|---|---|
| Module | 一个有明确职责、可运行的组件 | 继续叫 Node；WRS、TTS、Voice、Agent 已有独立进程。无需共同继承 Module |
| Stream | 组件持续输出的数据，如图像、识别片段、进度 | 是 Event/Stream 的通信场景。暂不增加可组合 Stream 类、操作符或响应式依赖 |
| Topic | 发布订阅使用的地址 | 使用 Zenoh key 字符串和既有前缀/后缀。规范命名即可，不需要 Topic 对象 |
| Message | 一次传输的数据 | 使用现有 Pydantic 消息合同。长期动作仍需要编号、受理、进度、终态和取消语义 |

这些词描述不同层面，并不是四个必须实例化的业务对象。给一条消息选地址、把消息持续发布出去，并不要求使用者先构造四层类。以上定义来自 DimOS 的 [传输说明](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/docs/usage/transports/index.md)。

## Node 的例子需要表达什么

最有价值的例子是说明“提供什么合同、收到请求后谁执行、如何停止、如何退出”：

- TTS 节点提供 speak@1，接受动作并报告进度与终态；取消受理后等待真实输出停止。
- WRS 节点通过 Environment 执行机器人动作，保留单一设备控制所有者与最终准入检查。
- Voice 已是独立节点，当前接收已识别文本并分类。ASR 后端接入示例见 [文本合同](VOICE_INPUT.md)；当前还没有真实识别引擎。
- Agent 也是独立节点，包含 Runtime 和 Planner。Planner 先作为可替换的内部接口；只有独立 GPU、故障隔离或部署需求出现时再拆进程。

可运行入口是 [自定义节点与 Skill](../examples/developer/05_custom_skill.py)。新增后端主要修改处理函数和节点创建信息；新增受支持角色的实例主要修改配置与启动入口，Runtime 不增加对应分支。V1 不自动加载网络发现的代码。

DimOS 的 [Module 文档](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/docs/usage/modules.md) 展示了输入、输出、RPC 和生命周期声明。借鉴这些边界即可；本项目目前不需要同样的继承与自动装配方式。

## zenohpubsub 值得借鉴什么

在 [zenohpubsub.py](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/dimos/protocol/pubsub/impl/zenohpubsub.py) 中，发布订阅收发与消息编码分开，发布器复用，订阅者有退出清理；按用途提供不同的可靠性与拥塞策略。这些是可借鉴的具体机制。

本项目已有 Transport 集中管理 Zenoh 收发、线程回调桥接、有界入口和生命周期清理，消息合同留在 schemas.py。暂不拆成 Base、编码 mixin、Topic 与多种实现的继承树，也不复制 LCM 类型路由或 Pickle 编码。

控制与观测需要不同策略：观测可以丢旧保新；控制必须有受理/完成区分、幂等编号与结果查询。可靠传输或阻塞发布不能证明机器人已经停止。当前控制请求走独立有界 Query 入口，保留超时与 UNKNOWN，不改成普通广播。

## 几种传输现在要不要加入

| 候选 | 有用的场景 | 当前决定与代价 |
|---|---|---|
| Zenoh | 当前跨进程、跨节点查询/事件/动作 | 保持唯一正式传输，便于联调和部署 |
| Memory | 单进程逻辑测试 | 沿用直接调用的测试夹具即可。不新增公开后端；它不能验证断网、序列化或进程退出 |
| Shared memory / IPC | 同机高帧率图像、点云或大音频块 | 暂缓。先测量复制/序列化成本，再明确缓冲区所有权、寿命、丢帧与跨机回退；当前小型 JSON 消息没有测得瓶颈 |
| DDS | 已有 ROS 2 / DDS 设备或系统互联 | 有明确互操作需求时先做边界桥接，暂不加入第二套默认传输；需额外处理类型、发现、QoS 与测试矩阵 |

DimOS 在该固定提交的 [传输对照表](https://github.com/dimensionalOS/dimos/blob/29dfda595892dffb91c79f379eb44d1c737f9caf/docs/usage/transports/index.md#available-transports) 将 Memory 标为单进程测试用途，SharedMemory 用于同机多进程，DDS 标为 WIP；这不能作为本项目的性能证据。

实现多种传输会增加依赖、部署项和故障组合；是否更快取决于实际数据量与使用方式。本轮没有负载或延迟基准，不宣称 Zenoh 或某一种替代方案更快。

## 只预留真正需要的边界

保持技能函数不依赖 Zenoh，保持 Planner 不依赖 WRS，继续通过 Transport 收发、通过消息合同表达数据。未来相机接入时，可先增加一项明确的数据合同和一个有界订阅例子；出现跨进程大数据需求后再评估缓冲区描述符与共享内存。

目前只在设计上保留这些边界，不添加未实现的 Transport Protocol、Stream 基类、Node 插件占位或新的配置选项。这能让接手者先把 WRS、TTS、ASR、UI 接通，后续再针对实际瓶颈扩展。
