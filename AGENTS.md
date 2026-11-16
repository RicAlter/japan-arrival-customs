<!-- SOP-FOUNDATION-FREEZE-20261116 -->
# 当前统一SOP、底座与总体进度

规则版本arrival-sop-foundation/20261116.1。先读[有效SOP](docs/current/EFFECTIVE_SOP_20261116.md)、[九项底座与版本](docs/current/SOP_FOUNDATION_FREEZE_20261116.md)、[总体进度](docs/current/PROJECT_PROGRESS_CURRENT_20261116.md)、[待确认/待适配](docs/current/SOP_PENDING_CONFIRMATIONS_20261116.md)。

可执行源码仍为a178d1812716bd91b33d8733b1d9e0f4ff78e451，已采纳development仍d3c3196。R2/R3/R4双表技术链已有，整体验收未完成。最新U实际盒数/V显式单位、成本和海关件数分离、实际卸价及尾差策略已固化，程序未完成适配。此文档分支保留原执行代码/配置/测试；业务处理、重算、材质图片补查继续暂停，正式安装/main/旧任务不变。

## 以下保留历史说明及原接口

下文旧“当前/下一步/未实现”等按原版本范围理解，业务规则以以上统一SOP及待办为准；历史接口仅说明原实现，不代表最新规则已经进入程序。
<!-- /SOP-FOUNDATION-FREEZE-20261116 -->

# 跨会话开发约束

先按 START_HERE.md 读取当前状态、版本登记、业务规则、SOP和测试索引，执行 tools/check_candidate.py。若本机存在项目治理根，继续其 governance/check.py startup；不要凭文件日期选择候选。

只在codex/隔离开发分支提交。当前唯一集成开发分支为codex/unified-repro-20261111。冻结055ef6f、98ce74e和旧候选完整保留，不改正式Skill、main、数据库release或既有业务session。新批运行/回放必须另建目录。

业务回传即提交，校验通过保存；不能因开发治理再要求常规二次确认。R/S参考不是O正式材质批准。原数量、金额、公式/cache、箱重及人工值保全。

每次集成同步版本/模块/来源/测试索引，保存真实执行证据及适用范围。跳过不算通过，技术自回传不算运营验收，网站历史零有效材质和完整真实闭环继续列为未完成。

源代码及脱敏测试/证据索引可推送开发分支；业务Excel、数据库、session、图片、网页证据和凭据留在只读本地来源。原样适配必须通过实际run.py配置接入，禁止依赖outputs目录中的临时源码。冻结工具从Git检出及锁定文本快照生成完整运行副本。
