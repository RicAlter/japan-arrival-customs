---
name: japan-arrival-product-library
description: 维护与日本到货主Skill共享的本地商品基础资料SQLite；负责导入、去重、版本冲突与确认后基础资料回写，不处理申报归类。
---

# 日本到货商品资料维护 Skill

本 Skill 是商品资料库的**唯一写入入口**。它与 `japan-arrival-customs` 主 Skill 使用同一安装目录外 SQLite 文件；主 Skill 只绑定快照并查询预填，不执行资料库写入。

允许的操作：初始化资料库、导入已授权的开定／商品档案／历史 Excel、查看统计、按编码＋日文名／版本查询、应用主 Skill 生成且已确认的维护队列。重复文件或队列按哈希跳过。

不允许的操作：写入最终申报材质、税号、税率、D1 决策、D2 候选、D3 规则或盒规换算。采购订单标题不是中文名；版本文字不是已确认盒规；历史材质不是官方完整材质。

运行：`python scripts/run.py --library <安装目录外SQLite> <init|import|stats|lookup|apply-queue> ...`。

`apply-queue` 仅接受主 Skill 在明确确认基础资料后生成的 JSON 队列；先核对其中的 SQLite 路径与哈希，再写入。不要手改队列内容或把它当作专业审批。

