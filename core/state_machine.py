"""双缓冲上游热切换状态机（纯逻辑）。

约束：本模块不做任何 I/O，不读时钟，不依赖平台。时序完全由调用方
以 step() 驱动，结果时间戳由 ProbeSource 提供。

优先级之外的一个必要补充：self.on_b 记录"当前由哪个槽位承载流量"，
它与 COOLDOWN 这种状态解耦——冷却只是暂时禁止动作，不代表已经回切。
没有它，场景5会在 swap 后被 A 的旧劣化抢先进 BOTH_DEGRADED，
场景6会在冷却结束后对同一个 B 重复 swap。详见 docs/architecture.md。
"""

from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Tuple

from .probe_source import ProbeResult


class State(Enum):
    STABLE_A = auto()
    DEGRADED_A = auto()
    PREBUILDING_B = auto()
    B_HEALTHY_READY = auto()
    SWAPPED = auto()
    ROLLBACK = auto()
    BOTH_DEGRADED = auto()
    COOLDOWN = auto()


@dataclass
class SwitchConfig:
    window_size: int = 10
    degrade_ratio: float = 0.6
    cooldown_ticks: int = 5
    latency_threshold_ms: float = 80.0
    loss_threshold_pct: float = 5.0
    throughput_threshold_mbps: float = 1.0
    # 以上阈值为占位默认值，UNVERIFIED：未在任何真实网络上标定。
    # 正确做法是按实测分布取 P95/P99 再定阈值，见 docs/unverified.md。


def is_degraded(result: ProbeResult, cfg: SwitchConfig) -> bool:
    return (
        result.latency_ms > cfg.latency_threshold_ms
        or result.loss_pct > cfg.loss_threshold_pct
        or result.throughput_mbps < cfg.throughput_threshold_mbps
    )


class StateMachine:
    def __init__(self, cfg: SwitchConfig, actions):
        self.cfg = cfg
        self.actions = actions
        self.window_a = deque(maxlen=cfg.window_size)
        self.window_b = deque(maxlen=cfg.window_size)
        self.state = State.STABLE_A
        self.cooldown = 0
        self.on_b = False
        self._history: List[Tuple[State, State, str]] = []

    @property
    def history(self) -> List[Tuple[State, State, str]]:
        return self._history

    def _ratio(self, window) -> float:
        if not window:
            return 0.0
        bad = sum(1 for r in window if is_degraded(r, self.cfg))
        return bad / len(window)

    def _go(self, to_state: State, reason: str) -> None:
        if to_state is self.state:
            return
        self._history.append((self.state, to_state, reason))
        self.state = to_state

    def step(self, result_a: ProbeResult, result_b: Optional[ProbeResult] = None) -> State:
        self.window_a.append(result_a)
        if result_b is not None:
            self.window_b.append(result_b)

        a_ratio = self._ratio(self.window_a)
        b_ratio = self._ratio(self.window_b) if self.window_b else None
        b_id = result_b.node_id if result_b is not None else "B"

        # 1) 冷却优先：冷却期内只衰减计数，不做任何切换判断。
        if self.cooldown > 0:
            self.cooldown -= 1
            self._go(State.COOLDOWN, "cooldown active, switch suppressed")
            return self.state

        if not self.on_b:
            # 2) 双槽同时劣化：疑似共享段瓶颈，切换无意义。
            if (
                a_ratio >= self.cfg.degrade_ratio
                and b_ratio is not None
                and b_ratio >= self.cfg.degrade_ratio
            ):
                self._go(State.BOTH_DEGRADED, "shared bottleneck suspected")
                return self.state

            # 3) A 劣化而 B 可用：预建 -> 确认 -> 切换，在逻辑层一次 step 内完成。
            #    B 完全无探测数据时也允许切换，这是骨架的简化（UNVERIFIED），
            #    真实实现应要求 B 先被证明健康。
            if a_ratio >= self.cfg.degrade_ratio and (
                b_ratio is None or b_ratio < self.cfg.degrade_ratio
            ):
                self._go(
                    State.DEGRADED_A,
                    f"a degraded ratio {a_ratio:.2f} >= {self.cfg.degrade_ratio}",
                )
                self._go(State.PREBUILDING_B, "prebuild B while A still carries traffic")
                self.actions.on_prebuild(b_id)
                self._go(State.B_HEALTHY_READY, "b window below degrade ratio")
                self._go(State.SWAPPED, "swap default route to B (stub)")
                self.actions.on_swap(b_id)
                self.on_b = True
                self.cooldown = self.cfg.cooldown_ticks
                return self.state
        else:
            # 4) 已经由 B 承载：只关心 B 是否劣化到需要回滚。
            if b_ratio is not None and b_ratio >= self.cfg.degrade_ratio:
                self._go(
                    State.ROLLBACK,
                    f"b degraded ratio {b_ratio:.2f} >= {self.cfg.degrade_ratio}",
                )
                self.actions.on_rollback(result_a.node_id)
                self.on_b = False
                self.cooldown = self.cfg.cooldown_ticks
                return self.state

        # 5) 无动作。
        self._go(State.STABLE_A, "within thresholds, no switch")
        return self.state
