# SOP索引

本候选阶段提交新规则优先：business-interaction/workbuddy/japan-arrival-customs-trial/references/stage-submission.md；实际run.py调用interaction.submission.Service。基础/计算回传校验保存不再常规二次确认；日方价格角色和外发门禁不取消。

统一操作顺序：固定输入/显式资料库release → run.py prepare → 完整性检查 → 唯一20列核对表 → upload实际差异 → 明确确认保存 → 实际日方价格和计算审核 → 再次人工确认 → 受控双草稿。每一步保留原件、来源SHA及未知原因。

- business-interaction/workbuddy/japan-arrival-customs-trial/SKILL.md：宿主入口。
- 同目录 references/business-preparation-sop.md：11月9业务版第一阶段操作。
- references/repair-sop-20261109.md：订单价/匹配/白底修订。
- references/material-query-sop-v2.md：原V2材质多站SOP。
- references/material-review.md、linked-material-original.md：双来源及关联原文。
- references/large-return.md：大图回传。
- 本目录 BUSINESS_RULES.md：版本冲突时的已确认规则及对应回归。

发布前运行治理回归及 material provider发布检查；零有效材质业务问题必须随包声明。


原样计算表接入：business-interaction/workbuddy/japan-arrival-customs-trial/references/original-layout.md；实际入口run.py→interaction/original_view.py→submission.Service。开发复现步骤见START_HERE.md及repro/REPLAY.md。历史SOP保留，阶段回传即提交规则优先于旧常规二次确认说明。
# 第二阶段黄标复核补充

`stage2-calculation.md`新增2026-11-13明确授权的独立最终流程测试出口，实际链为run.py→submission.Service.stage2→test_final；旧正常确认与正式外发门禁不变。

`business-interaction/workbuddy/japan-arrival-customs-trial/references/stage2-calculation.md`：前版/SHA/身份固定、具体SKU盒规、原订单参考价及颜色处理；`tools/stage2_review.py`和`tools/bind_stage2.py`接入主流程，不重新prepare。
