<!-- SOP-FOUNDATION-FREEZE-20261116 -->
# 当前统一SOP、底座与总体进度

规则版本arrival-sop-foundation/20261116.1。先读[有效SOP](docs/current/EFFECTIVE_SOP_20261116.md)、[九项底座与版本](docs/current/SOP_FOUNDATION_FREEZE_20261116.md)、[总体进度](docs/current/PROJECT_PROGRESS_CURRENT_20261116.md)、[待确认/待适配](docs/current/SOP_PENDING_CONFIRMATIONS_20261116.md)。

可执行源码仍为a178d1812716bd91b33d8733b1d9e0f4ff78e451，已采纳development仍d3c3196。R2/R3/R4双表技术链已有，整体验收未完成。最新U实际盒数/V显式单位、成本和海关件数分离、实际卸价及尾差策略已固化，程序未完成适配。此文档分支保留原执行代码/配置/测试；业务处理、重算、材质图片补查继续暂停，正式安装/main/旧任务不变。

## 以下保留历史说明及原接口

下文旧“当前/下一步/未实现”等按原版本范围理解，业务规则以以上统一SOP及待办为准；历史接口仅说明原实现，不代表最新规则已经进入程序。
<!-- /SOP-FOUNDATION-FREEZE-20261116 -->

# 当前任务与未完成业务验收

本轮：统一已验证候选、原样21列适配、完整源码/Skill冻结、开发分支GitHub同步和新会话启动。实际测试结果见repro/verification.json；私有来源SHA索引见repro/inputs-index.json。

后续仍需业务处理：运营实际计算审核回传、52行单位关系及包装/盒规依据、税号税率税费、完整历史双表结果对照；100商品零有效网站材质的业务效果问题保留。没有获得正式安装或海关外发授权，不执行这两项。

原样视图中基础字段变化会要求宿主先调用既有基础资料链并重算绑定；此跨阶段自动接续尚未完成实际运营业务验收。不得静默沿用旧身份/价格，不把技术自回传当运营通过。
