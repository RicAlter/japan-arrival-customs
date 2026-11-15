---
name: japan-arrival-matching-mvp
description: 处理日本到货基础匹配，或按已配置的补充模式查询材质和填采购图片。
---

# 日本到货基础匹配

只用部署时提供的Python、operate.py和runtime.json，不读取完整SOP、不自行编辑配置或数据库。

1. 处理本批：`<Python> -X utf8 -B <operate.py> --runtime <runtime.json> --action prepare`。
2. 查看结果：同一命令使用 `--action current`。
3. 中断续做：同一命令使用 `--action resume`；不要另建批次或改输出路径。

工具负责全部匹配、材质承接、字段来源和Excel生成。只交付`business_files`中的文件，并简报`summary`及需要处理的`issues`。`partial`表示可交付但有缺项，不等于失败；`failed`时按`error.code/message`报告，只有`retryable=true`才重试resume。来源变化、配置或行身份冲突交开发人员处理，不猜测商品、不修改文件补值。

本轮不放图片、不处理运营回传保存、不做完整计算或正式安装。收到回传时说明该能力尚未开发，保留文件交后续处理；不能声称已经保存。技术测试、Terra运行、运营验收及正式安装分别报告。

配置为enrich_review时，上段“不放图片”不适用：工具按实际采购清单补图、查询R网站材质，最后出表。仍只用prepare/current/resume，不自行写脚本或改规则。partial按next_action续做；requests由现有网页工具取真实原文，使用operate.py --action resume --responses <回传JSON>提交；不得编造网页、材质或成功状态。completed_with_gaps交付表和summary.pending_reason_file，说明空格原因。WPS实际核验和运营确认分别记录。
