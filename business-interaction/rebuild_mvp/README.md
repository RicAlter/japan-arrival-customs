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

# 基础资料匹配MVP

本次实跑复盘与后续定版依据见[FOUNDATION_REVIEW.md](../../FOUNDATION_REVIEW.md)。用户已明确确认表应先填候选：名称匹配、译名及多条记录可直接填入对应单元格，短注待选；已确认值保留。最终候选导出为`python -m rebuild_mvp.review_candidates --task ... --search ... --gaps ... --translations ... --output <新目录>`，使用固定查询/翻译资料及来源版本；目前尚未串入prepare/current/resume，不能声称基础prepare已经完成最终候选表。

**当前唯一业务流程见[BUSINESS_FLOW.md](BUSINESS_FLOW.md)。** 用户最新确认：主码→PCS→日文名→实际采购（不限制部门）→未找到再用日文名全表搜索《至今报单汇总》→用户判断。部门仅是来源背景，不影响可靠商品采用。主表命中四字段从同记录承接，主表渠道属于允许的实际业务来源；运营已核值优先保全。部分日文通用品名只列候选，不猜商品。以下早期范围记录遇冲突以此规则为准。

2026-11-14用户补充：已增加运营核对表的品类、盒规、是否盲盒等已有字段承接；补全表用于已查材质和参考文字。已填U/X只在同出荷行原数量一致时继承，不新增计算。有效运营YD可补缺，#N/A等错误值排除；YD未匹配原因输出到后台YD-reasons.json。旧表计算价/金额和渠道不回填原始事实；详细来源权限见CONTRACT.md与policy.json。本功能是已知业务资料承接，不是运营编辑Excel自动回传保存。

本模块对应长期R0/F01–F04、R1/F05的本批最小实现，不是第二套长期系统。当前只做来源受控的资料匹配、最小SQLite候选和固定24列/两页无图片Excel；回传保存、计算、税金、盒规推断和正式安装未实现。

## 调用

经现有 `business-interaction/run.py --request <JSON> --result-file <JSON>`，请求指定 `workflow: rebuild_mvp_v1`。

- prepare：batch_id、input_file、sources、layout_contract、output；来源由开发部署配置固定，不让日常模型临时决定。
- current/resume：task_root。current只查看，resume校验代码、输入、来源和规则版本后从已完成步骤继续。
- 简短模型入口 `operate.py --runtime <已绑定配置> --action prepare|current|resume`；业务不填写JSON。

协议、类型、字段及模块边界见CONTRACT.md；来源/匹配规则见policy.json。成功、带缺项交付和运行失败分别为completed、partial、failed；错误有固定code/message/retryable。模型不猜资料、不改程序配置、不写数据库。

商品基础资料主来源是业务整理的下单/至今报单汇总。其名称、规格、日元采购价和渠道均按用户确认的业务含义使用；开订及明确仅其派生数据排除。运营已核对内容按适用范围保全，商品及采购记录分区，原始批次行不可改写，采用字段逐项有证据。

## 校验

新模块回归：`python -X utf8 -B -m unittest discover -s rebuild_mvp/tests -v`（工作目录business-interaction）。

真实整批只读核验：`python -X utf8 -B tools/verify_matching_mvp.py --task <本批运行目录> --report <新报告>`。原文件及业务报告均留本地，不提交Git。

冻结使用既有tools/freeze_unified.py从干净提交生成新运行副本并还原旧依赖锁定字节，不改工作树冻结依赖。日常模型运行目录只放本Skill及绑定入口；不要求读完整开发SOP。强模型和Terra必须用同一冻结版本、来源和规则，比较逐行业务内容与证据；技术自测不等同运营认可或正式安装。
# 材质与采购图片统一补充（2026-11-15）

现有run.py入口新增mode=enrich_review，完整配置、恢复和外部网页回传说明见[ENRICHMENT.md](ENRICHMENT.md)。原匹配流程兼容。新模式最后填图，只补空R材质，保全原业务内容；实际WPS、Terra和业务验收以本机报告为准。

