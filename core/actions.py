"""动作层桩实现（stub）。

真实实现需接入平台路由 metric / 代理分流 / 权限提权，见 adapter/README.md。
本类不做任何系统调用，三个方法都只打印一行意图日志，UNVERIFIED。
"""


class Actions:
    def on_prebuild(self, node_b):
        print(f"WOULD prebuild B slot (auth+probe) for node={node_b} [UNVERIFIED stub]")

    def on_swap(self, node_b):
        print(f"WOULD swap default route to node={node_b} [UNVERIFIED stub]")

    def on_rollback(self, node_a):
        print(f"WOULD rollback default route to node={node_a} [UNVERIFIED stub]")
