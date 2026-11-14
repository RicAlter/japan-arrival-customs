---
name: japan-arrival-matching-mvp
description: 处理当前日本到货批次的基础资料匹配，交付无图片核对表。
---

# 日本到货基础匹配

只用部署时提供的Python、operate.py和runtime.json，不读取完整SOP、不自行编辑配置或数据库。

1. 处理本批：`<Python> -X utf8 -B <operate.py> --runtime <runtime.json> --action prepare`。
2. 查看结果：同一命令使用 `--action current`。
3. 中断续做：同一命令使用 `--action resume`；不要另建批次或改输出路径。

工具负责全部匹配、材质承接、字段来源和Excel生成。只交付`business_files`中的文件，并简报`summary`及需要处理的`issues`。`partial`表示可交付但有缺项，不等于失败；`failed`时按`error.code/message`报告，只有`retryable=true`才重试resume。来源变化、配置或行身份冲突交开发人员处理，不猜测商品、不修改文件补值。

本轮不放图片、不处理运营回传保存、不做完整计算或正式安装。收到回传时说明该能力尚未开发，保留文件交后续处理；不能声称已经保存。技术测试、Terra运行、运营验收及正式安装分别报告。
