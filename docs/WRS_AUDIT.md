# WRS 与环境审计（2026-09-17）

> 下文保留历史验收命令；2026-09-20 起当前 WRS 示例分别为 [虚拟运动](../examples/wrs/01_move.py)、[取消](../examples/wrs/02_cancel.py)、[取消后新动作](../examples/wrs/03_new_action_after_cancel.py)，均不附加命令行参数。最新结果见 [验收记录](ACCEPTANCE.md)。

解释器：`D:\code\venv312\.venv\Scripts\python.exe`，Python 3.12.0，Windows 11。core 经 scripts/run.ps1 使用项目独立依赖；WRS 探测子进程使用同一解释器及用户已有科学依赖，未安装/升级共享环境。

唯一远程：`https://github.com/chenhaox/WRS2.git`。固定 commit：
`2bb014b747833c2fd9345115fbe26ffb11376f20`。真实 gitlink 模式 160000，见 reports/doctor.json。submodule 无本任务修改。

初次审计本地 `D:\code\ch\WRS2` 的 origin 相同，HEAD 为 `5cbe75e829d8aa28701a0ad25be036e80c25320a`，有多项未提交修改。本任务仅读取该目录。向公开远程 fetch 此 SHA 返回 `not our ref`，故没有搬运不可还原提交或未提交文件；采用公开远程可取得的固定提交。父仓库原先未初始化 Git，现已初始化，未自动提交或发布。

| 项目 | 固定提交中的实际证据 | 本轮结果 |
|---|---|---|
| 包装 | pyproject.toml，setuptools，Python >=3.12 | 已审阅；未执行全量 editable 安装 |
| 最小导入 | wrs/__init__.py；本项目 env/wrs.py 中的 probe | PASS，未打开 viewer |
| 机器人类 | wrs/robots/manipulators/ 下 Lite6、UR3、FR3、RS007L、CVR038、CRX5IA、OpenArm | 源码枚举，不表示设备经过测试 |
| FK/状态 | robots/base/mech_base.py:101 的 fk(qs)、qs 和 link transforms | Lite6 构造/FK PASS，shape=[7,4,4]，6 个关节；虚拟状态 |
| IK | robots/base/mech_base.py:307 的 ik(...) | 已定位，数值求解 UNVERIFIED |
| 运动规划 | motion/probabilistic/rrt.py 的 RRTConnectPlanner.solve/solve_iter | 已定位，路径和碰撞验证 UNVERIFIED |
| 设备运动/读回 | 锁定版本模型与规划源码 | 未发现并验证可用实机入口；型号/地址未知 |
| stop/flush/夹持 | viewer/world.py:88 的 stop(function) 仅取消调度回调 | 不可当设备停车；控制器停止/清队列/物理确认 UNVERIFIED |
| 查看器线程 | viewer/world.py:125 的 run()，调用线程 tick、后台 publisher 采样 scene | WGPU/web viewer；未运行 viewer，不沿用 Panda3D 假设 |
| 授权来源 | 根 LICENSE，MIT，WRS Research Group 2026 | 代码许可证已读；网格/独立资产仍需逐项核查 |

实际探测：`./scripts/run.ps1 scripts/doctor.py --probe-wrs --output reports/doctor.json`。

已有 WRS 依赖：NumPy 1.26.4、SciPy 1.16.2、MuJoCo 3.5.0、WGPU 0.32.0、websockets 15.0.1。这些是已观察版本，不代表 WRS 全部传递依赖已锁定。干净机器的科学依赖恢复留待 M3。

core 的工具生成 uv.lock 锁定 Zenoh 1.9.0、Pydantic 2.13.5、pytest 9.1.1、pytest-asyncio 1.4.0、Ruff 0.16.8。uv 工具为 0.12.15。官方 zenohd 1.9.0 MSVC ZIP 的 SHA256：
`07af486bedd6e2138e187f277d4d8a74632ec1e7659f10dc76aa18a36b5d2a75`，
下载与校验脚本为 scripts/install_router.ps1。

本轮只证明 WRS 源码、导入与 FK 可用。M3 连续虚拟运动尚未实现；GLM、真实音频和实机全部 UNVERIFIED。CLI 只能选择 Mock 节点。

## 2026-09-17：router 版本检查误报

使用指定 Python 3.12.0 复核：本地 router 输出 `zenohd v1.9.0 built with rustc 1.93.0 (254b59607 2026-01-19)`；现有 ZIP 的 SHA256 与上述固定值一致。设置 `RUST_LOG=info` 或 `debug` 后，`--version` 会先向 stdout 写入带时间戳的 INFO 日志，然后才输出独立版本行。`LocalStack.start_router` 对整个输出执行 `startswith(b"zenohd v1.9.0 ")`，因此错误拒绝正确的二进制。

