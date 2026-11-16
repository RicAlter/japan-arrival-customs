R3-02新增 rebuild_mvp/tests/test_pricing.py：精确算术、原价税基、金额与取整差、显式原价/商品身份/币种/报价单位/税率坐标、禁止来源、人工值/公式缓存/图片保全、重复/恢复/漂移拒绝及统一run.py。真实坐标样本与合成防护分别登记；完整MVP及共享保全受影响回归在新冻结版本执行，本机报告绑定完整提交SHA，不以旧测试替代。

2026-11-15固化审计：outputs/project-freeze-20261115/audit.json只读比对2861行、190个R空格补入、2657行带图、普通ZIP头及两页原值/公式缓存保全；不是网站六站、最终采购图WPS或运营验收。证据清单见同目录evidence-manifest.json。

# 当前测试索引（2026-11-13）

2026-11-14新增material_foundation/tests：手册规则、精确编码、完整成分和比例、六站顺序、403/429不误记查无、续查/回传幂等、磁盘人工值及原文件保护。当前运行报告在本机reports/material-foundation-20261114，合成/历史页与实时联网验证分别记录。

2026-11-14匹配MVP：business-interaction/rebuild_mvp/tests覆盖来源排除、PCS/日文名、采购币种/范围、材质承接、原始数据、事务和恢复；tools/verify_matching_mvp.py核验真实整批字段、来源、箱重及SQLite；实际执行结果以本机治理报告为准，不能把测试定义当已通过。新增run.py流程与旧批次回归分别验证；Terra实际运行、运营认可和正式安装分开记录。

旧repro/verification.json为ed0134d的287项历史证据，保持原版本，不替代当前提交验证。完整SHA、执行数、失败/未执行、来源和实际日志见本机新治理报告。

当前重跑范围：tools/regression_existing.py的units231、loop21、pack16，以及catalogue-pack-loop/tests/test_price_input.py的19项原价输入；business-interaction/tests中test_stage2_calculation44、test_confirmation_view12、test_yellow_review13、test_final_flow14；新增test_presentation7和tools/tests/test_baseline8。每项只计一次，跳过不算通过。治理50项单列。

真实证据：tools/replay_stage2.py、replay_yellow_review.py和replay_test_final.py保留已执行记录及适用版本；tools/replay_presentation.py从已封存测试状态另建目录，经实际run.py验证双表展示生成、全行/公式/cache/箱重、幂等、current及旧确认拒绝。这个回放复用已封存test-final输入，不宣称重新跑过完整正常B00/A04链。

盒规证据覆盖790/1010、125/759/834及73组146行分箱核验；全批1967唯一匹配、84修正、104148单个、50083400JPY原金额、216JPY取整差。缺规格、混合YD、冲突、非整盒、零/缺税率及上游变化失效均保留拒绝用例。

业务原件、真实价格来源、session、图片、网页证据只读本地留存；所有可写回放另建目录。技术自回传不是运营验收，历史100商品零有效材质和完整真实闭环继续未完成。
2026-11-15统一补充测试：business-interaction/rebuild_mvp/tests/test_enrichment.py覆盖来源排除、采购链接和YD约束、网页非图片、断点恢复、原值/公式缓存及箱重保全、普通ZIP图片封装和重复执行；真实批次、WPS和Terra证据单列，不由合成测试代替。

本次新增外部原文回传至R列的联调回归，核实人工O/S不被覆盖、重复回传不重复出表。匹配及统一补充126项、冻结工具8项通过。实际Git冻结514e2a6在2861行输入上补入101行采购图片（97个缓存文件），WPS关闭重开后的前中后段抽查可显示；图片锚点和原数据由程序逐项校验。网站限流及尚待外部取页仍为partial，不计为材质查无；目标Terra实测、六站完整在线验证及运营认可仍分别待验。本机详细证据outputs/enrichment-integration-20261115，不提交业务文件。

