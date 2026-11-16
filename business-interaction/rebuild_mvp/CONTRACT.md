<!-- SOP-FOUNDATION-FREEZE-20261116 -->
# 当前统一SOP、底座与总体进度

规则版本arrival-sop-foundation/20261116.1。先读[有效SOP](../../docs/current/EFFECTIVE_SOP_20261116.md)、[九项底座与版本](../../docs/current/SOP_FOUNDATION_FREEZE_20261116.md)、[总体进度](../../docs/current/PROJECT_PROGRESS_CURRENT_20261116.md)、[待确认/待适配](../../docs/current/SOP_PENDING_CONFIRMATIONS_20261116.md)。

可执行源码仍为a178d1812716bd91b33d8733b1d9e0f4ff78e451，已采纳development仍d3c3196。R2/R3/R4双表技术链已有，整体验收未完成。最新U实际盒数/V显式单位、成本和海关件数分离、实际卸价及尾差策略已固化，程序未完成适配。此文档分支保留原执行代码/配置/测试；业务处理、重算、材质图片补查继续暂停，正式安装/main/旧任务不变。

## 以下保留历史说明及原接口

下文旧“当前/下一步/未实现”等按原版本范围理解，业务规则以以上统一SOP及待办为准；历史接口仅说明原实现，不代表最新规则已经进入程序。
<!-- /SOP-FOUNDATION-FREEZE-20261116 -->

<!-- R4-03-LOCAL-TRIAGE-20261116 -->
2026-11-16 R4-03本地归类：2551个原已保存品类/材质字段仅作来源参考接入新海关草稿，内部表及人工/公式/图片保全。74862条剩余提示精确重复0，完整关联8527个业务确认项+2暂停组；归并不等于解决。tools/triage_pair_acceptance.py只读承接父/子pair_source及整批验收报告，17专项测试覆盖作用域、依赖归并及原提示零丢失。材质/图片补查、新文件WPS及业务/专业认可未恢复或未发生，R4整体未完成。详见[归类契约及范围](../../docs/R4_03_TRIAGE.md)。下文旧阶段保留历史时点。
<!-- /R4-03-LOCAL-TRIAGE-20261116 -->

<!-- CNY-DOWNSTREAM-VERSIONS-20261116 -->
2026-11-16最新：已保存的人民币成本reviewed_source已由统一入口生成2861行R3-01/02/03和R4-02新版本。整批技术验收通过，63个H修订及原数据/人工值/公式缓存/图片保全，8次current/resume一致；旧任务绑定保留。缺项继续待核，新文件WPS显示未执行，R3/R4整体与运营/专业批准仍未完成。运行仍绑定冻结4b48d0d，本次仅同步进度文档，不改程序、正式安装/main或数据库。详见[新版本说明](../../docs/CNY_DOWNSTREAM_VERSIONS.md)。以下旧阶段状态保留历史时点。
<!-- /CNY-DOWNSTREAM-VERSIONS-20261116 -->

<!-- CNY-COST-FEEDBACK-20261116 -->
## 人民币采购成本：数值去重后取最高

用户2026-11-16补充确认：本条仅适用于人民币采购成本。同一商品、同币种且同原计价单位的有效采购价先按精确数值去重，再取最高价；32元和32.0元是同价，35元/31元/31.0元取35元，121元/112元取121元。选价不随记录顺序、字符串大小或小数位数改变。原始报价、单位、渠道、坐标及未选记录留后台。

日元、美元等其他币种不执行取最高规则；不同币种、明确不同包装/计价单位继续待核，不换汇或推盒规。主表优先及有效来源许可不变，不拿采购候选覆盖主表或已有人工确认单价。价格按最高值选定不等于同时选定渠道、YD或数量；其余字段按各自出处处理。候选身份尚未确认的行不因价格选定就升级为确认商品。

对用户本次指出的既有H格人民币多价，可在新副本内按同一到货行原采购成本字段整理；仅调整H格文字，保留原始各项和前值，不改变I倍数、原数量、日方价格金额、公式缓存、图片或行序。此整理不建立任何新的物理包装单位或税率依据；旧R3/R4绑定结果保持原版。
<!-- /CNY-COST-FEEDBACK-20261116 -->

