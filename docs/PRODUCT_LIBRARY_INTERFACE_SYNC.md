# 商品资料库与日本到货主 Skill 接口同步（rc.6）

日期：2026-10-23。此文件只定义集成边界，不扩展D1、D2或D3。

## 版本基准

| 位置 | 版本／状态 | 用途 |
|---|---|---|
| `integration-rc6` | `0.7.0-rc.6`，提交 `0282c8d…` 后的本地兼容修改 | 最新有效主流程；保留33列海关、20列内部和箱重页模板链路 |
| `workbuddy/japan-arrival-customs-0.7.0-rc.5` | `0.7.0-rc.5`，商品资料库研发分支 | 资料库规则参考，不覆盖主流程 |
| WorkBuddy 实际安装 | 未验证 | rc.6报告明确候选包未写入正式安装位置；不得声称已安装或验收 |

## 所有权与接口

两个独立 Skill 使用同一安装目录外 SQLite：

```text
商品维护 Skill  --唯一写入-->  shared product-library.sqlite3  <--只读查询--  日本到货主 Skill
                                      ↑
                       主Skill确认后的 product_maintenance_queue JSON
```

- 主Skill入参仍为 `product_library` 绝对路径；合同记录文件SHA-256并只读查询。
- 主Skill查询结果保持 `status`、`candidates`、`conflicts`、`matched_records`、`trusted_history_reused`、`automatic_approval=false`。它只预填基础字段，不写最终申报材质、盒规换算、税号税率或D1。
- 主Skill不再提供 `product-library-init/import`，也不在单人确认时直接写SQLite；它生成与本批、确认交易、SQLite路径及SHA绑定的维护队列。
- 商品维护Skill提供 `init`、`import`、`stats`、`lookup`、`apply-queue`。应用队列前必须验证SQLite路径和哈希；写入后以导入哈希去重并保留来源。
- SQLite变化后，旧主Skill合同的库SHA会失配；这是预期的可追溯性保护，下一批／重新准备合同后读取新快照。

## D1/D2/D3及未来关联预留

- 商品档案只保存 JAN/编码、中文名、日文名、品牌（来源可用时）、品类、YD、版本规格、包装文字、官方／历史材质来源和维护证据；不保存最终申报材质或归类审批。
- 未来品类、常见材质、最终申报材质与历史一致率应通过稳定的 `product_id`、版本键、来源行与D1决策事件关联计算；不得反向把统计或历史材质写入D1最终选择。
- D2候选发现、D3授权规则、跨JAN复用接口没有新增调用、字段或写入。

## 未完成

- WorkBuddy宿主尚未实测两个Skill同时安装、队列交接和SQLite快照重绑。
- 商品维护Skill当前依赖同一发布包中的主Skill资料库运行时；正式拆包时应把该运行时抽为版本化共享组件，并做兼容矩阵验证。
- 品牌的结构化来源、品类／材质一致率报表、最终申报材质与D1的只读关联均仅预留边界，未开发。