复现命令：`$env:RUST_LOG = 'info'; & 'D:\code\venv312\.venv\Scripts\python.exe' -X utf8 -S scripts/run.py examples/developer/02_mock_interrupt.py`，修复前退出码 1，证据 `reports/router_version_before.txt`。决策：从独立版本行提取完整版本号并严格比较 1.9.0，保留继承的日志设置；真实不匹配时报告期望版本、二进制路径和实际输出，不放宽到任意版本。

另观察到直接使用共享 site-packages 时 `eclipse-zenoh` 为 1.10.1；项目启动器加载 `.local/deps` 的锁定 1.9.0。两者与 router 版本检查误报分开处理，不修改共享环境。后续验证通过项目启动器执行；真实硬件、模型 API 和音频不在本修复范围内。

修复验证：指定解释器下新增 13 项版本检查单元测试及 2 项真实 router 集成测试通过。设置 RUST_LOG=info 执行当前完整单元集 92 passed、Zenoh 集成集 8 passed，0 failed / 0 errors / 0 skipped；两个示例、全仓库 Ruff、doctor 均 PASS，无阻塞检查。Mock 中断示例最终 SUCCEEDED，A 位于 C，旧动作拒绝 stale_epoch，迟到模型结果 STALE。实际命令、输出和依赖版本见 reports/router_version_fix.json、reports/router_fix_*.txt 和 reports/router_fix_doctor.json。共享环境未修改；WRS 连续虚拟动作、真实模型、音频和实机仍 UNVERIFIED。

## M3：已验证的 Lite6 虚拟节点

env/wrs.py 在独立 Environment 进程使用真实 Lite6、wmij.interp_by_n 和 robot.fk，单所有者线程操作模型，Zenoh/控制循环读取带时间、单位、frame/source 的镜像状态。验证关节到位与 FK 变换一致，默认 headless，不构造硬件或查看器。

capabilities / snapshot / observe / move_named_pose / status / cancel / hold / resume admission 已经真实跨进程验证。每次 FK 不可抢占：控制先撤权，等待在途 FK 返回后才确认停止；不对线程 future 执行 cancel 来冒充设备停车。没有控制器轨迹队列，controller_flush=false，stop_scope=virtual_fk_boundary。

固定源码有 robots/end_effectors/ee_mixins.py 的模型 hold/release、manipulation/arm.py 的抓取辅助接口；本 Lite6 profile 未装配夹爪、有效目标几何与碰撞校验，因此 pick/place/物体 verify 明确 unsupported。未把模型挂接当接触成功。RRT/IK 与 GUI 未接入动作路径，实机始终拒绝。

指定 venv 的科学依赖继承基础解释器 site-packages；core 不加载，WRS adapter 只读追加。完整科学依赖的干净安装仍未宣称可复现。测试/示例证据见 reports/m3.xml 和 reports/m3_example_cancel.txt。

## 2026-09-18：示例配置路径

从 examples/developer 使用指定解释器和绝对路径 scripts/run.py 启动 01_zenoh_roundtrip.py，复现 configs/robot.toml 被解析到示例子目录，退出码 1；证据 reports/example_paths_before.txt。仓库根目录 configs/robot.toml 实际存在，04_connect.py 的 configs/tts.toml 也受同样的工作目录依赖影响。修复限定在这两个示例，以脚本位置确定配置绝对路径；API 显式相对路径继续相对于调用者工作目录。验证：39 项现有回归、6 次跨工作目录示例和 Ruff 通过；IDE 导入路径下直接启动也通过。证据 reports/example_paths_summary.json、example_paths.xml、example_paths_ide.txt；命令与限制见 ACCEPTANCE.md 文末。


## 2026-09-21：方向移动与独立显示

在原有 WRS 节点上添加 `move_relative(dx, dy, dz)`，世界坐标系、米、非零总位移 ≤ 5 cm。模型工作线程调用实际 Lite6 IK，以当前关节选取近邻解，检查关节限位及单关节变化 ≤ 1 rad，然后关节插值；末端目标朝向保持，完成后通过实际 FK 核对。不是笛卡尔直线规划，也不做碰撞/接触验证。不可达在修改模型前以 `relative_target_unreachable` 结束；求解期间停止会撤销授权，迟到 IK 不再驱动模型。

