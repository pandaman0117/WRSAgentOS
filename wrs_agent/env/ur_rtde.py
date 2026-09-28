"""UR7e over ur_rtde and a DH gripper over Modbus RTU. No WRS, no Zenoh, no asyncio.

Every method runs on one caller-owned thread. Only latest() and the stop Event passed
to follow()/move_gripper() may be used from another thread.
"""

import math
import threading
import time
from dataclasses import dataclass

# ur_rtde RTDEReceiveInterface codes.
ROBOT_MODE_RUNNING = 7
SAFE_MODES = {1, 2}  # NORMAL, REDUCED; everything else is a stop, fault or recovery.

# DH PGC Modbus registers; the position registers are permille of the full stroke.
DH_INIT, DH_FORCE, DH_POSITION, DH_SPEED = 0x0100, 0x0101, 0x0103, 0x0104
DH_INIT_STATE, DH_GRIP_STATE, DH_POSITION_NOW = 0x0200, 0x0201, 0x0202
GRIP_MOVING, GRIP_ARRIVED, GRIP_CAUGHT, GRIP_DROPPED = 0, 1, 2, 3

# servoJ tracking: lookahead smooths the stream, and the final target is held until it
# converges, otherwise servoStop cuts the last lookahead window short.
LOOKAHEAD, GAIN = 0.1, 300
STOP_DECELERATION = 5.0  # rad/s^2
REST_SPEED = 0.005  # rad/s
SETTLE_TOLERANCE = 1e-3  # rad


class DeviceFault(RuntimeError):
    """The device refused, reported a safety stop, or replied with a corrupt frame."""


class StopUnconfirmed(RuntimeError):
    """A stop was commanded, but the device was not observed at rest."""


@dataclass(frozen=True)
class Sample:
    qs: tuple
    qd: tuple
    width: float | None
    robot_mode: int
    safety_mode: int
    program_running: bool
    observed_at_ns: int

    @property
    def ready(self):
        return (
            self.robot_mode == ROBOT_MODE_RUNNING
            and self.safety_mode in SAFE_MODES
            and self.program_running
            and self.width is not None
        )

    @property
    def status(self):
        if self.safety_mode not in SAFE_MODES:
            return f"safety_mode_{self.safety_mode}"
        if self.robot_mode != ROBOT_MODE_RUNNING:
            return f"robot_mode_{self.robot_mode}"
        if not self.program_running:
            return "rtde_script_stopped"
        return "ready" if self.width is not None else "gripper_unread"


def min_jerk_path(start, goal, *, dt, max_speed, min_duration):
    """Joint targets every dt. Quintic timing peaks at 1.875x the mean speed."""
    delta = [g - s for s, g in zip(start, goal, strict=True)]
    span = max(abs(d) for d in delta)
    duration = max(min_duration, 1.875 * span / max_speed)
    steps = max(1, math.ceil(duration / dt))
    path = []
    for index in range(1, steps + 1):
        t = index / steps
        s = t**3 * (10 - 15 * t + 6 * t * t)
        path.append([a + d * s for a, d in zip(start, delta, strict=True)])
    return path


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


class DHGripper:
    """DH PGC-style jaw on RS485. Every reply is checked for unit, function, echo and CRC."""

    def __init__(self, port, *, max_width, unit=1):
        self.port, self.max_width, self.unit = port, float(max_width), unit

    def _exchange(self, frame, size):
        frame += crc16(frame)
        for _ in range(3):
            self.port.reset_input_buffer()
            self.port.write(frame)
            reply = self.port.read(size)
            if len(reply) == size and reply[:2] == frame[:2] and crc16(reply[:-2]) == reply[-2:]:
                return reply
        raise DeviceFault("gripper_modbus_reply")

    def write(self, register, value):
        frame = bytes([self.unit, 0x06]) + register.to_bytes(2, "big") + value.to_bytes(2, "big")
        if self._exchange(frame, 8)[:6] != frame:
            raise DeviceFault("gripper_modbus_echo")

    def read(self, register):
        frame = bytes([self.unit, 0x03]) + register.to_bytes(2, "big") + (1).to_bytes(2, "big")
        reply = self._exchange(frame, 7)
        if reply[2] != 2:
            raise DeviceFault("gripper_modbus_length")
        return int.from_bytes(reply[3:5], "big")

    def initialize(self, *, force=30, speed=50, timeout=8.0):
        """Initialization strokes the jaw fully once; skip it when already initialized."""
        if self.read(DH_INIT_STATE) != 1:
            self.write(DH_INIT, 0xA5)
            deadline = time.monotonic() + timeout
            while self.read(DH_INIT_STATE) != 1:
                if time.monotonic() > deadline:
                    raise DeviceFault("gripper_init_timeout")
                time.sleep(0.1)
        self.write(DH_FORCE, force)
        self.write(DH_SPEED, speed)

    def width(self):
        return self.read(DH_POSITION_NOW) * self.max_width / 1000

    def state(self):
        return self.read(DH_GRIP_STATE)

    def command(self, width):
        self.write(DH_POSITION, round(min(max(width / self.max_width, 0.0), 1.0) * 1000))

    def halt(self):
        # Retarget to where the jaw is now; the gripper has no separate stop register.
        self.write(DH_POSITION, self.read(DH_POSITION_NOW))

    def close(self):
        self.port.close()


