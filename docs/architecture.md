# 架构：双缓冲语义 → 上游热切换

## 1. 语义映射

算子双缓冲里，计算与预取重叠：Buffer A 在被消费的同时，Buffer B 被后台填满，随后只交换指针。把这套语义搬到上游链路：

| 双缓冲 | 上游热切换 | 本仓库对应物 |
|---|---|---|
| Buffer A（正在计算） | A 槽位：当前承载默认路由的上游 | `window_a`、`on_b=False` |
| Buffer B（后台预取） | B 槽位：不承载流量，但被持续探测/评估 | `window_b` |
| fill（预取） | 对 B 的预建与质量确认（鉴权、测速） | `PREBUILDING_B` + `actions.on_prebuild` |
| swap（交换指针） | 把默认路由/分流规则指到 B | `SWAPPED` + `actions.on_swap`（桩） |
| release（回收旧 buffer） | A 退为候选，或 B 劣化后回滚到 A | `ROLLBACK` + `actions.on_rollback`（桩） |
| pipeline overlap | A 还在跑流量时，B 的评估已经在进行 | 每次 `step()` 同时喂 A、B 两份结果 |

关键不是"多一条链路"，而是**时序**：B 的评估发生在 A 仍然健康或刚开始劣化的时候，切换决策用的是已经攒好的 B 窗口，而不是故障发生后才开始测量。

## 2. 与 mwan3 类方案的差异

mwan3 这类策略路由工具的常见用法是 failover：跟踪接口在线状态，接口被判离线之后才把流量移走（此处指其常见的断线切换用法，本项目未在任何真实 OpenWrt 环境实测其行为，UNVERIFIED）。

本项目关心的是另一个时点：**A 还活着、只是质量变差的时候，B 已经预建完毕**。因此判定依据不是"通/断"布尔量，而是滑动窗口里的劣化占比；切换动作之前多了一段 fill（预建/确认）过程。

## 3. 状态机

```
                 ┌──────────────────────────────────────┐
                 ▼                                      │
            STABLE_A ──A 窗口劣化占比≥ratio──► DEGRADED_A │
                 ▲                            │          │ A、B 同时劣化
                 │                            ▼          ▼
                 │                      PREBUILDING_B  BOTH_DEGRADED
                 │                            │        (共享瓶颈, 不切换)
                 │                     on_prebuild(桩)
                 │                            ▼
                 │                      B_HEALTHY_READY
                 │                            │ on_swap(桩), 启动冷却
                 │                            ▼
                 │                          SWAPPED ──► COOLDOWN(冷却期内禁止动作)
                 │                            │
                 │              B 窗口劣化占比≥ratio(冷却结束后判定)
                 │                            ▼
                 └────── 无动作 ◄──────── ROLLBACK(on_rollback 桩, 启动冷却)
```

判定优先级（`StateMachine.step`）：

1. `cooldown > 0`：计数递减，状态置 COOLDOWN，不做任何切换判断。
2. A 承载中，且 A、B 窗口劣化占比都 ≥ `degrade_ratio`：BOTH_DEGRADED，reason 为 `shared bottleneck suspected`。
3. A 承载中，A 劣化占比 ≥ `degrade_ratio` 且 B 健康（或没有 B 数据）：DEGRADED_A → PREBUILDING_B → B_HEALTHY_READY → SWAPPED 在一次 step 内走完，依次调 `on_prebuild`、`on_swap`，并启动冷却。
4. B 承载中，B 劣化占比 ≥ `degrade_ratio`：ROLLBACK，调 `on_rollback`，启动冷却。
5. 其余：STABLE_A。

## 4. 两个必须写清楚的实现决定

**(a) 预建链在一次 step 内完成是逻辑层的简化。** 真实实现里 fill（鉴权、测速、确认）一定跨越多个采样周期，`PREBUILDING_B` 与 `B_HEALTHY_READY` 会是停留态而不是过路态。骨架把它们压进一次 step，是为了让"决策顺序"可以被确定性测试，不代表真实时延（UNVERIFIED）。

**(b) 承载槽位 `on_b` 是独立标志，不等于当前状态。** COOLDOWN 是"暂时禁止动作"，不是"已经回切"。如果只用 `state == SWAPPED` 判断谁在承载：

- 场景5里，冷却把状态改成 COOLDOWN 后，回滚条件永远无法命中；同时 A 的旧劣化还会和 B 的新劣化一起命中 BOTH_DEGRADED，把回滚挤掉。
- 场景6里，冷却结束后 A 依旧劣化、B 依旧健康，会对同一个 B 再 swap 一次。

所以规则 2、3 只在 `on_b=False`（A 承载）时评估，规则 4 只在 `on_b=True`（B 承载）时评估。

**(c) B 完全无探测数据时仍允许切换，是骨架的刻意简化（UNVERIFIED）。** 真实实现应当要求 B 先被证明健康再交换；保留这个分支是为了让接口语义完整，而不是推荐这么做的策略。

## 5. 分层与边界

```
core/            纯逻辑：数据结构、窗口、状态机、动作接口桩
                 零 I/O、零平台调用、零时钟读取；时间戳由数据源传入
adapter/         平台适配层（只有 README，无代码）：路由 metric、代理分流、提权
demo.py/tests/   剧本驱动：喂数据、断言迁移，不接触系统
```

逻辑层不 import 任何网络/平台/子进程库，因此六场景可以在无网络、无权限的机器上重放；这也是本仓库目前唯一被真正验证过的部分。
