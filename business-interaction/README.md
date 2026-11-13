# 日本到货资料准备与分阶段交付

2026-11-09最终Codex候选：[业务版SOP](workbuddy/japan-arrival-customs-trial/references/business-preparation-sop.md)已绑定prepare实际会话。prepare/current交付前执行`interaction.delivery_review`，检查原事实/金额公式cache/箱重、逐行资料检索、E实际图片锚点与媒体、网站响应快照与身份绑定及缺项原因，并返回completeness。缺失与未执行有原因时可继续核对，但明确未全部补齐；原事实变化、缺执行记录、图片虚报或证据/SOP漂移则拒绝交付。`run.py --config <session> --request <delivery-review-request>`亦可只读审计已有表；请求action=delivery-review，output指定独立后台JSON路径。

图片默认下载，测试可显式image_max_downloads限定次数；禁用/预算耗尽/来源缺失/冲突/访问失败分别记录。双来源review仍只读；prepare把已验证的唯一逐行网站结果交既有R overlay及回传归一化链，不覆盖不同的已有R。非标准短码保留全行覆盖与原因，不作为已验证JAN发起网站查询。联网预算耗尽停止空转，既有403/429停站保留。

工作区候选从日本仓原始表开始。prepare归档原件、捕获资料库只读快照，按登记来源补齐中文名、规格、原单位采购参考价、渠道、YD、材质、盒规和采购链接图片，登记一份固定20列基础资料表。当前支持既有读取器已验证的kmt-raw-invoice-v1/v2连续商品行；其他布局明确拒绝，行数和批次名不固定。v2历史原表已存在的中文名、规格、人工品类/材质非空值保留，不从导入行为推定业务批准。

主JAN未命中时查询pcs jan code，保留单个码与盒装码的双向来源关系及冲突。关联盒价不填成单个价，人民币显示“元”且后台保留CNY，采购数量与到货数量分别保存。完整规格包括末尾来源采购数量。

固定列为A箱号/B产地/C JAN/D JC/E图片/F中文名/G规格/H采购参考价/I预留/J日文/K原数量/L日方价/M金额/N人工品类/O人工材质/P渠道/Q YD/R网站材质/S资料库及历史材质参考/T盒规文字参考。N/O不自动填写。S按明确标签、规格及有出处的历史规则整理，T保留每盒/每包等完整层级；不由价格比或规格尾数推盒规，不默认1。

prepare现在自动建立数据库与网站双来源核对；material-review为推荐查询入口。全部商品都保留同码数据库记录、字段版本/来源和YD原文，同时核验网站缓存并安排JAN→渠道→日文名查询，数据库命中和人工材质均不跳过网站范围。冲突并列保留，精确SKU依据不足时数据库只作参考。此阶段只读工作簿及原库，后台输出material-review.json、summary.json和全量网站队列。联网复用已验证的多站点提供器，专项渠道证据通过清单接入；实际范围与pending须如实显示。[请求与适用边界](workbuddy/japan-arrival-customs-trial/references/material-review.md)。

旧query-materials保留兼容Anime Store单站R装饰，不能作为多站全量查询已完成的依据。业务确认与原计算流程继续复用。

运行python -X utf8 -B run.py --request <request.json> --result-file <result.json>；除prepare外传--config <session.json>。业务无需编写JSON，候选宿主脚本workbuddy/japan-arrival-customs-trial/scripts/operate.py负责运行配置。详见[完整SOP](workbuddy/japan-arrival-customs-trial/references/preparation-sop.md)及[宿主请求合同](workbuddy/japan-arrival-customs-trial/references/request-contract.md)。

已有current/upload/confirm及基础资料1份→计算审核1份→双表草稿2份继续复用原服务。A03明确范围确认、原CAS和幂等、A04/B00、ROUND0及双表计算规则保持。人工包装参数明确确认后才用于换算，不自动填倍数或调平。公式地址按投影平移、原cache和箱重页签保全，图片原媒体及高清资源保留。

新prepare只建独立批次；已完成同批恢复状态、保留人工编辑，不替换现有KMT日常或展示指针，不迁移覆盖19格已保存人民币参考。历史19列/旧R品类说明仅描述旧登记版本，不能用于本候选新批。候选不安装到WorkBuddy、不改变正式外发权限；本机CLI验证、WorkBuddy原生验证及真人业务验证分别记录。

prepare另自动生成后台JAN数量核对，不新增业务Excel或列。采购只汇总有效订单行，保留重复导出、状态/版本冲突和砍单口径；历史只读取显式登记的独立到货来源，不把查不到当0。同JAN本批Qty独立求和，主JAN/pcs/SKU关联仅用于找候选，跨码/跨单位必须有已确认换算依据；共享采购观察不重复分配。采购或历史范围、单位不可靠时累计差额及剩余数为null；可比较范围内的部分到货标记后续待跟踪，不当错误。前台只附quantity_attention汇总及待到货信息，明细在后台jan-quantity-review.json。[数量来源合同](quantity-review.md)。现有批次显式更新quantity_review配置可仅刷新该后台报告，保留旧报告版本及原Excel/head/人工保存，不重登记。