<!-- MATCHING-FEEDBACK-20261116 -->
## 业务反馈固化：YD名称查找与橙色多候选

2026-11-16，用户转交业务反馈并要求固化。完整商品名称对应的唯一YD，正常显示编码，不再附“按名称补”；这一查找路径本身不作为异常。实际查询词、匹配名称、记录坐标、来源版本与原始YD留在后台。已有业务文件/人工文字不批量清洗，旧冻结任务继续原绑定。

多个不同候选继续在对应字段逐条列出，保留橙色`#FCE4D6`并优先于普通缺项黄色；名称补查产生的多候选同样适用。业务认可这一显示便于对照到货数量，但颜色不计算、不合并出荷行、不改原数量金额，也不代表已经选定某个候选。相同值的重复出处合并显示，出处分条保留；不同YD、币种、渠道和规格不强行合并或任取第一条。

名称不明确、简称或泛称命中仍待核；多YD保留“待选”，不因取消方法后缀而自动确认为事实。译名及采购报价原有必要提示保留。本次是匹配/展示规则认可，不替代整批运营、材质、税率或正式安装认可。沿用最新版主表优先、缺项再补、采购不限部门、人工保护、来源排除和图片末置规则。
<!-- /MATCHING-FEEDBACK-20261116 -->

<!-- R4-03-REAL-BATCH-ACCEPTANCE-20261116 -->
2026-11-16 R4-03：新增只读pair_source验收工具，核对实际双表、R2/R3人工值/公式/缓存/图片保全、逐行金额和整批来源覆盖。当前新版链仅9行技术样本；1967行旧双表和另一2861行批次不冒充新版整批通过。WPS样本编码/公式显示及原图夹具重开显示已实测，图片对应关系和真人运营认可另列。真实整批验收仍待全量新版链，R4-03保持未完成，R4整体未完成。既有业务文件、正式安装/main不修改。表格核验优先代码，仅对用户明确要求的原生显示做最小界面抽查。以下旧“R4-03未启动”保留历史时点。 见[验收规则](../../docs/R4_03_ACCEPTANCE.md)。
<!-- /R4-03-REAL-BATCH-ACCEPTANCE-20261116 -->

<!-- R4-02-DUAL-PROJECTION-20261116 -->
2026-11-16 R4-02：统一 MVP mode=dual_projection 已实现承接 R2 reviewed_source 与 R3 quantity_source/pricing_source/logistics_source。内部两页24列表原字节保全，海关草稿按原认可33列版式另建，缺项标色并另存待核清单；历史模板只作版式，不作业务来源。逐行检查点和双文件联合回执保证可恢复、输入漂移拒绝、未完整保存不发布 pair_source。海关名/材质只接有实际表头与商品范围的许可来源，不回填内部名称或日文名；箱重只在唯一实体首次归属处计一次。技术范围/真实样本/运营认可分列，以本机最终冻结报告为准。下一任务 R4-03 真实整批验收未开始，R4 整体未完成；不更改正式安装/main，不恢复暂停的材质及图片补查。以下旧“最终双表未开发/下一R4-02”保留历史时点。 见[投影及保存契约](DUAL_PROJECTION_CONTRACT.md)。
<!-- /R4-02-DUAL-PROJECTION-20261116 -->

2026-11-16 R3-03：统一MVP mode=carton_weight承接quantity_source和pricing_source，提供有来源箱号范围、箱货集合关联和唯一实物箱去重重量。副本与上游价税Excel字节相同，全部人工值/原数据/图片/公式缓存保留；详情见[LOGISTICS_CONTRACT.md](LOGISTICS_CONTRACT.md)。R3三个计算单元已具备限定技术实现，运营认可及R3整体验收仍待办；下一开发任务R4-02未启动，本轮不生成最终双表。

# 当前说明（2026-11-16）

当前已支持统一候选及review_return技术回传。最新能力/限制见[BUSINESS_FLOW.md](BUSINESS_FLOW.md)、[SKILL.md](SKILL.md)和[项目同步审计](../../docs/PROJECT_AUDIT_20261116.md)。下方旧“未接统一入口/回传未开发”等条款仅保留历史范围。新MVP下一开发阶段为R3，不自动启动业务验证。

---

# 历史接口说明

# Matching MVP interface v1 (2026-11-14)

