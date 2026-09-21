"""读取 WRS 节点的关节状态，在 WRS 场景中显示；与控制脚本分开运行。"""

from pathlib import Path

from examples._session import use_local_token
from wrs_agent import connect
from wrs_agent.env.viewer import viewer_hub
from wrs_agent.env.wrs import load_wrs, sync_scene_objects

CONFIG = Path(__file__).with_name("wrs_bindings.toml")
VIEWER_PORT = 8001

if __name__ == "__main__":
    use_local_token("voice")
    wrs = load_wrs()
    world = wrs.wvw.World(
        cam_pos=(0.9, 0.9, 0.7),
        cam_lookat_pos=(0, 0, 0.25),
        port=VIEWER_PORT,
        hz=10,
        auto_start_hub=False,
    )
    world.set_caption("WRS Lite6 — 语音目标执行")
    robot = wrs.xarm_lite6.Lite6()
    robot.add_to_scene(world.scene)
    wrs.wssop.frame().add_to_scene(world.scene)

    with connect("tcp/127.0.0.1:7451", env_id="voice-goal", bindings=CONFIG) as system:
        initial = system.snapshot(node="wrs")
        if initial.data.robot.kinematics is None or not initial.data.robot.kinematics.valid:
            raise RuntimeError("WRS 节点没有有效的关节状态。")
        robot.fk(initial.data.robot.kinematics.qs)
        displayed = {}
        sync_scene_objects(wrs, world.scene, initial.data.objects, displayed)

        def update(dt):
            snapshot = system.snapshot(node="wrs")
            if snapshot.boot_id != initial.boot_id:
                raise RuntimeError("WRS 节点已重启，请重新连接 viewer。")
            state = snapshot.data.robot.kinematics
            if state is None or not state.valid:
                raise RuntimeError("WRS 关节状态无法确认，停止显示。")
            # 运动命令来自 Voice / GLM / Runtime；本回调仅用关节状态刷新显示。
            robot.fk(state.qs)
            sync_scene_objects(wrs, world.scene, snapshot.data.objects, displayed)

        world.schedule_interval(update, 0.1)
        try:
            # 这个帮助函数只管理页面服务，场景和刷新逻辑都在本文件。
            with viewer_hub(VIEWER_PORT):
                print(f"打开 http://127.0.0.1:{VIEWER_PORT}，Ctrl+C 退出观察。", flush=True)
                world.run()
        finally:
            world.close()  # 关闭显示不会取消远端任务。
