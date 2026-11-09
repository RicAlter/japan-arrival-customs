# 全量网站 + 数据库双来源核对

新批 prepare 自动运行此阶段的数据库及缓存部分。已有业务状态使用 action=material-review，不重建session。宿主负责请求，业务无需填写JSON。

必填 output：本次独立后台目录。可从session取 prepared_file 和 database.path，也可明确 input_file、database。表头必须唯一，读取全部商品，不以 R/S/O 是否有值筛选。

可选 evidence_manifests：已审核候选/主查询state路径列表；每个候选必须有绑定行身份、原文、译文、网址及原始响应SHA。跨输入复用以JAN+日文名+规格+YD一致为条件，并逐行核验。HTTP200与业务成功状态分别看待。冲突原样保留，不自动以“更长文本”选材质。

默认 allow_online=false：从数据库只读快照读取同码全部记录、字段版本、来源及YD关联原文，同时核验已有网站证据，建立scope=all_products的队列。pending表示仍需网站查询，不能称全网查无。已有R/S是展示值，不能单独当新证据。

联网 allow_online=true 须 authorized=true、access_review 文件。当前复用工作区 tools/fast_material_batch.py 和 reports/material-plugin-20261106/vendor/jp_material_query，是本机依赖，尚非可搬移独立安装包。access_review含enabled_sites列表、正整数request_budget，并记录允许路径、站点访问检查和当前授权。stop_state_files可追加历史熔断状态；默认也读取已有主队列stop状态。每站沿用已验证限速，403/429停站、503停本轮请求。重启保留停站和成功证据。

自动站点标识：anime_store、colleize、amiami、jumpcs、amnibus。官方渠道名称检索的专项候选可通过evidence_manifests接入；Caravan/MOVIC/A3等专项采集目前不等于全部已通用自动化。队列next_step指明JAN→渠道→精确日文名。新批逐一完成专项队列或明确保留pending。

输出 material-review.json（每行library、website、comparison、binding）、full-website-queue.json及summary.json。后台保留数据库原文/全部字段版本和网站原文/译文/网址/快照，业务当前Excel仍是一份；R网站/S资料库展示的现有布局不移动，人工O保留。

comparison=same_text仅表示文本规范化后一致；needs_review包括不同语言、比例、组件粒度差异，并不直接认定错误。YD成分集合仍只作关联参考，不自动分配到具体SKU。输出 adopted=false、confirmed=0。需要写R或业务采用时分别走已有装饰/明确确认流程。

工作区验收：reports/dual-source-material-integration-20261109/。已用本批保存证据做全量回放；本次接入不代表重新联网查询全部商品、不代表WorkBuddy原生安装通过。
