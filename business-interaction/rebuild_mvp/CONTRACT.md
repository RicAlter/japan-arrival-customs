2026-11-16 R3-02：统一 prepare/current/resume 新增 mode=price_tax，承接 quantity_source，计算有来源的单个价、金额差及原价税基的参考税金。只补新副本空白 I；原价金额、人工值、数量、公式/cache、图片及重量表保全。契约见[PRICE_TAX_CONTRACT.md](PRICE_TAX_CONTRACT.md)。R3-01继续原绑定，下一任务R3-03未启动，R3整体未完成。

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
