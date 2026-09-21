"""Actual WRS Lite6 IK/FK, owned by one worker. No hardware connection."""

import asyncio
import site
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path

from wrs_agent.actions import ActionExecutor, ExecutionUnknown, SkillFailure
from wrs_agent.scene import load_scene
from wrs_agent.schemas import ObjectData, RobotData, SceneData
from wrs_agent.skills import SKILLS

ROOT = Path(__file__).resolve().parents[2]
POSES = {
    "home": [0.0] * 6,
    "B": [0.3, 0.2, 0.5, 0.0, 0.2, 0.0],
    "C": [-0.3, 0.1, 0.4, 0.0, 0.1, 0.0],
}


def load_wrs():
    # Append platform-specific scientific package paths without executing .pth files.
    prefixes = [str(Path(sys.executable).parents[1]), sys.base_prefix]
    for package_path in site.getsitepackages(prefixes):
        if package_path not in sys.path:
            sys.path.append(package_path)
    source = ROOT / "third_party/wrs"
    sys.path.insert(0, str(source))
    import wrs

    if not Path(wrs.__file__).resolve().is_relative_to(source.resolve()):
        raise RuntimeError("unexpected_wrs_source")
    return wrs


def make_scene_object(wrs, object_id, data):
    """Construct only known, valid geometry; never invent an unknown pose."""
    if not data.valid or data.pos is None or data.rotmat is None or data.geometry is None:
        return None
    return wrs.wssop.box(
        pos=data.pos, rotmat=data.rotmat, xyz_lengths=data.geometry.xyz_lengths,
        rgb=data.rgb, name=object_id,
    )


def sync_scene_objects(wrs, scene, objects, displayed):
    """Apply serialized objects to a local WRS scene; no remote motion."""
    for name in set(displayed) - set(objects):
        displayed.pop(name)[1].remove_from_scene(scene)
    for name, data in objects.items():
        previous = displayed.get(name)
        if previous is not None and previous[0] == data:
            continue
        if previous is not None:
            previous[1].remove_from_scene(scene)
            del displayed[name]
        obj = make_scene_object(wrs, name, data)
        if obj is not None:
            obj.add_to_scene(scene)
            displayed[name] = (data.model_copy(deep=True), obj)


class VirtualModel:
    """All methods, including construction, run on one owner thread."""

    def __init__(self):
        self.wrs = load_wrs()
        self.robot = self.wrs.xarm_lite6.Lite6()
        self.tcp = self.robot.tcp("flange")
        self.scene = self.wrs.wss.Scene()
        self.robot.add_to_scene(self.scene)
        self.objects = {}
        self.path = None
        self.goal = None
        self.goal_tcp_tf = None

    def load_scene(self, objects):
        sync_scene_objects(self.wrs, self.scene, objects, self.objects)
        # Static configuration is read back from the actual WRS SceneObjects.
        result = {}
        for name, data in objects.items():
            values = data.model_dump()
            if name in self.objects:
                obj = self.objects[name][1]
                values.update(pos=obj.pos.tolist(), rotmat=obj.rotmat.tolist())
            result[name] = ObjectData.model_validate(values)
        return result

    def read(self):
        tcp_tf = self.tcp.tf
        return {
            "qs": self.robot.qs.tolist(),
            "tcp_name": self.tcp.name,
            "tcp_pos": tcp_tf[:3, 3].tolist(),
            "tcp_rotmat": tcp_tf[:3, :3].tolist(),
            "observed_at_ns": time.time_ns(),
            "valid": bool(
                self.wrs.np.isfinite(self.robot.gl_lnk_tfarr).all()
                and self.wrs.np.isfinite(tcp_tf).all()
            ),
        }

    def begin(self, pose, count):
        self.goal_tcp_tf = None
        self.goal = self.wrs.np.asarray(POSES[pose], dtype=self.wrs.np.float32)
        self.path = self.wrs.wmij.interp_by_n(self.robot.qs.copy(), self.goal, count)

    def begin_relative(self, displacement, count):
        np = self.wrs.np
        current = self.robot.qs.copy()
        target = self.tcp.tf.copy()
        target[:3, 3] += np.asarray(displacement)
        solutions = self.robot.ik(target[:3, 3], target[:3, :3], tcp=self.tcp, ref_qs=current)
        lower, upper = self.robot.chain_joint_limits("main")
        # Reject distant IK branches before changing the model or its published state.
        candidates = [
            q
            for q in solutions
            if np.isfinite(q).all()
            and (q >= lower).all()
            and (q <= upper).all()
            and np.max(np.abs(q - current)) <= 1.0
        ]
        if not candidates:
            raise SkillFailure("relative_target_unreachable")
        goal = min(candidates, key=lambda q: np.linalg.norm(q - current))
        self.path = self.wrs.wmij.interp_by_n(current, goal, count)
        self.goal, self.goal_tcp_tf = goal, target

    def step(self, index):
        self.robot.fk(self.path[index])
        return self.read()

    def verify(self):
        # Read the model, not a timer or a commanded pose label.
        before = self.robot.gl_lnk_tfarr.copy()
        after = self.robot.fk(self.robot.qs.copy())
        return bool(
            self.wrs.np.allclose(self.robot.qs, self.goal, atol=1e-6)
            and self.wrs.np.allclose(before, after, atol=1e-6)
            and self.wrs.np.isfinite(after).all()
            and (
                self.goal_tcp_tf is None
                or self.wrs.np.allclose(self.tcp.tf, self.goal_tcp_tf, atol=1e-4)
            )
        )


