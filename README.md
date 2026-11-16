# 日本到货与海关报单：重建开发候选

当前隔离开发分支：`codex/mvp-kmt20261101-20261114`。项目进度、旧代码适用范围和剩余工作见[同步审计](docs/PROJECT_AUDIT_20261116.md)，总体方案见[重建路线](docs/REBUILD_ROADMAP.md)。正式安装及main不随本分支推送切换。

新任务使用`business-interaction/run.py`，明确指定`workflow=rebuild_mvp_v1`。已实现基础匹配、版本化候选、材质/图片补充与运营回传技术闭环；R3-01数量与包装已接统一入口，R3-02价格金额与参考税金已接通 quantity_source，下一任务R3-03。实际运营验收、箱重和最终双表仍未完成，参考税金不等于专业关务批准。

- [生效业务SOP](business-interaction/rebuild_mvp/BUSINESS_FLOW.md)
- [统一接口说明](business-interaction/rebuild_mvp/CONTRACT.md)
- [模型操作说明](business-interaction/rebuild_mvp/SKILL.md)
- [材质与采购图片补充](business-interaction/rebuild_mvp/ENRICHMENT.md)

旧`interaction`、`rc*`及计算模块保留兼容历史session，不能把旧版列布局和审批流程套到新MVP。历史入口仅在明确使用相应旧绑定时采用。

本仓库提交源码、说明和脱敏测试；业务Excel、数据库、回传、图片、网页快照及私有凭证保存在本机，不进入发布包。部署按新输入另建profile与冻结runtime，旧任务继续原冻结版本。

- [R3-01数量契约及R3-02读取说明](business-interaction/rebuild_mvp/QUANTITY_CONTRACT.md)

- [R3-02价税契约及R3-03读取说明](business-interaction/rebuild_mvp/PRICE_TAX_CONTRACT.md)
