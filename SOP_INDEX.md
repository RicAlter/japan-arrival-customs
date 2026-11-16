<!-- SOP-FOUNDATION-FREEZE-20261116 -->
# 当前统一SOP、底座与总体进度

规则版本arrival-sop-foundation/20261116.1。先读[有效SOP](docs/current/EFFECTIVE_SOP_20261116.md)、[九项底座与版本](docs/current/SOP_FOUNDATION_FREEZE_20261116.md)、[总体进度](docs/current/PROJECT_PROGRESS_CURRENT_20261116.md)、[待确认/待适配](docs/current/SOP_PENDING_CONFIRMATIONS_20261116.md)。

可执行源码仍为a178d1812716bd91b33d8733b1d9e0f4ff78e451，已采纳development仍d3c3196。R2/R3/R4双表技术链已有，整体验收未完成。最新U实际盒数/V显式单位、成本和海关件数分离、实际卸价及尾差策略已固化，程序未完成适配。此文档分支保留原执行代码/配置/测试；业务处理、重算、材质图片补查继续暂停，正式安装/main/旧任务不变。

## 以下保留历史说明及原接口

下文旧“当前/下一步/未实现”等按原版本范围理解，业务规则以以上统一SOP及待办为准；历史接口仅说明原实现，不代表最新规则已经进入程序。
<!-- /SOP-FOUNDATION-FREEZE-20261116 -->

<!-- R4-03-LOCAL-TRIAGE-20261116 -->
2026-11-16 R4-03本地归类：2551个原已保存品类/材质字段仅作来源参考接入新海关草稿，内部表及人工/公式/图片保全。74862条剩余提示精确重复0，完整关联8527个业务确认项+2暂停组；归并不等于解决。tools/triage_pair_acceptance.py只读承接父/子pair_source及整批验收报告，17专项测试覆盖作用域、依赖归并及原提示零丢失。材质/图片补查、新文件WPS及业务/专业认可未恢复或未发生，R4整体未完成。详见[归类契约及范围](docs/R4_03_TRIAGE.md)。下文旧阶段保留历史时点。
<!-- /R4-03-LOCAL-TRIAGE-20261116 -->

2026-11-16 R3-03：箱号、箱货关联及去重重量统一入口已实现，契约见[business-interaction/rebuild_mvp/LOGISTICS_CONTRACT.md](business-interaction/rebuild_mvp/LOGISTICS_CONTRACT.md)。承接原R3-01/R3-02版本，旧绑定和原数据保全。下一开发任务R4-02未启动；R3整体运营验收与最终双表仍未完成。下方旧状态按历史时点保留。

以下为此前阶段说明；与上述本次范围冲突的状态仅保留历史时点。

# 当前SOP索引（2026-11-16）

- [生效业务SOP](business-interaction/rebuild_mvp/BUSINESS_FLOW.md)：来源、匹配、候选、H显示、图片链接和回传。
- [重建路线](docs/REBUILD_ROADMAP.md)与[同步审计](docs/PROJECT_AUDIT_20261116.md)：阶段及旧代码范围。
- [轻量操作说明](business-interaction/rebuild_mvp/SKILL.md)：prepare/current/resume与回传参数。

---

# 历史SOP索引（冲突时不用作日常规则）

- [FOUNDATION_SNAPSHOT_20261115.md](FOUNDATION_SNAPSHOT_20261115.md)：当前成果、采购图片来源、网站材质范围、底座差距与项目进度；优先于下面已过期的当前状态描述。

# 当前SOP索引（2026-11-13）

- material_foundation/README.md（位于business-interaction）：2026-11-14按用户网站查询手册建立的新材质流程，统一run.py的material_query_v1；六站调度、错误重试、完整翻译、证据及只补空格写回，网页实测范围单列。

- [FOUNDATION_REVIEW.md](FOUNDATION_REVIEW.md)：本次实跑复盘、最新业务规则、确认表候选与短备注、已验证基座和下一轮收口范围。候选已填版优先按此口径，旧严格留空要求只保留历史范围。

2026-11-14本批匹配MVP使用business-interaction/rebuild_mvp/README.md、CONTRACT.md、policy.json及简短SKILL.md；按本机重建总览和已批准48小时范围执行。排除开订、无图片、固定24列两页；旧默认20列、全量网站和图片步骤不套用本次MVP。回传保存及计算不在本轮，旧session协议保留原范围。

已保存批次先读 START_HERE.md 和 CURRENT_STATUS.md，承接原第一阶段，不重新prepare。新阶段以回传即提交规则为准，不重复要求常规确认。旧SOP只在旧session适用。

- business-interaction/workbuddy/japan-arrival-customs-trial/references/stage-submission.md：校验、保存、异常、幂等及旧版拒绝。
- 同目录 stage2-calculation.md：固定SKU盒规、分箱、I倍数、26列结果、黄标复核和独立历史测试。
- 同目录 original-layout.md：既有21列来源和旧绑定适配。
- 同目录 business-preparation-sop.md：新批第一阶段唯一20列。
- 同目录 material-query-sop-v2.md、material-review.md、linked-material-original.md、large-return.md：材质来源及图片保全。
- BUSINESS_RULES.md：已确认业务口径；repro/BASELINE.md：能力边界及后续开发顺序。

run.py → submission.Service → CalculationView 为当前计算入口。历史测试为 test-final → presentation-preview，后者只改变版式，不做专业批准。正常第二阶段提交到B00/A04的桥接尚未完成，不能把它写成已交付流程。真实SOP/程序/用例/行证据对应表见stage2-calculation.md。
- 2026-11-15统一补充：business-interaction/rebuild_mvp/ENRICHMENT.md，prepare.mode=enrich_review；采购清单图片链接、材质查询及最后写表通过原run.py执行。旧默认无图匹配模式保持原范围。

