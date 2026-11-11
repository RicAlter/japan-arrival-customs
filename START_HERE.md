# 当前开发入口（2026-11-11）

唯一集成开发分支：`codex/unified-repro-20261111`。这是开发候选，不是正式安装或业务放行。当前检出完整SHA由 `git rev-parse HEAD` 读取；版本、来源及未完成事项见 `repro/version-registry.json`。本机项目根的 `governance/version-registry.json` 保存本次发布的完整SHA与冻结包位置。

新会话顺序：AGENTS.md → 本文件 → CURRENT_STATUS.md → repro/version-registry.json → BUSINESS_RULES.md → SOP_INDEX.md → TEST_INDEX.md。运行 `python -B -X utf8 tools/check_candidate.py` 核对分支、Git状态、入口和依赖。没有本机业务来源时只做源码检查，不能声称重现真实业务。

执行入口：`business-interaction/run.py --config <独立session.json> --request <宿主请求.json>`。原样计算表通过session中的显式 `native_view_binding` 使用 `interaction/original_view.py`；没有绑定时沿用既有入口，不猜选KMT批次。运营不填写JSON。

冻结：`python -B -X utf8 tools/freeze_unified.py --output <新的冻结目录>`。只在新目录还原锁定依赖的精确字节，不改原仓库。源码清单与Skill包同目录；Skill包不含业务数据，也不会安装。封包 `skill/scripts/operate.py` 校验源码SHA后再运行。

真实回放：先取得本机登记的只读输入清单，逐一核验SHA，再在冻结副本中执行 `tools/replay_original_view.py --manifest <本机inputs.json> --output <新目录>`。复制已保存批次，复现1967行、21列原样I列试算和技术自回传；不重新prepare、不迁移原session、不等同运营提交。

原工作表已含K总单个数，所以本批继续21列；标准新批第一阶段仍唯一20列。I单个价试算、M原日方价、N原金额不能混用。52行单位关系、盒规/税费、实际运营计算回传和网站材质业务效果仍未验收；正式双表/外发不在本次整合范围。