2026-11-15扩展：已授权材质与采购图片补充模式见ENRICHMENT.md。prepare.mode=enrich_review，current/resume自动分流；原匹配默认无图片的接口不变。新模式不依赖outputs源码，不新增业务列。旧无图片限制继续约束原匹配模式。

## Final review-draft contract from real batch

See ../../FOUNDATION_REVIEW.md. The user explicitly permits full-name matches, translations and multiple provisional choices inside the review workbook, with short notes. This supersedes historical instructions below that kept all uncertain candidates out of the workbook. Existing adopted values and raw shipment facts stay protected. Review candidates retain separate per-option evidence and confirmed=false, and never become confirmed SQLite facts automatically. The final candidate-export module exists; preparing its name-search/translation inputs and integrating it into the daily prepare/current/resume workflow remains unfinished.

## Current user correction: department-independent procurement and Japanese search

Latest user instruction supersedes all department gates below: actual matched procurement can supply missing product fields regardless of department or department absence. Department is provenance only. Unresolved products are searched by their Japanese titles across the audited main summaries, confirmed by user as the same 至今报单汇总. Full exact title matches are the Japanese-name branch; partial text hits are recorded as unadopted candidates with original cells, never guessed identities. Operator-confirmed values, latest-dated same-product reissue YD and benefit-without-YD exemption remain in force. Earlier department restrictions below describe historical runs only.

BUSINESS_FLOW.md + policy.json user_strict_v1 supersede conflicting early restrictions below. Main summary is an actual business-maintained purchase source: its product/specification/JPY quote/channel must be read by confirmed business meaning even with legacy headers 数量/金额. Primary code→PCS→Japanese-name→hand/Bandai department procurement→user judgment; user confirmed 模型部=万代部. No automatic catalogue/other-department bypass. Operator-reviewed applicable values are protected before automatic matching, including reference price/channel; uncertain currency stays explicit, never guessed. Public matching entry rejects any other flow instead of silently falling back.

## Latest user-approved enrichment (2026-11-14)

`reviewed_basics` is the supplied operator-reviewed partial workbook: category, O/R/S material, packaging reference, box size and blind flag may be inherited by exact code+Japanese-name SKU scope. Its valid YD may fill an empty/conflicting automatic YD only at the same carton/origin/original quantity. A different nonempty current YD is exposed as conflict, never overwritten. Excel errors such as #N/A are not IDs or material.

`completed_reference` is the user-specified completed workbook. Its R/S material/reference is preferred as requested; category/packaging/blind values supplement known blanks. Existing U/X counts may carry only for the same exact shipment row, explicitly as existing reference (no new calculation). Its calculated I/L/M, procurement price/channel and aggregated YD are not adopted. Operator O retains priority. Both original files and v4 MVP artifacts remain unchanged. This extends the earlier material-only scope on explicit user authorization; the old scope remains documented below for prior runs.

Operator-reviewed name/specification may also fill current blanks only at the same shipment row; existing rematched values are preserved. YD diagnostic row positions use the detected header, not a fixed source-row offset.

Single maintained module, called through `business-interaction/run.py`, request `workflow=rebuild_mvp_v1`. Actions prepare/current/resume only; no return, images or calculations.

## Data contract

All values from spreadsheets initially strings; original typed cells and formulas retained. JSON dictionaries with sorted deterministic processing. Paths private, business IDs derived from source hashes and source row identity. No model calls inside business code.

Batch row: `{row_id, source_row, sheet, raw:{carton,origin,code,ja,qty,jpy_price,amount}, raw_cells:{field:{column,value,type,formula?}}, values:{jc,name,specification,purchase_price,category,material,channel,yd,website_material,material_reference,pack_reference,box_count,box_size,blind,total_pieces}, evidence:{field:[ref]}, issues:[{code,field,message,candidates?}]}`. `row_id=sha256(source_sha+sheet+source_row)` (full or prefix >=24). Original raw fields immutable. Values not adopted are absent or empty. A ref contains source_id/source_sha256, role, sheet, row, column, value; purchase price ref also currency and unit (unknown is explicit, not inferred). Material inherit O/R/S only, separate.

