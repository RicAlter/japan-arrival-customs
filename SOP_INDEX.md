# 当前SOP索引（2026-11-13）

已保存批次先读 START_HERE.md 和 CURRENT_STATUS.md，承接原第一阶段，不重新prepare。新阶段以回传即提交规则为准，不重复要求常规确认。旧SOP只在旧session适用。

- business-interaction/workbuddy/japan-arrival-customs-trial/references/stage-submission.md：校验、保存、异常、幂等及旧版拒绝。
- 同目录 stage2-calculation.md：固定SKU盒规、分箱、I倍数、26列结果、黄标复核和独立历史测试。
- 同目录 original-layout.md：既有21列来源和旧绑定适配。
- 同目录 business-preparation-sop.md：新批第一阶段唯一20列。
- 同目录 material-query-sop-v2.md、material-review.md、linked-material-original.md、large-return.md：材质来源及图片保全。
- BUSINESS_RULES.md：已确认业务口径；repro/BASELINE.md：能力边界及后续开发顺序。

run.py → submission.Service → CalculationView 为当前计算入口。历史测试为 test-final → presentation-preview，后者只改变版式，不做专业批准。正常第二阶段提交到B00/A04的桥接尚未完成，不能把它写成已交付流程。真实SOP/程序/用例/行证据对应表见stage2-calculation.md。
