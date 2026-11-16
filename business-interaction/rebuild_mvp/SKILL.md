---
name: japan-arrival-matching-mvp
description: 日本到货匹配、候选、材质/采购图片补充、版本化运营回传和有来源数量/价税/箱重和双模板草稿保存。
---

双模板保存：使用部署绑定的 dual_projection runtime，prepare/current/resume 只读承接 R2 保存文件及 R3 三个版本化结果。保存成功后交付两份 business_files、pair_source 和双表待核.csv；draft_with_gaps 不等于失败或正式可外发。不得从内部名字、日文名或未知材质推海关字段，不为补齐而改原表，不恢复暂停的图片下载，不将预览或技术测试称作真人认可。输入漂移另建新任务，不改旧绑定。R4-03 整批验收未开始。详情见 DUAL_PROJECTION_CONTRACT.md。

# 日常操作

使用开发部署提供的Python、operate.py及runtime.json，模型不临时改规则、配置或数据库。按任务配置执行prepare/current/resume，交付business_files中的文件，并说明summary、issues和状态。

匹配：prepare/current/resume包含配置启用的名称候选补查和版本化译名。候选不是已确认事实，不自动审批材质/税率。只在配置授权范围内处理。

图片补充：enrich_review新任务默认先在E列存唯一核对链接，统计缺链接与待嵌图；最后明确要求填图时，使用resume --finalize-pictures。已有图片和人工内容保留。材质R只补空，外部网页原文通过resume --responses提供，不编造成功状态或材质结论。

运营回传：使用部署绑定的review_return runtime，先current取得revision和reference_sha256。用户回传文件后，使用resume --submitted-file <文件> --expected-revision <版本> --expected-reference-sha256 <SHA>。需要明确清空时另带--clear-cells <单元格...>；普通空格不自动清空。校验合格范围由程序保存，异常只报告，不重复要求确认已提交内容。reviewed_source供后续任务承接。专业批准仍独立。

partial可以表示有待核字段；failed按error.code/message处理。来源、程序或版本冲突时保留现文件交开发核对，不能强改job摘要或把旧回传覆盖新结果。旧冻结任务用原程序继续，不直接套用新版本。

完整R3计算、最终双表、实际运营验收及正式安装仍待完成。用户停止本批补充时，不因旧任务存在而自动恢复查询或下载。本次文档同步不表示重跑了业务验证。

数量阶段：配置mode=quantity_conversion时沿用prepare/current/resume。程序校验已保存R2及来源、生成新副本和quantity_source；只交付business_files及待核说明。模型不判断单位、不编写包装倍率、不把partial当失败，也不自行覆盖旧值或启动R3-02。

价格金额与税金：使用部署绑定的 price_tax runtime，prepare/current/resume 承接 quantity_source，生成新副本、pricing_source、价格税金计算明细及待核清单。只补有可比依据的空白I，其他人工值和原始价格金额不改。税率缺失不补零，不让模型猜计价单位/税率。参考税金不是专业批准；partial按字段原因交付，不启动箱重或最终双表。

箱号重量：使用部署绑定的carton_weight runtime，prepare/current/resume承接quantity_source与pricing_source，交付business_files、logistics_source及箱货关联/箱重明细/待核CSV。程序仅在真实合并范围内承接箱号，按唯一实物箱计重，区间数量不均分、商品重量不分摊。副本保全所有原格，模型不改箱重或猜未知值。partial只限制对应结果，不自行改旧job、安装或生成最终双表。