class UR7eDH50:
    """Real arm and jaw. Construct through connect(); tests pass fake interfaces."""

    def __init__(self, receive, control, gripper, *, frequency=500.0):
        self.receive, self.control, self.gripper = receive, control, gripper
        self.dt = 1.0 / frequency
        self._lock = threading.Lock()
        self._latest = None
        self._width = None

    def latest(self):
        """(qs, width, progress) from the running motion; safe from any thread."""
        with self._lock:
            return self._latest

    def _publish(self, qs, progress):
        with self._lock:
            self._latest = (tuple(qs), self._width, progress)

    def read(self):
        self._width = self.gripper.width()
        return Sample(
            qs=tuple(self.receive.getActualQ()),
            qd=tuple(self.receive.getActualQd()),
            width=self._width,
            robot_mode=self.receive.getRobotMode(),
            safety_mode=self.receive.getSafetyMode(),
            program_running=bool(self.control.isProgramRunning()),
            observed_at_ns=time.time_ns(),
        )

    def _check_safety(self):
        if self.receive.getSafetyMode() not in SAFE_MODES:
            raise DeviceFault("robot_safety_stop")

    def _wait_rest(self, timeout=2.0):
        deadline, still = time.monotonic() + timeout, 0
        while time.monotonic() < deadline:
            still = still + 1 if max(map(abs, self.receive.getActualQd())) < REST_SPEED else 0
            if still >= 3:
                self._publish(self.receive.getActualQ(), None)
                return
            time.sleep(0.01)
        raise StopUnconfirmed("arm_not_at_rest")

    def follow(self, path, stop, *, settle=0.5):
        """Stream path; return "done"/"stopped" only after the arm is observed at rest."""
        try:
            for index, q in enumerate(path, 1):
                if stop.is_set():
                    break
                start = self.control.initPeriod()
                if not self.control.servoJ(list(q), 0.0, 0.0, self.dt, LOOKAHEAD, GAIN):
                    raise DeviceFault("servo_rejected")
                if index % 10 == 0 or index == len(path):
                    self._check_safety()
                    self._publish(self.receive.getActualQ(), index / len(path))
                self.control.waitPeriod(start)
            else:
                goal = list(path[-1])
                for _ in range(max(1, round(settle / self.dt))):
                    if stop.is_set():
                        break
                    start = self.control.initPeriod()
                    self.control.servoJ(goal, 0.0, 0.0, self.dt, LOOKAHEAD, GAIN)
                    actual = self.receive.getActualQ()
                    self.control.waitPeriod(start)
                    error = max(abs(a - g) for a, g in zip(actual, goal, strict=True))
                    if error <= SETTLE_TOLERANCE:
                        break
        finally:
            self.control.servoStop(STOP_DECELERATION)
        self._wait_rest()
        return "stopped" if stop.is_set() else "done"

    def move_gripper(self, width, stop, *, timeout=5.0):
        """Return the DH grip state after the jaw stops, or "stopped" after a halt."""
        self.gripper.command(width)
        began = time.monotonic()
        seen_moving = False
        while True:
            if stop.is_set():
                self.gripper.halt()
                self._wait_jaw(began + timeout)
                return "stopped"
            state = self.gripper.state()
            self._width = self.gripper.width()
            self._publish(self.receive.getActualQ(), None)
            seen_moving |= state == GRIP_MOVING
            # A fresh command may still report the previous terminal state for a moment.
            if state != GRIP_MOVING and (seen_moving or time.monotonic() - began > 0.3):
                return state
            if time.monotonic() - began > timeout:
                self.gripper.halt()
                raise DeviceFault("gripper_timeout")
            time.sleep(0.02)

    def _wait_jaw(self, deadline):
        while time.monotonic() < deadline:
            if self.gripper.state() != GRIP_MOVING:
                self._width = self.gripper.width()
                return
            time.sleep(0.02)
        raise StopUnconfirmed("gripper_not_at_rest")

    def close(self):
        # Closing connections never moves the arm; each resource is released independently.
        for release in (self.control.stopScript, self.control.disconnect,
                        self.receive.disconnect, self.gripper.close):
            try:
                release()
            except Exception:
                pass


def connect(robot_ip, gripper_port, *, frequency=500.0, gripper_width=0.05, payload_kg=None):
    """Open receive first and refuse a stopped or faulted arm before taking control."""
    import rtde_control
    import rtde_receive
    import serial

    receive = rtde_receive.RTDEReceiveInterface(robot_ip, frequency)
    control = port = None
    try:
        mode, safety = receive.getRobotMode(), receive.getSafetyMode()
        if mode != ROBOT_MODE_RUNNING or safety not in SAFE_MODES:
            raise DeviceFault(f"robot_not_ready_mode_{mode}_safety_{safety}")
        port = serial.Serial(gripper_port, 115200, bytesize=8, parity="N", stopbits=1, timeout=0.2)
        gripper = DHGripper(port, max_width=gripper_width)
        gripper.initialize()
        # Uploads the RTDE control script; the controller must be in remote control mode.
        control = rtde_control.RTDEControlInterface(robot_ip, frequency)
        if payload_kg is not None:
            control.setPayload(payload_kg, [0.0, 0.0, 0.0])
        return UR7eDH50(receive, control, gripper, frequency=frequency)
    except BaseException:
        for release in (
            getattr(control, "disconnect", None), receive.disconnect, getattr(port, "close", None)
        ):
            if release is not None:
                try:
                    release()
                except Exception:
                    pass
        raise
