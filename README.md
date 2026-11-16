<!-- R4-02-DUAL-PROJECTION-20261116 -->
2026-11-16 R4-02：统一 MVP mode=dual_projection 已实现承接 R2 reviewed_source 与 R3 quantity_source/pricing_source/logistics_source。内部两页24列表原字节保全，海关草稿按原认可33列版式另建，缺项标色并另存待核清单；历史模板只作版式，不作业务来源。逐行检查点和双文件联合回执保证可恢复、输入漂移拒绝、未完整保存不发布 pair_source。海关名/材质只接有实际表头与商品范围的许可来源，不回填内部名称或日文名；箱重只在唯一实体首次归属处计一次。技术范围/真实样本/运营认可分列，以本机最终冻结报告为准。下一任务 R4-03 真实整批验收未开始，R4 整体未完成；不更改正式安装/main，不恢复暂停的材质及图片补查。以下旧“最终双表未开发/下一R4-02”保留历史时点。 见[投影及保存契约](business-interaction/rebuild_mvp/DUAL_PROJECTION_CONTRACT.md)。
<!-- /R4-02-DUAL-PROJECTION-20261116 -->

# 日本到货与海关报单：重建开发候选

当前隔离开发分支：`codex/mvp-kmt20261101-20261114`。项目进度、旧代码适用范围和剩余工作见[同步审计](docs/PROJECT_AUDIT_20261116.md)，总体方案见[重建路线](docs/REBUILD_ROADMAP.md)。正式安装及main不随本分支推送切换。

新任务使用`business-interaction/run.py`，明确指定`workflow=rebuild_mvp_v1`。已实现基础匹配、版本化候选、材质/图片补充与运营回传技术闭环；R3-01数量与包装已接统一入口，R3-02价格金额与参考税金已接通 quantity_source，R3-03箱货关联和去重重量也已接通两份上游契约，下一开发任务R4-02。实际运营验收、R3整体验收和最终双表仍未完成，参考税金不等于专业关务批准。

- [生效业务SOP](business-interaction/rebuild_mvp/BUSINESS_FLOW.md)
- [统一接口说明](business-interaction/rebuild_mvp/CONTRACT.md)
- [模型操作说明](business-interaction/rebuild_mvp/SKILL.md)
- [材质与采购图片补充](business-interaction/rebuild_mvp/ENRICHMENT.md)

旧`interaction`、`rc*`及计算模块保留兼容历史session，不能把旧版列布局和审批流程套到新MVP。历史入口仅在明确使用相应旧绑定时采用。

本仓库提交源码、说明和脱敏测试；业务Excel、数据库、回传、图片、网页快照及私有凭证保存在本机，不进入发布包。部署按新输入另建profile与冻结runtime，旧任务继续原冻结版本。

- [R3-01数量契约及R3-02读取说明](business-interaction/rebuild_mvp/QUANTITY_CONTRACT.md)

- [R3-02价税契约及R3-03读取说明](business-interaction/rebuild_mvp/PRICE_TAX_CONTRACT.md)

- [R3-03箱重契约及R4读取说明](business-interaction/rebuild_mvp/LOGISTICS_CONTRACT.md)
