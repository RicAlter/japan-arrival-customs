# 非破坏性归档索引

旧源码、候选、SOP、验收与会话均保留原位。机器索引 governance-release/archive-index.json 登记路径/类别/恢复依赖；source-snapshots.json登记源码与SOP哈希。Git完整bundle保存所有可达历史，源码ZIP保存当前可运行字节。

这是一份原位只读归档目录，不移动、不删除业务资产；运行时仍引用的路径须继续保留。没有独立副本或依赖未核实的资产不做物理清理。恢复时先验证SHA再在新隔离路径解包，历史session用原runtime。