显示模块从执行节点读取 boot_id 和真实关节快照，在另一份只读 WRS 显示模型中呈现。WRS 原生页面服务仅在回环监听，由 viewer 拥有和关闭；退出观察不取消远端动作，节点重启则要求重新连接。新入口见 [WRS 示例](../examples/README.md#wrs-虚拟机器人)。仍使用固定 submodule，无硬件连接。


## 2026-09-21：后端名称澄清

旧名 wrs_virtual 指的是实际调用 WRS Lite6 IK/FK 的仿真节点，不是 Mock。现统一为 `backend="wrs"`，CLI、启动器、节点能力声明和全部当前示例同步修改；旧选择值明确拒绝，不保留两种名字。能力中的 hardware=false、wrs_fk 和 virtual_fk_boundary 继续明确仿真边界，未新增实机控制能力。历史记录中的旧命令只供审计。

07_viewer.py 直接展示 World/Lite6/坐标轴创建、读取节点快照、robot.fk、定时刷新和退出。show_wrs/create_viewer 包装删除，viewer_hub 只负责页面服务生命周期；可从示例本身读懂完整的显示流程。


## 2026-09-22：具名 TCP 与状态命名

核对 WRS 2bb014b747833c2fd9345115fbe26ffb11376f20：MechBase 使用 qs，TCP 提供 name/pos/rotmat/tf；Lite6 注册 flange TCP。运动学消息由 joints/tip_position 迁移为 qs/tcp_name/tcp_pos/tcp_rotmat。适配器读取具名 TCP，IK 显式传同一 TCP，到位验证也使用其 tf；不再用最后连杆的位置冒充工具点。现有 frame_id=world、米/弧度及启动/控制合同保留。

此为运动学数据的破坏性字段迁移，配套服务/客户端/viewer 同步更新并重启；旧字段拒绝，不提供别名。RobotData.pose 仍仅表示 home/B/C 命名姿态，不等于几何位姿。完整场景字段取舍、并行相机和常驻 skill 设计见 [状态与感知](SCENE_AND_PERCEPTION.md)。SceneData/视觉/真实抓取属于后续方案，本轮未实现。

## 2026-09-22：SceneData 实现审计

已实现静态场景纵向切片，接续上节后续方案。固定 WRS 的 wss.Scene.add/remove 管理对象，wssop.box 接受 pos/rotmat/xyz_lengths/rgb/name，SceneObject.pos/rotmat 为世界位姿。适配器工作线程创建真实 Scene、Lite6 和方块；源数据经严格 TOML 校验后，快照中的已实例化物体位姿由 WRS 对象读回。无 geometry/rotmat 或 valid=False 时保留未知数据但不虚构显示实体。

NodeSnapshot.data 现为 SceneData（或 SpeechData），RobotData 位于 data.robot。独立 viewer 只操作自己的 SceneObject，支持跟随快照创建、修改、移除显示对象；当前服务端物体来自启动配置，无在线更新入口。未调用 collider、GraspNet 或真实硬件，碰撞检查仍 False。配置无需依赖 WRS SDK 即可校验，未新增外部依赖。完整合同与示例见 SCENE_AND_PERCEPTION.md。

## 2026-09-24：UR7E 替换 Lite6

旧版 WRS（D:\code\wrs，robot_sim 架构）的 UR7E 机械臂与 DH50 夹爪移植到 third_party/wrs 新架构：`wrs/robots/manipulators/universal_robots/ur7e`（与 ur3 并列，MechStruct + P234X56 解析 IK）和 `wrs/robots/end_effectors/dh/dh50`（GripperMixin，grasp_center 在 z=0.139）。关节原点、轴和零位沿用旧版，旧版关节值可直接复用；旧 flange 偏移位于第 6 轴上，并入最后一个关节，因此 wrist3 连杆坐标系即 flange。旧版 DAE 带交错索引与节点缩放，新版 DAE 读取器不支持，已用 trimesh 烘焙变换转为 STL，超过 1 万面的网格用 open3d 二次误差简化，最大表面偏差 0.22 mm。旧组合机器人（0.3×0.3×0.5 m 底座 + 臂 + Rz(π/2) 安装的 DH50）改为新版的 mount 组合，按 `fr3_with_hand` 惯例由 `ur7e.py` 的 `ur7e_with_gripper()` 提供（底座不属于机器人，不再内置）。wrs 顶层新增 `ur_ur7e`、`dh_dh50` 别名，Lite6 源码与别名保留。

对照：51 组关节角下各连杆与 flange 位姿和旧版差异 ≤ 2.7e-7；随机 200 组目标解析 IK 全部有解，往返误差 ≤ 7.3e-6；DH50 手指与抓取中心位置与旧版一致。适配器改用 `wrs.ur_ur7e.UR7E()`；home 为 UR 常用姿态 [0, -π/2, π/2, -π/2, -π/2, 0]（工具朝下），B/C 重新选在其附近，三处命名姿态的 ±2/±5 cm 方向移动均通过 IK 与到位验证。节点仍为裸臂 flange TCP，未挂夹爪；pick/place、碰撞规划和实机仍 unsupported。运动学采用旧版取整参数（如 d1=0.163），与 UR 官方标定值有毫米级差别，未做实机标定核对。
