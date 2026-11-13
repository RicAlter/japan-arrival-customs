# 已确认业务规则与执行依据

2026-11-11用户调整：运营填写回传Excel即提交阶段结果，系统自动差异/完整性/规则校验并保存合格范围，只有实质冲突、关键依据缺失和失败项目需要处理。适用于基础表及计算审核。实际入口interaction/submission.py；旧service.py仅保留历史协议。专业归类与正式海关外发仍独立放行。KMT20261003的4302格历史待核输入获明确授权用于本次计算，隔离副本新增确认版本保留旧记录。

|规则|唯一有效实现/回归|
|---|---|
|适用有效采购订单价优先；777.4/777.39662同币同单位精度不误冲突|matching_repair.py / test_matching_repair.py|
|普通同JAN多YD、再次开订正常；特典/自编重复码须核商品规格订单|matching_repair.py / test_matching_repair.py|
|pcs与明确DG+JAN须核商品规格；盒价保留盒单位，CNY标元|pcs_enrichment.py、dg_enrichment.py / 对应测试|
|正常白底，需改缺项浅黄、实质冲突浅红|attention_display.py / test_attention_display.py|
|具体SKU材质优先，缺失允许YD集合供参考；不猜拆混合、不写O|material_reference.py、material_review.py / 两套材质测试|
|网站缓存核验→JAN→渠道官网→日文名→独立后备；403/429单站停|material_providers/fast_material_batch.py / test_material_provider_release.py|
|R须完整材质原文、身份、快照及来源；不覆盖已有R|material_review.py、website_query.py / test_material_review.py|
|原始数量金额公式cache箱重人工值和原图保全|delivery_review.py、large_return.py / 对应测试|
|采购数量独立汇总；未知单位/来源不得推累计差额|quantity_review.py / test_quantity_review.py|
|新阶段回传即提交，服务端校验保存；旧session协议原样保留|service.py / test_large_return.py、test_delivery.py|
|实际日方价、确认单位盒规、ROUND0及金额差额保持既有计算规则|business-loop、catalogue-pack-loop / test_loop.py、test_units.py|

统一SOP为此规则表加 SOP_INDEX.md 指向的既有操作细则；发生冲突先查版本证据，不用新文档反向覆盖历史人工确认。


2026-11-11统一候选：原21列表格适配通过run.py显式session.native_view_binding接入。K是整行总单个数，单个价试算=ROUND(原M单价/(K/原L数量),0)，只修改原I预留列；原M/N不覆盖。原表价格齐备与其他更新文件未匹配分开统计；参考历史的84行总数差异保留当前输入。基础字段回传变化先由宿主同步既有基础资料链，再重算，不静默沿用旧值。完整单位、盒规、税费及正式外发门禁不变。

## 2026-11-13当前口径（优先于历史I列说明）

新绑定results26的I列是倍数s/q，公式K/L，须对应空运原始表K；单个价u/(s/q)留后台，ROUND0金额差另列。原L数量、M价格、N金额和箱重保全；同款分箱按完整身份匹配，固定盒规逐行算盒数，不按JAN取首条，不强制取整。税金沿原价u基数，零税率有效、缺税率留空。

业务返回表即提交，校验后保存，不再常规二次确认。当前正常计算表到B00/A04主链仍未接通；test-final及presentation-preview只限显式历史测试配置，生成表不产生批准。当前21列来源的O品类、P人工材质、R为YD、S网站、T数据库、U盒规，与新批默认20列坐标分别处理。当前待补清单和统计见CURRENT_STATUS.md，不采用上文历史52行状态。