Source config `{path,role,sha256?,version?,field_map?}` roles `business_summary,purchase_list,order_detail,purchase_order,product_catalog,daily_material,product_card,prior_material`. Opening role/name/known lineage rejected before parsing. New raw source is separate. Product card known snapshot revision115, not online122 content. Config optional field_map maps canonical field to exact header or column; duplicate ambiguities cannot silently pick first.

Record: `{source_id,source_sha256,role,sheet,row,fields:{code,pcs,name,ja,specification,yd,sku,category,material,channel,price,actual_price,currency,unit,status,department,order_id,quote_id,date,...},columns:{canonical:letter}, scope:{...}}`; fields may be strings or list of explicit PCS codes. Original record/columns retained. Allowed observations filter by role. Every record in minimal candidate is batch-relevant (codes/ja then connected YD/SKU), no full library migration.

## Ownership / interfaces

`xlsxio.py` (workbook agent): `read_book(path)->{path,sha256,sheets:[{name,path,rows:[{row,values,types,formulas}],merges}]}`; `iter_rows(path,sheet_name=None)` streaming same row dict; `sheet_info(path)->list[{name,path}]`; `extract_batch(path)->{source:{path,sha256,role},rows:[batchrow],sheet,weight_sheet,metadata}`. Header recognition dynamic and ambiguity explicit. Preserve carton per exact merges. `write_book(raw_source,output,rows,layout_contract,manifest)->dict` exports fixed24 columns 2sheets no pictures, source weight XML byte-exact with original dependencies. Formula/cache preservation deliberate remap. Use artifact-tool authoring for new main sheet, lossless native XML packaging where needed. Source raw extra fields retained backend. No overwrite inputs/output. Include backend manifest ZIP custom part without business columns. Export result at least file/sha256/rows.

`sources.py` and `matching.py` (matching agent): `collect_sources(config:list, batch:dict, progress=None)->{sources:[metadata],records:[record],audit:dict}`; progress optional callback(dict), safe if omitted. `match_batch(batch, collected, policy=None)->list[batchrow]` pure deterministic no writes; same full order/row IDs. Policy checked-in config. Business summary code -> PCS -> Japanese-name; fill only reliable same-scope values. Procurement channel actual sources only, unit/currency known before price adopted, actual quote vs declared quote not silently collapsed. Name branch CNY per approved SOP. No amount/qty division. No fuzzy adoption. `issues` field-local. Prior O/R/S carry with code+JP exact and SKU/version protection; other old columns must not leak. Source summary material goes reference S unless prior O confirmed by supplied batch. Unknown leaves blank. No novel material classifications.

`storage.py`, `service.py`, run.py adapter (integrator): SQLite separate sources, product_records, procurement_records, batch_rows, adopted_fields, issues, jobs/checkpoints. Immutable observations; small current-batch only. Prepare records snapshot config/hashes, extraction, collection, matching, export steps atomically checkpointed. Resume validates frozen inputs/code/config, reuses finished stages. Current reads status/delivery, no source rescan. Identical request idempotent. Candidate owns outputs new run dir. Output envelope `{schema,task_id,batch_id,status,step,versions,business_files,summary,issues,error,next_action}`. Stable error codes INPUT_INVALID, CONFIG_INVALID, SOURCE_FORBIDDEN, FIELD_MAPPING_AMBIGUOUS, SOURCE_CHANGED, TASK_CONFLICT, RUNTIME_FAILURE; exception issue != total failure. No automatic installation or pointer updates.

## Fixed columns A:X

CartonNo.; Origin; ProductCode(JANCode); JC; 商品图片; 商品名称; 规格; 采购单价（原计价单位）; 倍数（采购价÷批发价）; DescriptionofGoods; Qty; 卸价（日本JPY）; 批发金额（日本JPY）; 品类; 材质; 渠道; YD; 网站查找材质; 材质参考; 盒规原文参考（人工判断）; 盒装数; 盒规; 是否盲盒; 总单个数（数量依据）.

Raw day price and amount appear L/M as original values for this matching draft, not calculated new values; no I/new packing/count formulas. Original formula/cache preserved by coordinate mapping. Source weight sheet and total rows preserved, with cross-sheet references remapped if necessary and cache exact. Traces/issues backend only, sparse highlighting permitted, no added business columns/sheets. Body row height from selected layout, no image-driven huge rows.
