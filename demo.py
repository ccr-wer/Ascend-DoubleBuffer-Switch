"""六个场景的逻辑层演示。

运行：python demo.py
不需要网络、不需要管理员权限、不需要任何环境变量。
所有"探测数据"来自 core/fake_source.py 的剧本，所有切换动作都是 WOULD 桩。
"""

from core.actions import Actions
from core.fake_source import (
    scenario_a_degraded_b_healthy,
    scenario_both_degraded,
    scenario_brief_blip,
    scenario_cooldown_blocks,
    scenario_stable_a,
    scenario_swap_then_b_degrades,
)
from core.state_machine import StateMachine, SwitchConfig, is_degraded

SCENARIOS = [
    ("stable_a", scenario_stable_a, 12),
    ("a_degraded_b_healthy", scenario_a_degraded_b_healthy, 16),
    ("both_degraded", scenario_both_degraded, 16),
    ("brief_blip", scenario_brief_blip, 16),
    ("swap_then_b_degrades", scenario_swap_then_b_degrades, 22),
    ("cooldown_blocks", scenario_cooldown_blocks, 24),
]


def run_scenario(index, name, factory, steps):
    print(f"=== scenario {index}: {name} ===")
    source = factory()
    cfg = SwitchConfig()
    machine = StateMachine(cfg, Actions())
    seen = 0
    for tick in range(1, steps + 1):
        result_a = source.probe("A")
        result_b = source.probe("B")
        state = machine.step(result_a, result_b)
        print(
            f"  step {tick:02d} | A lat={result_a.latency_ms:6.1f}ms "
            f"loss={result_a.loss_pct:.1f}% tp={result_a.throughput_mbps:.1f}Mbps "
            f"degraded={is_degraded(result_a, cfg)}"
            f" | B lat={result_b.latency_ms:6.1f}ms "
            f"degraded={is_degraded(result_b, cfg)}"
            f" -> {state.name}"
        )
        for from_state, to_state, reason in machine.history[seen:]:
            print(f"    transition: {from_state.name} -> {to_state.name} | {reason}")
        seen = len(machine.history)
    print(f"  final state: {machine.state.name} | transitions={len(machine.history)}")
    print()


def main():
    print("double-buffer-switch: logic-layer demo (scripted data, stub actions)")
    print()
    for index, (name, factory, steps) in enumerate(SCENARIOS, start=1):
        run_scenario(index, name, factory, steps)


if __name__ == "__main__":
    main()
