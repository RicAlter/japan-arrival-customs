# 测试索引

最终流程测试出口：`test_final_flow.py`验证缺盒规参考计算、原数量/税基与ROUND0差额、缺税率留空、原件/缓存漂移拒绝、公开表内部信息排除、明确测试范围与独立配置、旧确认门禁不变和箱重公式/cache原文保全。`tools/replay_test_final.py`经run.py验证整批双表生成、保存回读、幂等、374箱及原session保全；该范围不替代B00/A04业务确认或完整真实业务验收。

第二阶段黄标复核：`business-interaction/tests/test_yellow_review.py`覆盖已接受商品名/YD/SKU与版本、类别、包装层数、原订单币种及重复报价、单位/状态冲突；`test_confirmation_view.py`覆盖仅H/U参考更新和清色保全。`tools/replay_yellow_review.py`从固定前版副本经实际run.py检查逐项结果、原数量/I倍数/金额和箱重保全，并保存缺依据清单。执行结果与完整候选SHA在本机项目治理登记，不视为运营放行。

本轮结果位于治理封包 governance-release/tests.json 与各stdout/stderr日志。覆盖第一阶段匹配、pcs/DG、材质分层、多站域名停站、大图回传、数量未知、标色、交付保全及既有计算/包装。

只读实样：KMT1002/1003/1101及各fixed-inputs，原件SHA；历史网站证据复核，不把缓存当联网。真人回传依据reports/workbuddy-native-phase1-20261109/user-native-acceptance-readback.json；不在旧业务session运行可写current/confirm。

100商品实际联网审计保留于outputs/KMT20261003_材质SOP恢复联网100_20261110_v3/后台/dual-source-material-review/。其零材质成功列为业务失败，不被单元测试通过抵消。


本次统一整合：tools/regression_existing.py复用既有202基础、21闭环、16包装、19价格适配和15阶段提交用例，并加入14项原样视图技术回归。真实1967行原样表独立复制回放另记，不将技术自回传计为运营批准。实际结果见repro/verification.json；日志/真实业务输入在本机只读证据目录。
