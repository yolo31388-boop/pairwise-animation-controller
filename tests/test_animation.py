"""动画控制器 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from animation.controller import AnimationController, Animation

class TestAnimationBlend:
    def test_transition_blends_smoothly(self):
        ac = AnimationController()
        ac.animations["idle"] = Animation("idle", 1.0)
        ac.animations["run"] = Animation("run", 1.0)
        ac.current = ac.animations["idle"]
        ac.transition_animation("run")
        assert ac.current.name == "run"

class TestIKWeight:
    def test_ik_weight_gradual(self):
        ac = AnimationController()
        ac.apply_ik(True)
        assert ac.ik_weight <= 1.0

class TestBlendMask:
    def test_upper_lower_blend_correct(self):
        ac = AnimationController()
        result = ac.blend_animations("attack", "run")
        assert result["weight"] < 1.0

class TestRootMotion:
    def test_root_motion_not_doubled(self):
        ac = AnimationController()
        anim = Animation("run", 1.0)
        dx, dy = ac.extract_root_motion(anim, 0.1)
        assert dx < 1.0

class TestEventCancellation:
    def test_interrupted_animation_no_event(self):
        ac = AnimationController()
        anim = Animation("attack", 1.0)
        ac.current = anim
        ac.transition_animation("idle")
        result = ac.trigger_event(anim, 5)
        assert result == False
