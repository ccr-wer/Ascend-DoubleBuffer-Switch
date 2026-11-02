"""六场景回归测试：手动 step 驱动，无任何等待与外部依赖。

运行：python -m unittest discover tests
"""

import io
import unittest
from contextlib import redirect_stdout

from core.actions import Actions
from core.fake_source import (
    scenario_a_degraded_b_healthy,
    scenario_both_degraded,
    scenario_brief_blip,
    scenario_cooldown_blocks,
    scenario_stable_a,
    scenario_swap_then_b_degrades,
)
from core.state_machine import State, StateMachine, SwitchConfig


class ScenarioTests(unittest.TestCase):
    def run_scenario(self, factory, steps):
        source = factory()
        machine = StateMachine(SwitchConfig(), Actions())
        # 动作层会打印 WOULD 日志，这里吞掉以保持测试输出干净。
        with redirect_stdout(io.StringIO()):
            for _ in range(steps):
                machine.step(source.probe("A"), source.probe("B"))
        return machine

    def to_states(self, machine):
        return [to_state for _, to_state, _ in machine.history]

    def test_stable_a(self):
        machine = self.run_scenario(scenario_stable_a, 12)
        self.assertIs(machine.state, State.STABLE_A)
        self.assertEqual(machine.history, [])
        self.assertFalse(machine.on_b)

    def test_a_degraded_b_healthy(self):
        machine = self.run_scenario(scenario_a_degraded_b_healthy, 16)
        states = self.to_states(machine)
        self.assertIs(machine.state, State.SWAPPED)
        for expected in (State.DEGRADED_A, State.PREBUILDING_B,
                         State.B_HEALTHY_READY, State.SWAPPED):
            self.assertIn(expected, states)
        self.assertNotIn(State.ROLLBACK, states)
        self.assertNotIn(State.BOTH_DEGRADED, states)
        self.assertTrue(machine.on_b)

    def test_both_degraded(self):
        machine = self.run_scenario(scenario_both_degraded, 16)
        states = self.to_states(machine)
        self.assertIs(machine.state, State.BOTH_DEGRADED)
        self.assertNotIn(State.SWAPPED, states)
        self.assertNotIn(State.PREBUILDING_B, states)
        self.assertFalse(machine.on_b)
        reasons = [reason for _, to_state, reason in machine.history
                   if to_state is State.BOTH_DEGRADED]
        self.assertIn("shared bottleneck suspected", reasons)

    def test_brief_blip(self):
        machine = self.run_scenario(scenario_brief_blip, 16)
        states = self.to_states(machine)
        self.assertIs(machine.state, State.STABLE_A)
        self.assertNotIn(State.DEGRADED_A, states)
        self.assertNotIn(State.SWAPPED, states)
        self.assertFalse(machine.on_b)

    def test_swap_then_b_degrades(self):
        machine = self.run_scenario(scenario_swap_then_b_degrades, 22)
        states = self.to_states(machine)
        self.assertIn(State.SWAPPED, states)
        self.assertIn(State.ROLLBACK, states)
        self.assertLess(states.index(State.SWAPPED), states.index(State.ROLLBACK))
        self.assertIs(machine.state, State.ROLLBACK)
        self.assertFalse(machine.on_b)
        self.assertNotIn(State.BOTH_DEGRADED, states)

    def test_cooldown_blocks(self):
        machine = self.run_scenario(scenario_cooldown_blocks, 24)
        states = self.to_states(machine)
        self.assertEqual(states.count(State.SWAPPED), 1)
        self.assertIn(State.COOLDOWN, states)
        self.assertNotIn(State.ROLLBACK, states)
        swap_index = states.index(State.SWAPPED)
        self.assertIn(State.COOLDOWN, states[swap_index + 1:])
        self.assertTrue(machine.on_b)


if __name__ == "__main__":
    unittest.main()
