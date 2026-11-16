2026-11-16 R3-02数量承接后的价格/金额/参考税金已实现，详见[business-interaction/rebuild_mvp/PRICE_TAX_CONTRACT.md](business-interaction/rebuild_mvp/PRICE_TAX_CONTRACT.md)。新模式不改原始K/L/M、人工值或图片；下一任务R3-03未启动，R3整体未完成。旧安装、runtime和既有业务任务保持原绑定。

以下为此前阶段说明；与上述本次范围冲突的状态仅保留历史时点。

# 当前开发入口（2026-11-16）

先读[同步审计](docs/PROJECT_AUDIT_20261116.md)、[重建路线](docs/REBUILD_ROADMAP.md)与[生效SOP](business-interaction/rebuild_mvp/BUSINESS_FLOW.md)。当前MVP已实现统一候选、图片两阶段及运营回传技术闭环，下一开发阶段为R3。验证先保留待办，本批剩余补充停止。旧批次、旧冻结和已采纳基线分别登记，不自动迁移或安装。

---

# 历史启动说明（以下旧当前状态不作为新MVP选择依据）

2026-11-16用户已暂停测试。先读[开发进度与底座现状](DEVELOPMENT_STATUS_20261116.md)，本次仅更新文档和交接；后续业务查询、下载及测试等待用户明确恢复。下文旧授权和旧状态保留历史范围。

2026-11-15用户已批准两日接入方案并授权实施及真实验证。统一run.py新增rebuild_mvp_v1的mode=enrich_review，操作说明见business-interaction/rebuild_mvp/ENRICHMENT.md；旧匹配接口保持兼容。当前验收以本机enrichment-integration-20261115报告为准，WPS、Terra、运营及正式安装分别登记。

此前固化见[FOUNDATION_SNAPSHOT_20261115.md](FOUNDATION_SNAPSHOT_20261115.md)。旧停止指令已由本次实施授权在上述范围内替代，历史业务文件继续只读，outputs脚本不作为日常底座。

# 当前开发入口（2026-11-13）

2026-11-14真实批次处理已按用户要求结束于候选确认表。后续开发先读[FOUNDATION_REVIEW.md](FOUNDATION_REVIEW.md)：固定最新主表优先、采购不限部门、名称/译名候选直接填表和短备注规则。基础匹配和候选导出已验证，统一日常入口及运营回传尚未收口；不把历史严格留空规则继续用于确认表。

2026-11-14用户批准的当前优先任务是两日内基础资料匹配MVP。新流程经run.py的workflow=rebuild_mvp_v1接入，使用prepare/current/resume，说明见business-interaction/rebuild_mvp/README.md和本机治理根MVP_SPRINT.md。仅本批最小库、匹配与固定24列两页无图片核对表；回传保存、计算、最终双表和正式安装延期。以下旧批次入口保持原适用范围。日常模型只读简短Skill，开发会话仍遵循本文件与治理要求。

唯一集成开发分支：`codex/unified-repro-20261111`。本次只整理开发基线，正式Skill、main、数据库和既有session不变。先读 AGENTS.md → 本文件 → CURRENT_STATUS.md → repro/version-registry.json → BUSINESS_RULES.md → SOP_INDEX.md → TEST_INDEX.md，再读 repro/BASELINE.md。

运行 `python -X utf8 -B tools/check_candidate.py`。隔离任务分支需显式增加 `--governance-root <已有项目治理根> --task-id <已登记任务ID>`，由现有 startup 校验归属，不自动采纳版本。本机存在治理根时同时执行其 governance/check.py startup；不初始化新的治理系统。

业务入口：`business-interaction/run.py --config <独立session.json> --request <请求.json>`。原21列绑定 native_view_binding；新第二阶段绑定 calculation_view_binding。当前交付 results26：原A:U加盒数、取整金额、金额差、每盒税金、本行税金。I列为K/L倍数，原Qty、原价和金额不变。无绑定的旧session沿用旧行为。

承接已保存第一阶段，不重新prepare、不重复确认4302格授权。新批从原表开始仍默认20列；本批原有21列不能套用20列坐标。当前能力和未完成业务主链见 CURRENT_STATUS.md。

冻结：`python -X utf8 -B tools/freeze_unified.py --output <新目录>`，从干净Git HEAD取源码并在新副本恢复锁定字节。旧依赖锁不改。精确步骤及回归见 repro/REPLAY.md；本机治理登记完整SHA、来源和实际新报告，repro/verification.json只保留历史。
