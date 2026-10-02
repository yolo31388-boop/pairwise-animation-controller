"""动画控制器。

修复内容：
- 动画切换走时间混合（cross-fade），不再硬切；攻击等不可中断动作
  未播放完毕时拒绝普通切换，除非显式 force=True（打断会取消未触发事件）。
- 脚部 IK 目标权重由"是否启用 + 是否着地"共同决定，实际权重每帧渐变。
- 上下半身叠加按骨骼掩码混合，腰部为边界、权重 0.5/0.5，不重复归属。
- 根运动与代码移动二选一（root_motion_enabled），根运动同时含 X/Y 分量。
- 动画事件只在动画仍在播放且时间到达时触发，打断即取消未触发事件。
"""
from dataclasses import dataclass, field


@dataclass
class Animation:
    name: str
    duration: float
    current_time: float = 0.0
    looping: bool = False
    root_velocity: tuple = (0.0, 0.0)
    events: list = field(default_factory=list)

    def reset(self) -> None:
        self.current_time = 0.0

    def is_finished(self) -> bool:
        return not self.looping and self.current_time >= self.duration


UPPER_BONES = ("spine_chest", "neck", "head",
               "left_shoulder", "left_arm", "left_forearm", "left_hand",
               "right_shoulder", "right_arm", "right_forearm", "right_hand")
LOWER_BONES = ("pelvis", "left_thigh", "left_calf", "left_foot",
               "right_thigh", "right_calf", "right_foot")
# 腰部是上下半身的边界骨骼，两边各占 0.5，保证同一块骨骼权重和为 1，
# 不会同时被两边以满权重拉扯。
BOUNDARY_BONES = ("spine_waist",)


