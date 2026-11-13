# P2-D1 独立申报归类决策库（0.6.0）

一个主Skill继续使用B2审核，不创建第二套人工确认系统。只从可信管理员登记的B2 Store读取已提交事件及四层快照；上传Excel/任意JSON不是导入授权。库必须放在Skill安装目录、批次目录和原始文件目录之外。不要把业务库放进安装ZIP，不在升级时删除库。

以下`<批次目录>`是已有B2 Store，`<知识目录>`须全新、独立。示例占位符不是可执行默认值，真实部署由可信管理员配置来源性质；合成来源必须使用synthetic，测试夹具必须明确使用authorized_test_fixture，不能登记为business。

```text
python scripts/run.py --output <批次目录> knowledge-init --library <知识目录> --source-kind business
python scripts/run.py --output <批次目录> knowledge-import --library <知识目录> --batch <批次ID>
python scripts/run.py --output <批次目录> knowledge-stats --library <知识目录> --as-of <YYYY-MM-DD>
python scripts/run.py --output <批次目录> knowledge-search --library <知识目录> --as-of <YYYY-MM-DD> --criteria <条件JSON>
python scripts/run.py --output <批次目录> knowledge-history --library <知识目录> --batch <批次ID> --decision <决策ID>
python scripts/run.py --output <批次目录> knowledge-check --library <知识目录>
python scripts/run.py --output <批次目录> knowledge-rebuild --library <知识目录>
python scripts/run.py --output <批次目录> knowledge-backup --library <知识目录> --backup <全新备份目录>
python scripts/run.py --output <批次目录> knowledge-restore --library <全新恢复目录> --backup <备份目录>
python scripts/run.py --output <批次目录> knowledge-upgrade --library <知识目录>
```

条件JSON示意：`{"product_type":"已明确类型","purpose":"已明确用途","complete_composition":"关键组成","construction":"关键构造"}`。支持字段还包括key_material_features；至少一个非空条件，不支持只按商品名猜归类。默认realm=formal，技术取证可显式`--realm test`或`--realm quarantine`。文本检索只返回案例，不授权采用；展示依据、范围、有效版本和缺证据原因，不能让AI据此自动生成税率或规则。

导入返回new_events/duplicate_events/journal_committed/index_status。若pending_rebuild，先保留权威提交，再执行rebuild或重试同批次，不重新审批、不把未建索引当作人工选择丢失。过期来源、事件分叉、同ID不同内容、损坏权威对象须停止相应导入并报告。索引坏可重建；事件归档坏须从完整校验备份恢复，不能使用索引冒充事实。

撤销通过原B2 `return-preview` operations中的`revoke_decision`、明确row_ids/reference/reason，再经原`return-commit`可信会话确认，沿用material职责。与退回一样失效对应材质/归类及税金批准；历史版本保留。重新批准须新版本及必要双域审核。不能直接修改库内JSON或SQLite来撤销/批准。

正式集只用完整、当前有效、可信人工双域审批的最终选择；官方/历史/AI推荐始终是独立参考。合成、未审草稿、自动执行、退回撤销和过期记录不进入正式集。完整授权技术夹具仅进入测试学习集。批量审批商品数和独立人工决定次数分开统计。

备份含权威事件/快照、提交链、元数据及哈希清单，不依赖索引。恢复到新目录并重建。可信管理员须保护库、Store和会话配置，禁止附件上传者写入；本地哈希链不是外部数字签名。权限配置轮换后无法核验旧证据时不得推定通过。WorkBuddy身份注入、原生触发、D1实机误批拒绝、实际显示/保存仍未在本阶段验证。

D1不发现/发布/执行跨JAN规则，不更改D05和价格/盒规/税率门禁。正式业务成果仍只有海关报关单和内部到货单。