class VirtualState:
    def __init__(self, kinematics, objects=None):
        self.version = 0
        self.kinematics = kinematics
        self.objects = objects or {}
        self.pose = "home"

    def snapshot(self):
        return SceneData(
            robot=RobotData(pose=self.pose, kinematics=self.kinematics),
            objects={name: obj.model_copy(deep=True) for name, obj in self.objects.items()},
            facts={"calibration": "wrs2-lite6-v1", "collision_checked": False},
        )


async def make_wrs_environment(journal_path, *, duration=0.4, scene=None, allow_hardware=False):
    if allow_hardware:
        raise ValueError("hardware_unsupported")
    if not 0 < duration <= 30:
        raise ValueError("invalid_duration")
    objects = await asyncio.to_thread(load_scene, scene) if scene is not None else {}
    owner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wrs-model")
    loop = asyncio.get_running_loop()

    async def call(fn, *args):
        # Never cancel this future to claim a physical/model stop.
        return await loop.run_in_executor(owner, fn, *args)

    try:
        model = await call(VirtualModel)
        if scene is not None:
            objects = await call(model.load_scene, objects)
        state = VirtualState(await call(model.read), objects)
    except BaseException:
        owner.shutdown(wait=False)
        raise

    async def advance(skill, state, args, stop, progress):
        try:
            if skill == "observe":
                state.kinematics = await call(model.read)
                state.version += 1
                return state.kinematics["valid"]
            count = max(2, round(duration / 0.02) + 1)
            if skill == "move_relative":
                await call(model.begin_relative, (args.dx, args.dy, args.dz), count)
            else:
                await call(model.begin, args.pose, count)
            for index in range(1, count):
                if stop.is_set():
                    return False
                state.pose = None
                # One in-flight FK only. No model object is read by the control thread.
                state.kinematics = await call(model.step, index)
                state.version += 1
                if stop.is_set():
                    return False
                progress(index / (count - 1))
                try:
                    await asyncio.wait_for(stop.wait(), duration / (count - 1))
                except TimeoutError:
                    pass
            if stop.is_set():
                return False
            verified = await call(model.verify)
            if not stop.is_set() and verified:
                state.pose = args.pose if skill == "move_named_pose" else None
            return verified
        except SkillFailure:
            # An unreachable target has caused no model update.
            raise
        except Exception:
            state.kinematics = {**state.kinematics, "valid": False}
            # A model update may have happened; no blind allow_actions or retry.
            raise ExecutionUnknown("wrs_model_state_unknown") from None

    async def close():
        await asyncio.to_thread(owner.shutdown, wait=True)

    executor = ActionExecutor(
        journal_path,
        state=state,
        close_backend=close,
        skills={
            name: replace(SKILLS[name], handler=partial(advance, name))
            for name in ("observe", "move_named_pose", "move_relative")
        },
        duration=0,  # This backend advances itself; no Mock delay before motion.
        backend="wrs",
        capabilities_extra={
            "verification": "wrs_fk",
            "stop_scope": "virtual_fk_boundary",
            "controller_flush": False,
            "unsupported": {
                "pick": "Bare Lite6 profile has no validated gripper/grasp scene.",
                "place": "No verified held-object/contact state.",
                "verify": "Object placement verifier requires a grasp scene.",
                "hardware": "No verified controller stop/flush/state feedback.",
                "collision_planning": "No collision-checked path in this kinematic profile.",
            },
        },
    )
    return executor


def probe_virtual():
    from importlib.metadata import version

    wrs = load_wrs()
    robot = wrs.xarm_lite6.Lite6()
    transforms = robot.fk()
    return {
        "import": "PASS",
        "dependencies": {
            name: version(name) for name in ("numpy", "scipy", "mujoco", "wgpu", "websockets")
        },
        "module": wrs.__file__,
        "robot_class": type(robot).__name__,
        "fk_shape": list(transforms.shape),
        "qs": robot.qs.tolist(),
        "tcp_name": "flange",
        "tcp_pos": robot.tcp("flange").pos.tolist(),
        "tcp_rotmat": robot.tcp("flange").rotmat.tolist(),
        "hardware": False,
        "virtual_runtime_adapter": "wrs_ik_fk",
    }


async def serve_viewer_hub(port):
    # Keep all WRS imports in this adapter; no detached server survives the viewer.
    load_wrs()
    from wrs.viewer.server import serve

    await serve(host="127.0.0.1", port=port, idle_timeout=0, auto_open=False)
