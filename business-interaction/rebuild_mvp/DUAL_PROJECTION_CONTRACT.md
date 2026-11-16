# R4-02 双模板投影与联合保存契约

版本 `arrival-dual-projection/1`，规则 `reviewed-r3-draft-pair/1`。在既有 `rebuild_mvp_v1` 中增加 `mode=dual_projection`，仍用 prepare/current/resume 和 operate.py 的 runtime/profile。只投影已经保存的版本化结果，不重算包装、价格税金或箱重，不修改旧任务和正式安装。

## 输入和绑定

prepare 必须提供 batch_id、review_task_root、reviewed_source、quantity_source、pricing_source、logistics_source、projection_binding、renderer、output。current/resume 只需 task_root。

```json
{
  "workflow":"rebuild_mvp_v1", "action":"prepare", "mode":"dual_projection",
  "batch_id":"与R2/R3相同",
  "review_task_root":"R2保存任务目录",
  "reviewed_source":{"path":"R2保存Excel","sha256":"文件SHA","role":"reviewed_basics","version":"operator-return-版本号"},
  "quantity_source":{"path":"数量契约JSON","sha256":"文件SHA","schema":"arrival-quantity/1","result_id":"结果ID","semantic_sha256":"语义SHA"},
  "pricing_source":{"path":"价税契约JSON","sha256":"文件SHA","schema":"arrival-price-tax/1","result_id":"结果ID","semantic_sha256":"语义SHA"},
  "logistics_source":{"path":"箱重契约JSON","sha256":"文件SHA","schema":"arrival-carton-weight/1","result_id":"结果ID","semantic_sha256":"语义SHA"},
  "projection_binding":"投影依据JSON",
  "renderer":{"node":"部署的Node","node_modules":"已提供的Artifact依赖目录"},
  "output":"新任务目录"
}
```

只读核对 R2 保存回执和版本、SHA、原始行身份，以及三个 R3 契约的相互引用、语义摘要、实际交付、来源与顺序。任一跨版本引用拒绝整项绑定；单行缺项只限制依赖字段。不能按 JAN 合并出荷行，不能调用旧任务入口触发重跑或强改旧摘要。Node 和 Artifact 包版本文件加入任务指纹；程序或输入变更时另建任务版本。

## 认可模板及用途许可

内部表采用用户最新选定的两张表、A–X 24 列布局，模板标识 `arrival-completion-24/20261114`，直接复制对应 R3-03 保存文件，**整个文件字节不变**。原数量、价格、金额、I、人工值、错误值、公式及缓存、图片、重量页、备注和行序均保全。旧内部 20 列版式不再决定当前列义。

海关表标识 `accepted-stage5-33/20261023`，来源为本机“第5步海关外发表_最终输出模板_版式验收通过_业务数据未验收.xlsx”，原 SHA `7915da95ef075e4477ebe8d89b14f32bfb07da86eb182c15a606dbee39178937`。当时仅认可版式，历史业务值未被认可。只提取 33 列表头、列宽、字体样式、合并、行高和主题；不复制历史数据、审批状态或旧工作簿部件。该原文件及旧内部模板不能改标为 reviewed_basics 绕回业务来源。

新海关页为“图片处理”，A–AG 保持原 33 列，冻结 A2；表头合并 T1:X1、AA1:AF1。追加已填合计和草稿说明，不增加业务列、隐藏页或技术列。海关模板没有商品图片列；原图完整保留在内部表，不擅增列。缺图及待嵌图状态仍在待核清单，不自动恢复下载或补查。

## 字段投影

| 海关列 | 允许输入及行为 |
|---|---|
| A/B/D | R3 明确箱号、对应行商品编码文本、原产地；箱号未确定留空待核 |
| E/F | R3-01 状态允许的整数盒数、总单个数；折合盒数不冒充实物整盒 |
| G/P | R3-02 明确 JPY/单个的取整单价、对应行金额；不重新除价格或推包装 |
| K | R3-01 明确的盲盒事实；不根据全 N 种推断 |
| C/H/I/J/L/M/N/O | 有适用范围和实际坐标的海关品名、品牌、对外品名、品类、标签、材质、尺寸、规格；缺许可留空 |
| Q/R/S | 唯一实物箱数量、明确原单箱重和去重箱重；只在首次归属行显示 |
| T:AG 其他栏 | 当前不推断尺寸/体积展示、标签等未许可信息，保留模板位置 |

