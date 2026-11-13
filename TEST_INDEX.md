# 当前测试索引（2026-11-13）

旧repro/verification.json为ed0134d的287项历史证据，保持原版本，不替代当前提交验证。完整SHA、执行数、失败/未执行、来源和实际日志见本机新治理报告。

当前重跑范围：tools/regression_existing.py的units231、loop21、pack16，以及catalogue-pack-loop/tests/test_price_input.py的19项原价输入；business-interaction/tests中test_stage2_calculation44、test_confirmation_view12、test_yellow_review13、test_final_flow14；新增test_presentation7和tools/tests/test_baseline8。每项只计一次，跳过不算通过。治理50项单列。

真实证据：tools/replay_stage2.py、replay_yellow_review.py和replay_test_final.py保留已执行记录及适用版本；tools/replay_presentation.py从已封存测试状态另建目录，经实际run.py验证双表展示生成、全行/公式/cache/箱重、幂等、current及旧确认拒绝。这个回放复用已封存test-final输入，不宣称重新跑过完整正常B00/A04链。

盒规证据覆盖790/1010、125/759/834及73组146行分箱核验；全批1967唯一匹配、84修正、104148单个、50083400JPY原金额、216JPY取整差。缺规格、混合YD、冲突、非整盒、零/缺税率及上游变化失效均保留拒绝用例。

业务原件、真实价格来源、session、图片、网页证据只读本地留存；所有可写回放另建目录。技术自回传不是运营验收，历史100商品零有效材质和完整真实闭环继续未完成。
