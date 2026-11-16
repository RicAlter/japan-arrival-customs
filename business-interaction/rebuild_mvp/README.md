# 当前说明（2026-11-16）

当前已支持统一候选及review_return技术回传。最新能力/限制见[BUSINESS_FLOW.md](BUSINESS_FLOW.md)、[SKILL.md](SKILL.md)和[项目同步审计](../../docs/PROJECT_AUDIT_20261116.md)。下方旧“未接统一入口/回传未开发”等条款仅保留历史范围。新MVP下一开发阶段为R3，不自动启动业务验证。

---

# 历史接口说明

# 基础资料匹配MVP

本次实跑复盘与后续定版依据见[FOUNDATION_REVIEW.md](../../FOUNDATION_REVIEW.md)。用户已明确确认表应先填候选：名称匹配、译名及多条记录可直接填入对应单元格，短注待选；已确认值保留。最终候选导出为`python -m rebuild_mvp.review_candidates --task ... --search ... --gaps ... --translations ... --output <新目录>`，使用固定查询/翻译资料及来源版本；目前尚未串入prepare/current/resume，不能声称基础prepare已经完成最终候选表。

**当前唯一业务流程见[BUSINESS_FLOW.md](BUSINESS_FLOW.md)。** 用户最新确认：主码→PCS→日文名→实际采购（不限制部门）→未找到再用日文名全表搜索《至今报单汇总》→用户判断。部门仅是来源背景，不影响可靠商品采用。主表命中四字段从同记录承接，主表渠道属于允许的实际业务来源；运营已核值优先保全。部分日文通用品名只列候选，不猜商品。以下早期范围记录遇冲突以此规则为准。

2026-11-14用户补充：已增加运营核对表的品类、盒规、是否盲盒等已有字段承接；补全表用于已查材质和参考文字。已填U/X只在同出荷行原数量一致时继承，不新增计算。有效运营YD可补缺，#N/A等错误值排除；YD未匹配原因输出到后台YD-reasons.json。旧表计算价/金额和渠道不回填原始事实；详细来源权限见CONTRACT.md与policy.json。本功能是已知业务资料承接，不是运营编辑Excel自动回传保存。

本模块对应长期R0/F01–F04、R1/F05的本批最小实现，不是第二套长期系统。当前只做来源受控的资料匹配、最小SQLite候选和固定24列/两页无图片Excel；回传保存、计算、税金、盒规推断和正式安装未实现。

## 调用

经现有 `business-interaction/run.py --request <JSON> --result-file <JSON>`，请求指定 `workflow: rebuild_mvp_v1`。

- prepare：batch_id、input_file、sources、layout_contract、output；来源由开发部署配置固定，不让日常模型临时决定。
- current/resume：task_root。current只查看，resume校验代码、输入、来源和规则版本后从已完成步骤继续。
- 简短模型入口 `operate.py --runtime <已绑定配置> --action prepare|current|resume`；业务不填写JSON。

协议、类型、字段及模块边界见CONTRACT.md；来源/匹配规则见policy.json。成功、带缺项交付和运行失败分别为completed、partial、failed；错误有固定code/message/retryable。模型不猜资料、不改程序配置、不写数据库。

商品基础资料主来源是业务整理的下单/至今报单汇总。其名称、规格、日元采购价和渠道均按用户确认的业务含义使用；开订及明确仅其派生数据排除。运营已核对内容按适用范围保全，商品及采购记录分区，原始批次行不可改写，采用字段逐项有证据。

## 校验

新模块回归：`python -X utf8 -B -m unittest discover -s rebuild_mvp/tests -v`（工作目录business-interaction）。

真实整批只读核验：`python -X utf8 -B tools/verify_matching_mvp.py --task <本批运行目录> --report <新报告>`。原文件及业务报告均留本地，不提交Git。

冻结使用既有tools/freeze_unified.py从干净提交生成新运行副本并还原旧依赖锁定字节，不改工作树冻结依赖。日常模型运行目录只放本Skill及绑定入口；不要求读完整开发SOP。强模型和Terra必须用同一冻结版本、来源和规则，比较逐行业务内容与证据；技术自测不等同运营认可或正式安装。
# 材质与采购图片统一补充（2026-11-15）

现有run.py入口新增mode=enrich_review，完整配置、恢复和外部网页回传说明见[ENRICHMENT.md](ENRICHMENT.md)。原匹配流程兼容。新模式最后填图，只补空R材质，保全原业务内容；实际WPS、Terra和业务验收以本机报告为准。