G/F/P 必须同版本、单位明确、相互一致。新 P 公式为 `IF(AND(ISNUMBER(G2),ISNUMBER(F2)),G2*F2,"")`，按输出行调整引用。缺依赖不写公式；合法零保留。缓存须等于 R3 精确结果，并经 Artifact 实际重算核对。内部原 M 不改；原金额差、取整差单独保存，不调平。参考税金只留在 R3 契约及待核记录，不增加税金列或宣称专业批准。

精确数沿用约分分子/分母字符串。Excel 只接收可准确表示、无超精度的数；非终止小数、超精度值不舍入冒充确定值。

箱重按原行序给唯一实体建立首次归属。完整箱组总重只贡献一次；分到不同归属行时，只有原表明确单箱重才能按所属箱数展示，不能按总重÷箱数均摊。重复箱所在后行留空不重复计重，不代表缺箱。箱重属于物理箱，不分摊为商品净重。数量、金额、箱数、重量合计均带覆盖数和完整性，部分合计不能冒充全批。内部继承重量页与 R3 来源不同时保留原页并列差异，不静默替换。

## 海关字段依据

projection_binding 为 `arrival-projection-evidence/1`，必须绑定 batch_id、四个来源 SHA、internal_template、customs_template、template_sha256，并提供 sources、rows。

sources 只接受经审计的 reviewed_basics/business_summary（主表至多一个），保留路径、SHA、版本、用途；开订及明确派生、completed_reference 和版式参考原表不接受。rows 保存完整稳定行 scope、原表行坐标和 fields。每个字段包括 value、state、evidence、header_evidence、identity_evidence，核对实际值、同列真实表头及同记录编码/日文名身份；适用规格非空时也核对原规格。商品组或同码不替代完整范围。

海关品名必须来自明确海关/对外品名字段，不把内部 F、日文名、渠道、YD、HS 或候选名称当对外品名。材质不得仅因内部 O 已填就宣称专业认可。相同业务词可以成为合法公开值，但本轮保守过滤含内部专属整段名称、日文名、渠道和 YD 的自由文本，受影响字段待核。字段冲突或头义不明只阻断该字段。专业确认始终另存，不伪造批准。

## 保全、恢复及联合保存

按绑定、逐行投影、双文件导出、联合回执保存检查点。逐行指纹包括上下游、依据、权重归属和输出行。中断续算未完成部分；同输入重复调用返回相同结果，已经成功的文件校验后复用。输入/程序/输出漂移、检查点或回执篡改均拒绝混合续跑。已有不同文件不覆盖。

Artifact 只创建新的海关工作簿；原内部文件原字节复制。新海关包只含新数据和许可版式，核验表数、样式、表头、宽度、合并、冻结、数值和公式缓存；禁止内部隐藏信息、外链、宏、评论、旧绘图和嵌入部件。文本以 inlineStr 保存，公式状文本不执行；编码保留前导零及完整字符串。

只有两份 Excel 均通过保存检查后才生成 `pair-save-receipt.json` 的 committed=true 并发布 saved 状态。一个文件成功或孤立 JSON 不代表成对保存。response 的 business_files 仅在联合保存成功后返回。

后台产物：pair-results.json、双表待核.csv、pair-save-receipt.json，以及作者/校验记录。待核 CSV 包括内部缺项、缺图/待嵌图、海关缺字段、R3 继承异常和重量页差异；记录数可能重叠，不称为缺失行数。业务文件不塞入技术信息。

## R4-03 接口与验收边界

统一响应提供 pair_source：path/sha256/schema/semantic_sha256/result_id。`read_pair_source` 同时验证契约、已保存 job、完整联合回执、所有上游及来源、两份文件 SHA，供 R4-03 读取。JSON 含模板指纹、四个来源、稳定行与输出行映射、逐格状态、精确差额、去重依据、覆盖范围、异常、文件和保全证明。

输出状态 draft/draft_with_gaps，formal_output=false、professional_approved=false。技术实现、历史样本验证、实际运营认可、专业批准和正式安装分别登记。R4-03 真实整批验收另行执行，R4 整体未完成。Artifact 预览/重算不代替 WPS 显示验证；目前预览引擎把数字形文本渲染为科学计数法，实际值及 OOXML 文本类型已核对，WPS 尚未验证。
