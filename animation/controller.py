"""动画控制器"""
from dataclasses import dataclass, field


@dataclass
class Animation:
    name: str
    duration: float
    current_time: float = 0.0
    looping: bool = False
    interruptible: bool = True
    root_velocity: tuple = (1.0, 0.0)
    interrupted: bool = False
    pending_events: set = field(default_factory=set)
    triggered_events: set = field(default_factory=set)
    cancelled_events: set = field(default_factory=set)

    @property
    def is_finished(self) -> bool:
        return not self.looping and self.current_time >= self.duration


class AnimationController:
    UPPER_BONES = ("chest", "neck", "head", "shoulder_l", "shoulder_r",
                   "arm_l", "arm_r", "hand_l", "hand_r")
    LOWER_BONES = ("hips", "leg_l", "leg_r", "foot_l", "foot_r")
    WAIST_BONES = ("spine", "waist")

    def __init__(self, fps: float = 30.0):
        self.current: Animation = None
        self.previous: Animation = None
        self.animations: dict[str, Animation] = {}
        self.fps = fps
        self.blend_time: float = 0.2
        self.blend_elapsed: float = 0.0
        self.blend_weight: float = 1.0
        self.ik_weight: float = 0.0
        self.ik_target: float = 0.0
        self.ik_fade_rate: float = 4.0
        self.use_root_motion: bool = True
        self.code_move_speed: float = 1.0
        self._pending_transition: str = None

    def transition_animation(self, name: str, blend_time: float = None) -> bool:
        if name not in self.animations:
            return False
        target = self.animations[name]
        if target is self.current:
            return False
        old = self.current
        if old is not None and not old.interruptible and not old.is_finished:
            self._pending_transition = name
            return False
        if old is not None and not old.is_finished:
            self._interrupt(old)
        self.previous = old
        self.current = target
        target.current_time = 0.0
        target.interrupted = False
        if blend_time is not None:
            self.blend_time = blend_time
        self.blend_elapsed = 0.0
        self.blend_weight = 0.0 if old is not None else 1.0
        return True

    def _interrupt(self, animation: Animation) -> None:
        animation.interrupted = True
        animation.cancelled_events |= animation.pending_events
        animation.pending_events.clear()

    def update(self, dt: float) -> None:
        if self.previous is not None and self.blend_weight < 1.0:
            self.blend_elapsed += dt
            if self.blend_time > 0:
                self.blend_weight = min(1.0, self.blend_elapsed / self.blend_time)
            else:
                self.blend_weight = 1.0
            if self.blend_weight >= 1.0:
                self.previous = None
        if self.ik_weight < self.ik_target:
            self.ik_weight = min(self.ik_target, self.ik_weight + self.ik_fade_rate * dt)
        elif self.ik_weight > self.ik_target:
            self.ik_weight = max(self.ik_target, self.ik_weight - self.ik_fade_rate * dt)
        cur = self.current
        if cur is not None:
            cur.current_time += dt
            if cur.current_time >= cur.duration:
                if cur.looping and cur.duration > 0:
                    cur.current_time %= cur.duration
                else:
                    cur.current_time = cur.duration
                    if self._pending_transition is not None:
                        pending = self._pending_transition
                        self._pending_transition = None
                        self.transition_animation(pending)

    def apply_ik(self, enable: bool, dt: float = 0.1) -> None:
        self.ik_target = 1.0 if enable else 0.0
        step = self.ik_fade_rate * dt
        if self.ik_weight < self.ik_target:
            self.ik_weight = min(self.ik_target, self.ik_weight + step)
        elif self.ik_weight > self.ik_target:
            self.ik_weight = max(self.ik_target, self.ik_weight - step)

    def blend_animations(self, upper: str, lower: str) -> dict:
        bone_weights = {}
        for bone in self.UPPER_BONES:
            bone_weights[bone] = {"upper": 1.0, "lower": 0.0}
        for bone in self.LOWER_BONES:
            bone_weights[bone] = {"upper": 0.0, "lower": 1.0}
        for bone in self.WAIST_BONES:
            bone_weights[bone] = {"upper": 0.5, "lower": 0.5}
        return {
            "upper": upper,
            "lower": lower,
            "weight": 0.5,
            "bone_weights": bone_weights,
        }

    def extract_root_motion(self, animation: Animation, delta: float) -> tuple:
        vx, vy = animation.root_velocity
        return (vx * delta, vy * delta)

    def compute_movement(self, delta: float) -> tuple:
        if self.use_root_motion and self.current is not None:
            return self.extract_root_motion(self.current, delta)
        return (self.code_move_speed * delta, 0.0)

    def trigger_event(self, animation: Animation, frame: int) -> bool:
        if animation is not self.current:
            return False
        if animation.interrupted:
            return False
        if frame in animation.cancelled_events:
            return False
        frame_time = frame / self.fps
        if not (frame_time <= animation.current_time <= animation.duration):
            return False
        animation.triggered_events.add(frame)
        animation.pending_events.discard(frame)
        return True
