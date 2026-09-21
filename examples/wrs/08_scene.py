"""独立运行：加载场景，读取同一份快照中的机器人、物体和坐标系。"""

from pathlib import Path

from wrs_agent import launch

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    with launch(
        backend="wrs", bindings=HERE / "bindings.toml", scene=HERE / "scene.toml"
    ) as system:
        snapshot = system.snapshot()
        scene = snapshot.data
        print("场景坐标系：", scene.frame_id)
        print("关节角：", scene.robot.kinematics.qs)
        for object_id, obj in scene.objects.items():
            print("物体：", object_id, obj.label, "位置：", obj.pos)
        print("碰撞规划已验证：", scene.facts["collision_checked"])
