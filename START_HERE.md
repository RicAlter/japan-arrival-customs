# 当前开发入口（2026-11-13）

唯一集成开发分支：`codex/unified-repro-20261111`。本次只整理开发基线，正式Skill、main、数据库和既有session不变。先读 AGENTS.md → 本文件 → CURRENT_STATUS.md → repro/version-registry.json → BUSINESS_RULES.md → SOP_INDEX.md → TEST_INDEX.md，再读 repro/BASELINE.md。

运行 `python -X utf8 -B tools/check_candidate.py`。隔离任务分支需显式增加 `--governance-root <已有项目治理根> --task-id <已登记任务ID>`，由现有 startup 校验归属，不自动采纳版本。本机存在治理根时同时执行其 governance/check.py startup；不初始化新的治理系统。

业务入口：`business-interaction/run.py --config <独立session.json> --request <请求.json>`。原21列绑定 native_view_binding；新第二阶段绑定 calculation_view_binding。当前交付 results26：原A:U加盒数、取整金额、金额差、每盒税金、本行税金。I列为K/L倍数，原Qty、原价和金额不变。无绑定的旧session沿用旧行为。

承接已保存第一阶段，不重新prepare、不重复确认4302格授权。新批从原表开始仍默认20列；本批原有21列不能套用20列坐标。当前能力和未完成业务主链见 CURRENT_STATUS.md。

冻结：`python -X utf8 -B tools/freeze_unified.py --output <新目录>`，从干净Git HEAD取源码并在新副本恢复锁定字节。旧依赖锁不改。精确步骤及回归见 repro/REPLAY.md；本机治理登记完整SHA、来源和实际新报告，repro/verification.json只保留历史。