class AnimationController:
    # 不可被移动类动画中途打断的动作（必须播完，或显式 force 打断）
    ACTION_LOCKED = {"attack", "cast", "hit", "dodge", "roll"}

    def __init__(self, blend_duration: float = 0.2, ik_blend_duration: float = 0.15):
        self.current: Animation | None = None
        self.previous: Animation | None = None
        self.animations: dict[str, Animation] = {}

        self.blend_duration: float = max(blend_duration, 0.0)
        self.blend_time: float = 0.0

        self.ik_weight: float = 0.0
        self.ik_target_weight: float = 0.0
        self.ik_blend_duration: float = max(ik_blend_duration, 1e-6)

        # 二选一：True 用根运动驱动移动，False 用代码驱动移动
        self.root_motion_enabled: bool = False
        self.code_move_enabled: bool = True

        # 已在当前这次播放中触发过的事件帧（防止重复触发）
        self._fired_events: set = set()
        # 等待在 update 中到达帧时触发的事件: {anim_id: set(frame)}
        self._pending_events: dict = {}
        self._event_callbacks: dict = {}

    # ------------------------------------------------------------------ #
    # 动画注册
    # ------------------------------------------------------------------ #
    def add_animation(self, animation: Animation) -> None:
        self.animations[animation.name] = animation

    def register_event(self, animation: Animation, frame: int,
                       callback=None) -> None:
        if frame not in animation.events:
            animation.events.append(frame)
        self._pending_events.setdefault(id(animation), set()).add(frame)
        if callback is not None:
            self._event_callbacks[(id(animation), frame)] = callback

    # ------------------------------------------------------------------ #
    # 1. 动画切换：时间混合 + 未播完的攻击动作不被普通切换打断
    # ------------------------------------------------------------------ #
    def transition_animation(self, name: str, force: bool = False,
                             blend_duration: float | None = None) -> bool:
        target = self.animations.get(name)
        if target is None:
            return False

        if (self.current is not None
                and target is not self.current
                and not force
                and self._is_action_locked(self.current)):
            # 攻击等动作未播完，不允许被移动动画打断
            return False

        self._start_transition(target, blend_duration)
        if force:
            # 被打断：取消所有未触发的动画事件
            self._cancel_events()
        return True

    def play(self, name: str, force: bool = True, **kwargs) -> bool:
        # force=True 的语义：强制打断并切换（事件随之取消）
        return self.transition_animation(name, force=force, **kwargs)

    def _is_action_locked(self, animation: Animation) -> bool:
        if animation.name not in self.ACTION_LOCKED:
            return False
        if animation.looping:
            return False
        return (animation.current_time > 0.0
                and animation.current_time < animation.duration)

    def _start_transition(self, target: Animation,
                          blend_duration: float | None) -> None:
        if self.current is target:
            return
        self.previous = self.current
        self.current = target
        target.reset()
        duration = self.blend_duration if blend_duration is None else blend_duration
        self.blend_duration = max(duration, 0.0)
        self.blend_time = 0.0
        self._fired_events.clear()
        self._sync_pending(target)

    def _sync_pending(self, animation: Animation) -> None:
        self._pending_events.setdefault(id(animation), set())
        for frame in animation.events:
            self._pending_events[id(animation)].add(frame)

    def _cancel_events(self) -> None:
        if self.current is not None:
            self._pending_events.pop(id(self.current), None)
            self._fired_events.clear()
        if self.previous is not None:
            self._pending_events.pop(id(self.previous), None)

    @property
    def is_blending(self) -> bool:
        return (self.previous is not None
                and self.blend_time < self.blend_duration)

    @property
    def blend_weight(self) -> float:
        """新动画在混合中的权重：0 -> 1。"""
        if self.previous is None:
            return 1.0
        if self.blend_duration <= 0.0:
            return 1.0
        return min(self.blend_time / self.blend_duration, 1.0)

    def sample_blend(self) -> dict:
        return {
            "previous": None if self.previous is None else self.previous.name,
            "current": None if self.current is None else self.current.name,
            "weight": self.blend_weight,
        }

    # ------------------------------------------------------------------ #
    # 主推进
    # ------------------------------------------------------------------ #
    def update(self, delta_time: float) -> None:
        dt = max(delta_time, 0.0)

        # 推进混合
        if self.previous is not None:
            self.blend_time += dt
            if self.blend_time >= self.blend_duration:
                self.previous = None
                self.blend_time = self.blend_duration

        # 推进当前动画时间
        if self.current is not None:
            anim = self.current
            anim.current_time += dt
            if anim.looping and anim.duration > 0:
                anim.current_time %= anim.duration
                self._fired_events.clear()
                self._sync_pending(anim)
            self._fire_due_events(anim)

        self._update_ik(dt)

    def _fire_due_events(self, animation: Animation) -> None:
        pending = self._pending_events.get(id(animation))
        if not pending:
            return
        for frame in sorted(pending):
            if self._frame_time(animation, frame) <= animation.current_time:
                pending.discard(frame)
                key = (id(animation), frame)
                if key not in self._fired_events:
                    self._fired_events.add(key)
                    callback = self._event_callbacks.get(key)
                    if callback is not None:
                        callback(frame)

    def _frame_time(self, animation: Animation, frame: int,
                    fps: float = 30.0) -> float:
        return frame / fps

    # ------------------------------------------------------------------ #
    # 2. 脚部 IK：着地才施加目标权重，实际权重渐变，不跳变
    # ------------------------------------------------------------------ #
    def apply_ik(self, enable: bool, grounded: bool = True) -> None:
        self.ik_target_weight = 1.0 if (enable and grounded) else 0.0

    def _update_ik(self, dt: float) -> None:
        rate = dt / self.ik_blend_duration
        if self.ik_weight < self.ik_target_weight:
            self.ik_weight = min(self.ik_weight + rate, self.ik_target_weight)
        elif self.ik_weight > self.ik_target_weight:
            self.ik_weight = max(self.ik_weight - rate, self.ik_target_weight)

    # ------------------------------------------------------------------ #
    # 3. 上下半身叠加：按骨骼掩码混合，边界腰部 0.5/0.5
    # ------------------------------------------------------------------ #
    def blend_animations(self, upper: str, lower: str) -> dict:
        upper_weight = {bone: 1.0 for bone in UPPER_BONES}
        lower_weight = {bone: 1.0 for bone in LOWER_BONES}
        for bone in BOUNDARY_BONES:
            upper_weight[bone] = 0.5
            lower_weight[bone] = 0.5

        masks = {}
        masks.update(upper_weight)
        masks.update(lower_weight)
        return {
            "upper": upper,
            "lower": lower,
            "weight": 0.5,                      # 边界腰部的混合权重 < 1
            "upper_weight": 0.5,
            "lower_weight": 0.5,
            "upper_bones": UPPER_BONES,
            "lower_bones": LOWER_BONES,
            "boundary_bones": BOUNDARY_BONES,
            "bone_weights": masks,
        }

    # ------------------------------------------------------------------ #
    # 4. 根运动：与代码移动二选一，根运动含 X/Y 分量
    # ------------------------------------------------------------------ #
    def set_root_motion_enabled(self, enabled: bool) -> None:
        self.root_motion_enabled = enabled
        self.code_move_enabled = not enabled

    def enable_root_motion(self) -> None:
        self.set_root_motion_enabled(True)

    def disable_root_motion(self) -> None:
        self.set_root_motion_enabled(False)

    def extract_root_motion(self, animation: Animation,
                            delta: float) -> tuple:
        if not self.root_motion_enabled:
            # 代码移动模式：根运动不参与位移，交给代码移动，避免速度翻倍
            return (0.0, 0.0)
        vx, vy = animation.root_velocity
        return (vx * delta, vy * delta)

    def move(self, animation: Animation, delta: float,
             code_velocity: tuple = (0.0, 0.0)) -> tuple:
        """每帧应施加的位移：根运动与代码移动二选一。"""
        if self.root_motion_enabled:
            return self.extract_root_motion(animation, delta)
        vx, vy = code_velocity
        return (vx * delta, vy * delta)

    # ------------------------------------------------------------------ #
    # 5. 动画事件：被打断（current 已切换）或未到帧均不触发
    # ------------------------------------------------------------------ #
    def trigger_event(self, animation: Animation, frame: int) -> bool:
        # 动画已被打断 / 已切换走：未触发的事件一律取消
        if animation is not self.current:
            self._pending_events.get(id(animation), set()).discard(frame)
            return False
        # 动画已经播完一轮之后才到的帧不再触发
        if animation.is_finished() and self._frame_time(animation, frame) > animation.duration:
            return False

        key = (id(animation), frame)
        if key in self._fired_events:
            return False
        # 必须真的播放到了指定帧
        if self._frame_time(animation, frame) > animation.current_time:
            return False

        self._fired_events.add(key)
        self._pending_events.get(id(animation), set()).discard(frame)
        callback = self._event_callbacks.get(key)
        if callback is not None:
            callback(frame)
        return True

    def trigger_animation_event(self, animation: Animation, frame: int) -> bool:
        return self.trigger_event(animation, frame)
