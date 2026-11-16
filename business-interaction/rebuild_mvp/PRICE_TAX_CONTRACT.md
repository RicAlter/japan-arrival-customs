# R3-02 价格、金额与参考税金契约

契约 `arrival-price-tax/1`，规则 `original-unit-price-reference-tax/1`。承接 R3-01 的 `arrival-quantity/1`，沿用 `rebuild_mvp_v1` 的 prepare/current/resume。轻量模型只调用已绑定的 runtime，不判断计价单位、税率或来源。此单元不实现箱重、最终双表、汇率换算或正式申报税额。

## 调用和绑定

```json
{
  "workflow": "rebuild_mvp_v1",
  "action": "prepare",
  "mode": "price_tax",
  "batch_id": "与数量任务相同",
  "quantity_source": {
    "path": "数量契约路径", "sha256": "文件SHA256",
    "schema": "arrival-quantity/1", "semantic_sha256": "语义摘要",
    "result_id": "结果标识"
  },
  "pricing_binding": "已审计价格及税率依据JSON",
  "output": "新的输出目录"
}
```

current/resume 仅需 task_root。部署入口仍为 operate.py --runtime <绑定文件> --action prepare|current|resume。原 R2/R3-01 任务只读；校验数量契约、交付 Excel、原来源、保存版本和原行身份，不调用旧任务入口改绑。输出从 R3-01 交付副本生成，保留已补数量字段。

任务绑定程序摘要、quantity_source、交付 SHA 和所有价格依据。逐行 SQLite 检查点校验输入与载荷摘要；中断后继续未完成部分。同一任务重复调用返回既有结果。程序、来源或上游版本变化时拒绝混合续跑，另建新版本；已有结果发生漂移时拒绝覆盖。

## 价格及税率依据

pricing_binding 为 `arrival-price-tax-evidence/1`，包含 quantity_source_sha256、sources[]、rows[]。sources 每项含 source_id/path/sha256/role/version，读取实际文件及坐标；沿用禁止开订、其明确派生值及已知禁止 SHA 的来源限制。

每行含 sheet、row 和完整 scope：carton/origin/code/name/specification/ja/qty/yd，须与数量契约一致。重复行和身份冲突仅暂停该行。该文件由来源审计生成、冻结，不让日常模型临时编造。

- invoice_evidence 必须声明 basis=preserved_japanese_original，分别提供 quantity/price/amount 的证据数组，逐项核对当前 K/L/M 保存值；只允许 japanese_batch/reviewed_basics 中明确保留的日方原始事实。旧完成表的计算价、商品官方售价及采购报价不能作日方原价。表头相同不足以证明字段语义。缺金额可独立暂停金额差，不能影响已有可靠原价的单个价计算。
- invoice_evidence.currency=JPY，currency_evidence 指向同记录币种格或同单价列的明确币种表头。其他币种/缺币种不标作 JPY，不调用汇率。
- 原价、采购报价都需 identity_evidence：证据含 field=code/name/ja/specification/yd，读取实际原格核对 scope；每个价格源记录至少提供同一来源、工作表、行的 code/name/ja 身份坐标。完整 SKU、版本、规格适用范围仍由审计映射保存，同码不是跨行覆盖依据。
- purchase_quote 可选：value/currency/unit/unit_basis、evidence、currency_evidence、unit_evidence 和 identity_evidence。仅 business_summary/purchase_list/order_detail/reviewed_basics 允许；主表优先和补缺规则沿用上游已审计匹配。采购清单/明细另需 record_state=effective 及实际 status_evidence，取消/作废记录排除。报价、单位和币种须同原记录，币种可取同单价列明确表头；不得借其他报价行币种。单位为 piece/pack/box/set/carton，须有对应原文。H 展示值须与已审计采购报价一致。
- duty_rate/vat_rate 各自含 value/evidence；允许 tax_reference/japanese_batch/reviewed_basics。value 支持明确小数或百分数，范围 0–1，零是有效值，缺失不是零。历史原公式中的税率可用 basis=formula_multiplier，附 formula 原文；仅接受实际公式末尾明确常数乘数，不能从已算税额反推税率。
- 所有证据包含 source_id、sheet、row、column、value，identity_evidence 另含 field。程序核对实际原格、SHA 及版本。依据不符进入待核/未采用候选，不能伪报完整成功。

## 算术及状态

令 q=日方原 Qty，u=原日元计价单位价，a=原金额，s=可用总单个数，b=可用折合盒数，r/v=明确给定的关税/增值税参考率。

| 结果 | 算式与边界 |
|---|---|
| 单个价 | u/(s/q)，只读取数量契约中 inherited/derived 且单位明确的结果；对应原单位数量必须等于 q |
| 整数展示价 | ROUND_HALF_AWAY_FROM_ZERO(单个价,0)，保留精确原值 |
| 原金额核对 | a−q×u；冲突保留原值及差额，不调平 |
| 取整金额/差 | ROUND0(单个价)×s；分别记录与 q×u、a 的差 |
| I采购价比值 | 同币种 JPY、相同原计价单位、H值一致时采购价/u；精确比值另存，I沿选定模板显示 ROUND0；价格比不参与包装判断 |
| 每原Qty关税/增值税 | u×r；u×(1+r)×v，始终以未取整原价为基数 |
| 行参考税金 | 上述两项之和×q；缺任何必要税率时不生成合计 |
| 盒参考税金 | 行参考税金/b；盒数不可用则暂停本项；只有参考盒数时另标 tax_per_reference_box_only，不反向批准盒规 |

所有精确值用约分后的 numerator/denominator 字符串。无价格、税率或物理数量依据时只暂停依赖字段。税金 reference 状态仅表示所提供历史参考口径的算术；不表示现行法定税率、专业关务批准、运营认可或正式安装。

1010 历史行：q=60、u=202、s=180、b=5，单个价202/3、整数价67，取整差−60JPY；给定 r=0、v=13% 时每盒315.12JPY。不能换成按67计算的313.56JPY。

## 交付与保全

统一响应增加 pricing_source，含 path/sha256/schema/semantic_sha256/result_id。JSON 保存规则与程序摘要、quantity_source、来源、原始证据/公式、行身份、继承 H/I/K/L/M/U/V/W/X、逐项精确结果、状态、算式、待核及未采用候选。汇总仅相加有币种的行金额，附 covered_rows/total_rows/complete；不相加单位税或每盒税充当整票税。

新 Excel 仍两张表、24列、原布局：仅补有完整可比采购依据的空白 I，已有数字、错误值和公式均保留；H/K/L/M/U/V/W/X 不改。逐个 ZIP 部件保全，非目标单元格、公式/cache、图片和重量表不改。技术状态不增加业务列/隐藏页。另交价格税金计算明细 CSV（精确分数、币种/单位、取整差和参考税金）及价格税金待核 CSV。

后续 R3-03 只通过 read_pricing_source(pricing_source) 校验 SHA、语义、逐行汇总及上游后读取，结合 field_states/per_unit/currency 和覆盖范围；reference 不代表批准，conflict/pending 不得当可用事实，不能从 Excel 列位重新猜算。R3-03 本轮未实现，R3 整体未完成。
