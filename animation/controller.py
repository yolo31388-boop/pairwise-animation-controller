"""动画控制器 - 含5个bug"""
from dataclasses import dataclass, field

@dataclass
class Animation:
    name: str
    duration: float
    current_time: float = 0.0
    looping: bool = False

class AnimationController:
    def __init__(self):
        self.current: Animation = None
        self.animations: dict[str, Animation] = {}
        self.ik_weight: float = 0.0  # bug2: 不渐变

    def transition_animation(self, name: str) -> bool:
        # bug1: 不混合，直接跳
        if name not in self.animations:
            return False
        self.current = self.animations[name]
        return True

    def apply_ik(self, enable: bool) -> None:
        # bug2: IK权重不渐变
        self.ik_weight = 1.0 if enable else 0.0

    def blend_animations(self, upper: str, lower: str) -> dict:
        # bug3: 骨骼权重计算错误
        return {"upper": upper, "lower": lower, "weight": 1.0}

    def extract_root_motion(self, animation: Animation, delta: float) -> tuple:
        # bug4: 根运动和代码移动叠加
        return (delta * 5, 0)

    def trigger_event(self, animation: Animation, frame: int) -> bool:
        # bug5: 动画打断后事件还触发
        return True
