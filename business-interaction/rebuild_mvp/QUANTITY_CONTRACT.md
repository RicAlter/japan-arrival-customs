# R3-01 数量与包装契约

生效：2026-11-16。仅数量换算，不计算价格、税金、箱重或最终双表。用户确认正常业务不存在同码不同包装；同码资料异常仅作防护场景，不构造真实正例。

## 统一调用

经原 `business-interaction/run.py`，`workflow=rebuild_mvp_v1`，操作仍为 `prepare/current/resume`。新冻结runtime/profile配置：

```json
{
  "mode": "quantity_conversion",
  "batch_id": "与R2相同的批次",
  "review_task_root": "已保存R2任务目录",
  "reviewed_source": {
    "path": "R2当前保存文件",
    "sha256": "文件SHA256",
    "role": "reviewed_basics",
    "version": "operator-return-1"
  },
  "quantity_binding": "已审计数量依据JSON路径",
  "output": "新的数量任务目录"
}
```

R2必须已有对应保存回执；prepare revision0不能冒充保存。只读读取旧R2的job/SQLite/文件，不调用旧程序改变其绑定。批次、版本、SHA、原始A/B/C/J/K/L/M和工作表结构均核对。原R1行身份可从经语义摘要核验的原匹配证据承接；缺失时以R2初始来源、工作表及行号建立稳定关联，不按JAN合并。

同一绑定重复调用复用结果。逐行SQLite检查点带内容摘要；中断后resume接续。来源、上游保存版本、代码或原行映射变化拒绝混合续跑；输出漂移拒绝覆盖。失败状态和原因保存，来源问题不能伪报完成。

## 数量依据输入

`quantity_binding` 使用 `arrival-quantity-evidence/1`：

- `sources[]`：每项含source_id、path、sha256、role、version。允许限定数量用途的日方原表、已保存/继承业务表、主表、实际采购/明细、商品资料及授权产品卡。来源排除、派生来源及已知禁止SHA复用现有检查。旧库仅追查原件，不作为无出处的换算来源。
- `rows[]`：sheet、row及scope。scope完整保存carton/origin/code/name/specification/ja/qty/yd，必须与本次R2行一致。重复或不符只影响该行。
- 每个evidence数组项含source_id、sheet、row、column、value；读取实际原格核对，不仅检查SHA。原始观察和审计结论分开；该配置由来源审计生成并冻结，不由轻量模型编造。
- `qty_unit`：unit、label、basis、evidence。unit为piece/pack/box/set/carton；保留原文标签与适用依据。不得仅据规格尾数、采购价格或箱号指定单位。
- `packaging[]`：原文子段excerpt、scope=`exact_sku`及evidence。程序仅解析明确的1/每包、1/每盒、整盒、1/每套、1/每运输箱包含关系；款式数、本体/配件和规格尾数不解析。
- 产品卡包装另需identity_evidence指向原商品名称格，限定去掉“模玩熊”前缀及“预定金/追定金/预金”尾缀后核对名称，保留版本和其他文字；按规格品种核对分段。混合商品通用盒规不得套角色单品，其他品种包装不采用。
- 可选 `v_unit` 指定本行V表示个/盒、个/包或个/套。只建立与piece连通且无冲突的关系；不能一律以X÷V计算U。
- 可选 `observations.total_pieces/box_count` 含value及evidence，须对应明确数值原格。与已有U/X不同则保留双方证据、列冲突，不替换原值。
- 可选 `blind` 含布尔value及evidence，原文须明确盲抽/非盲抽；“全N种”不作为盲抽依据。已有W保留来源。
- 可选 `allow_split_quantity` 必须伴随 `split_quantity_evidence`。否则非整数原Qty待核。

最小包装示例：

```json
{
  "packaging": [{
    "excerpt": "每包3枚，1盒12包",
    "scope": "exact_sku",
    "evidence": [{"source_id":"已登记ID","sheet":"原表","row":2,"column":"T","value":"每包3枚，1盒12包"}]
  }],
  "v_unit": "box"
}
```

## 数量输出与Excel

`quantity_source`返回path、sha256、schema=`arrival-quantity/1`、semantic_sha256和result_id。契约含程序/规则摘要、来源版本、R2保存版本、稳定行身份、原Qty单元格/公式缓存、既有U/V/W/X及其适用范围。

每行quantity分别保存原单位、已引用观察、其他独立观察、包装关系、推导结果、字段状态、待核原因和未采用候选。每个精确数用约分的字符串numerator/denominator表示。results按piece/pack/box/set/carton给出，field_states为inherited/derived/pending/conflict；仅前两种可供后续数量算术。关系source_checked仅表示来源检查，不代表专业或运营批准。

总单个数要求整数。盒数不足整盒时保留精确折合结果及whole_boxes/remaining_pieces，不舍入、不把折合当完整实物盒装。原数量无效、零或缺单位，分别列明；独立确认的数量观察仍可保留和复算。缺盒规不妨碍已有依据的单个数。

只向新Excel副本补空白U/V/W/X：U为无冲突整数盒数，V为有明确包装单位的整数包含数，W为明确盲抽标记，X为确定整数总单个数。原值、错误值、公式均不算空格。I/K/L/M、其他字段、公式缓存、样式、行序、图片、重量表和非目标ZIP部件保全；技术信息只放后台JSON及待核CSV。

## R3-02读取边界

使用 `read_quantity_source(quantity_source)` 校验契约SHA、语义摘要及当前上游/来源版本；用 `usable_quantity(row, unit)`读取可用的有单位数量。pending/conflict返回空，不能从Excel展示或其他候选补猜。

数量可用不代表原始计价单位、价格版本或税率可用。R3-02需另核对应关系，本模块不实现任何价格税金计算。旧正式安装、main、runtime和release数据库均不切换。
