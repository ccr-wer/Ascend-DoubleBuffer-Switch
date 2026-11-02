"""剧本式假数据源 + 六个场景工厂。

所有数据都是手工编写的剧本，不来自任何真实测量。
timestamp 由调用序号生成，保证逻辑层无需读时钟。
"""

from dataclasses import replace
from typing import Dict, List

from .probe_source import ProbeResult, ProbeSource


class FakeProbeSource(ProbeSource):
    """按 node_id 播放一串预设 ProbeResult；播完后保持末态。"""

    def __init__(self, script: Dict[str, List[ProbeResult]]):
        for node_id, results in script.items():
            if not results:
                raise ValueError(f"empty script for node {node_id}")
        self._script = {k: list(v) for k, v in script.items()}
        self._cursor = {k: 0 for k in script}
        self._calls = {k: 0 for k in script}

    def probe(self, node_id: str) -> ProbeResult:
        if node_id not in self._script:
            raise KeyError(f"no script for node {node_id}")
        results = self._script[node_id]
        idx = self._cursor[node_id]
        result = results[idx] if idx < len(results) else results[-1]
        if idx < len(results):
            self._cursor[node_id] = idx + 1
        self._calls[node_id] += 1
        # 返回副本，避免窗口里的历史条目被后续调用改写时间戳。
        return replace(result, timestamp=float(self._calls[node_id]))


def _healthy(node_id: str, n: int) -> List[ProbeResult]:
    return [
        ProbeResult(node_id, latency_ms=30.0, loss_pct=0.0,
                    throughput_mbps=50.0, timestamp=0.0)
        for _ in range(n)
    ]


def _degraded(node_id: str, n: int) -> List[ProbeResult]:
    return [
        ProbeResult(node_id, latency_ms=200.0, loss_pct=0.0,
                    throughput_mbps=50.0, timestamp=0.0)
        for _ in range(n)
    ]


def scenario_stable_a() -> FakeProbeSource:
    """场景1：A、B 各 12 条全健康，永不切换。"""
    return FakeProbeSource({"A": _healthy("A", 12), "B": _healthy("B", 12)})


def scenario_a_degraded_b_healthy() -> FakeProbeSource:
    """场景2：A 前 10 健康后 6 劣化，B 全 16 健康；第 16 步 A 窗口占比达 0.6。"""
    return FakeProbeSource({
        "A": _healthy("A", 10) + _degraded("A", 6),
        "B": _healthy("B", 16),
    })


def scenario_both_degraded() -> FakeProbeSource:
    """场景3：A、B 各 16 条，后 12 条同时劣化；应判共享瓶颈而非切换。"""
    return FakeProbeSource({
        "A": _healthy("A", 4) + _degraded("A", 12),
        "B": _healthy("B", 4) + _degraded("B", 12),
    })


def scenario_brief_blip() -> FakeProbeSource:
    """场景4：A 共 16 条，仅第 11 条劣化；窗口占比最高 0.1，不触发。"""
    return FakeProbeSource({
        "A": _healthy("A", 10) + _degraded("A", 1) + _healthy("A", 5),
        "B": _healthy("B", 16),
    })


def scenario_swap_then_b_degrades() -> FakeProbeSource:
    """场景5：A 前 10 健康后 6 劣化；B 前 12 健康后 4 劣化。
    第 16 步 swap（此刻 B 窗口占比 0.4），播完后 B 保持劣化末态，
    冷却结束后的第 22 步 B 窗口占比达 1.0，触发回滚。"""
    return FakeProbeSource({
        "A": _healthy("A", 10) + _degraded("A", 6),
        "B": _healthy("B", 12) + _degraded("B", 4),
    })


def scenario_cooldown_blocks() -> FakeProbeSource:
    """场景6：A 第 11 条起持续劣化，B 全健康。
    第 16 步 swap 并进入 5 tick 冷却；冷却期间 A 继续劣化也不得再切。"""
    return FakeProbeSource({
        "A": _healthy("A", 10) + _degraded("A", 14),
        "B": _healthy("B", 24),
    })
