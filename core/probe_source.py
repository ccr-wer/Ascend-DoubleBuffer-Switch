"""探测数据源抽象。

逻辑层只依赖这个接口：真实探测（ICMP/HTTP/代理延迟）由外部实现，
本仓库不提供任何真实网络探测，相关接入方式见 docs/unverified.md（UNVERIFIED）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProbeResult:
    node_id: str
    latency_ms: float
    loss_pct: float
    throughput_mbps: float
    timestamp: float


class ProbeSource(ABC):
    @abstractmethod
    def probe(self, node_id: str) -> ProbeResult:
        raise NotImplementedError
