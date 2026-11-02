> - 本项目验证的是逻辑层（状态机 + 时序），不是网络层（真实探测/真实切换）。
> - 真实环境验证未完成，swap 动作为桩实现。
> - 定位：给有环境的人提供可执行的图纸，欢迎补真探测与平台适配层。

# double-buffer-switch

把"算子双缓冲"的语义映射到上游链路热切换：A 还在承载流量时就预建并评估 B，满足条件再交换槽位，而不是等 A 断了才救。本仓库只有可运行、可测试的逻辑层参考实现，网络层与动作层留接口和桩。

## 架构

```
                 ProbeSource(接口)
                       │
        剧本 FakeProbeSource │ 真实探测(待补, UNVERIFIED)
                       ▼
              ┌─────────────────┐
   fill ────► │  A 槽位(承载中)  │ ──► 滑动窗口 + 劣化占比
              ├─────────────────┤
   fill ────► │  B 槽位(预建中)  │ ──► 滑动窗口 + 劣化占比
              └─────────────────┘
                       │  状态机判定(见下)
        ┌──────────────┼───────────────────┐
        ▼              ▼                   ▼
   A 劣化/B 健康    A、B 同时劣化        B 劣化(已切到 B)
   fill→swap       不切换               release→rollback
   (预建后交换)    BOTH_DEGRADED        (回收到 A)
                       │
                       ▼
              Actions(桩, 只打印 WOULD)
              真实路由/代理适配见 adapter/ (UNVERIFIED)
```

状态迁移优先级：COOLDOWN 冷却 → BOTH_DEGRADED 共享瓶颈 → DEGRADED_A→PREBUILDING_B→B_HEALTHY_READY→SWAPPED 链 → ROLLBACK 回滚 → STABLE_A 无动作。细节见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

```bash
python demo.py
python -m unittest discover tests
```

无第三方依赖（requirements.txt 只有注释），不需要网络、权限或环境变量。Python 3.7+（用到 dataclasses；类型标注走 typing，不用 3.9 的内建泛型）。

## 目录

| 路径 | 作用 |
|---|---|
| `core/probe_source.py` | ProbeResult 数据类 + ProbeSource 抽象接口 |
| `core/fake_source.py` | 剧本式 FakeProbeSource + 六场景工厂 |
| `core/state_machine.py` | State 枚举、SwitchConfig、is_degraded、StateMachine |
| `core/actions.py` | 动作桩：on_prebuild / on_swap / on_rollback，只打印 WOULD |
| `demo.py` | 一条命令跑完六场景，打印输入摘要与迁移日志 |
| `tests/test_scenarios.py` | 六场景 unittest 回归 |
| `adapter/README.md` | 平台适配层要做什么（UNVERIFIED，无代码） |
| `docs/` | 架构说明、待验证清单、博客草稿 |

## 六个场景

| # | 场景 | 剧本要点 | 期望结果 |
|---|---|---|---|
| 1 | stable_a | A、B 各 12 条全健康 | 一直 STABLE_A，无迁移 |
| 2 | a_degraded_b_healthy | A 前 10 健康后 6 劣化，B 全健康 | 第 16 步 A 窗口占比 0.6，进入 SWAPPED |
| 3 | both_degraded | A、B 后 12 条同时劣化 | BOTH_DEGRADED，全程无 SWAPPED |
| 4 | brief_blip | A 仅第 11 条劣化 | 占比不足，连 DEGRADED_A 都不出现 |
| 5 | swap_then_b_degrades | 先 swap，B 随后持续劣化 | 冷却结束后 ROLLBACK |
| 6 | cooldown_blocks | swap 后 A 继续劣化 | 冷却期不再切换，SWAPPED 仅 1 次，出现 COOLDOWN |

## 待验证

真实环境相关的一切（共享瓶颈判定、重认证、平台权限、阈值标定等）都是 UNVERIFIED，清单与验证方法见 [docs/unverified.md](docs/unverified.md)。
