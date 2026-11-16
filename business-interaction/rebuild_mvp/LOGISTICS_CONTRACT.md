# R3-03 箱号、箱货关联与重量契约

契约 `arrival-carton-weight/1`，规则 `carton-physical-weight/1`。统一 `rebuild_mvp_v1` 新增 `mode=carton_weight`，仍用 prepare/current/resume 和部署绑定的 operate.py runtime/profile。只读承接 R3-01 quantity_source、R3-02 pricing_source 与价税Excel；不重跑或改绑旧任务，不实现最终双表。

## 调用

```json
{
  "workflow":"rebuild_mvp_v1", "action":"prepare", "mode":"carton_weight",
  "batch_id":"与数量任务相同",
  "quantity_source":{"path":"数量结果","sha256":"文件SHA","schema":"arrival-quantity/1","result_id":"结果ID","semantic_sha256":"语义SHA"},
  "pricing_source":{"path":"价税结果","sha256":"文件SHA","schema":"arrival-price-tax/1","result_id":"结果ID","semantic_sha256":"语义SHA"},
  "logistics_binding":"已审计箱重依据JSON路径", "output":"新目录"
}
```

current/resume 只需 task_root。必须校验两份契约确实为同数量版本、同出荷行与原顺序，R3-02交付文件、原R2保存版本、旧job和来源SHA保持。数量或价格待核不妨碍独立箱号关联；不会据JAN合并出荷行。轻量模型不展开箱号、不分配数量或重量、不猜单位。

## 依据与字段

logistics_binding 为 `arrival-carton-weight-evidence/1`，包含：

- batch_id、quantity_source_sha256、pricing_source_sha256：显式绑定本批及上游版本。
- sources：只绑定一个已审计本批版本，含 source_id/path/sha256/role/version。仅 japanese_batch 或 reviewed_basics；禁止开订及其明确派生数据，不能从商品卡或历史商品资料取本批重量。
- sheet、header_row、detail_rows=[起行,末行]：按真实表头映射，不固定某工作表名或列位。columns 中每字段含 column 和实际 header 原文；列重复、表头不符拒绝。
- 必需字段 carton/count/total_weight；可选 unit_weight。weight_unit=KG/G，按原文单位换成精确KG。单位必须由实际表头说明；表头缺单位时用 weight_unit_evidence 的真实坐标提供说明。配置与原表单位冲突拒绝，不能把KG数值标成G。
- 可选 width/height/depth，必须同时声明 dimension_unit=CM/MM/M 并核对原始单位，表头缺单位时提供 dimension_unit_evidence。可选 volume 原格必须明确m³。体积为箱数×三边×单位比例³，保留原值和精确核对；“容积重量(M³)”不解释为计费重量，不引入6000等系数。
- summary_rows：实际主汇总行，不进入实物箱明细。核对原缓存及精确逐组和；若有公式，仅允许对明确明细范围的SUM。箱数、KG和m³各自核对，缺缓存或不一致不覆盖原值。
- note_rows：已定位的非数字备注，保留实际坐标和内容。数字、实体箱号或公式不得标成备注绕过检查。
- auxiliary_rows：例如主汇总下的重复箱数显示。每项含row、reason、references（如 `{"D":"C178"}`）；只允许实际公式直接引用已登记主汇总，原缓存须等于引用值，其他数字不允许隐藏。辅助D列未必仍是重量含义，不能按明细列位重复计重。
- coverage=partial/complete：明确商品行是部分抽样还是全批。部分样本的“关联箱重量”与完整重量清单总重分开；完整批次另列重量清单有箱无货、商品有箱无重量等差异。

所有实际读取格保存文件SHA、版本、表、行、列、原值、类型、公式及缓存。明细范围外未登记的数值或未知行列待核，不静默丢弃。原始单箱重、箱组总重、箱数及体积各自保存，互相不冒充。

## 箱号与关联

支持单箱、同前缀升序范围和明确分隔列表，例如 `ZA01`、`DA05-08`、`A1-A3,B1;B3～4`。全半角及大小写规范化，数字前导零只用于同前缀身份规范化，保留原文。空值、零、倒序、跨前缀、表达式、歧义分隔和重复箱号不猜；单标签展开上限10000箱。

商品箱号从上游原A格读取。空白只能在真实A列纵向合并范围内承接锚点，不无条件向下填充，不修改原格。原格/合并依据与数量契约scope不符只暂停该行。公式箱号不作为确定身份采用。

一个商品行可关联一个箱或一个箱集合。同箱多商品、同码多出荷行完整保留；范围内商品数量只标“位于此箱集合、未分配”，不把原Qty平均分到各箱，不从箱重反推盒规。数量与价格状态单独保留引用。

## 去重计重与异常

- 重量组的展开实体数须等于明确正整数箱数；原重量必须为正、有限数。缺失、零、负数、非数及缺缓存保留原值并待核，不补零。
- 原B单箱重若独立明确，核对B×箱数与原组总重。冲突不覆盖人工总重，相关重量结果暂停。原D公式仅接受实际明确乘积及独立数值前置格，不执行任意Excel公式。缺单箱重但有可靠手填组总重仍可采用完整箱组总重。
- 明细中箱号重复或范围重叠时，所有受影响箱组列冲突；不取第一条，也不擅自扣除重叠部分重量。无关箱组继续。
- 汇总按唯一实体箱集合计算。多商品共箱只计一次；完整所需箱组的总重只贡献一次。商品只用箱组的一部分时，只有原表明确的单箱重可按所需箱数计算；缺此依据不以总重÷箱数均分。
- 不把实物箱毛重分摊给商品，不生成“商品净重”。每行仅留箱号和箱组引用，不能将逐商品行箱组总重相加。来源清单总重、当前商品关联的去重重量及覆盖范围分别输出。
- 箱号、箱数、组重量、单箱观察、体积各有source_checked/derived/pending/conflict/not_requested状态。汇总带complete及覆盖数；部分合计不能冒充完整批次。

历史复用审计：参照 ffcfc05 中 arrival_core/_p0_frozen.py 的有界同前缀展开与 logistics.py 的实体并集、箱组总重核对。新实现补列表和严格失败、部分字段/行处理、合并单元格范围、显式来源与单位、辅助汇总区分及可恢复接口；不调用旧审批或最终出表流程。

## 输出与后续读取

响应返回 logistics_source：path/sha256/schema/semantic_sha256/result_id。JSON含规则和程序摘要、两份上游引用、交付SHA、原始依据、箱组、稳定出荷行与箱集合关系、汇总/覆盖范围、未分配标记和待核原因。精确重量、体积用约分的numerator/denominator字符串。

交付一份价税Excel的**字节相同新副本**，两张表、24列、行序、布局、全部原数据/人工值/公式/cache/备注/图片/重量表均不修改。本单元的核对结果在箱货关联.csv、箱重明细.csv、箱重待核.csv及后台JSON，不新增业务列或隐藏页，不生成最终双表。

任务按绑定、逐箱组、逐商品行和导出保存检查点；载荷与输入摘要不符拒绝复用。重复运行返回同一结果；来源、程序、上游版本或既有交付变化时保留旧成果，要求另建版本，禁止强改旧job摘要。

R4通过 read_logistics_source(logistics_source) 校验契约SHA、语义、当前上游与来源，按字段状态、scope/coverage及完整性读取。不得重新从列位、展示文字或商品行重量求和猜算。技术可用、运营认可、正式安装和最终外发分别登记；本轮不宣布R3整体或最终双表完成。
