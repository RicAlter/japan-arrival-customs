# 全量网站 + 数据库双来源核对

新批 prepare 自动运行此阶段的数据库及缓存部分。已有业务状态使用 action=material-review，不重建session。宿主负责请求，业务无需填写JSON。

必填 output：本次独立后台目录。可从session取 prepared_file 和 database.path，也可明确 input_file、database。表头必须唯一，读取全部商品，不以 R/S/O 是否有值筛选。

可选 evidence_manifests：已审核候选/主查询state路径列表；每个候选必须有绑定行身份、原文、译文、网址及原始响应SHA。跨输入复用以JAN+日文名+规格+YD一致为条件，并逐行核验。HTTP200与业务成功状态分别看待。冲突原样保留，不自动以“更长文本”选材质。

默认 allow_online=false：从数据库只读快照读取同码全部记录、字段版本、来源及YD关联原文，同时核验已有网站证据，建立scope=all_products的队列。pending表示仍需网站查询，不能称全网查无。已有R/S是展示值，不能单独当新证据。

联网 allow_online=true 须 authorized=true、access_review 文件。Skill内置已验证的 V2 多站提供器及其查询依赖；发布检查会校验提供器、五站列表和 V2.0 SOP 都在包内。access_review含enabled_sites列表、正整数request_budget，并记录站点访问检查和当前授权。stop_state_files可追加已批准的历史熔断状态；新隔离批不得隐式读取开发目录的旧状态。每站沿用已验证限速，403/429只停该站、503停该站本轮请求；其他已启用站继续处理。重启保留本批停站和成功证据。

联网范围默认是全队列；`online_rows` 可明确指定当前表中不重复的商品行号，用于授权的 100 商品范围测试。缓存核验→JAN 快速多站→渠道/官方站点→完整日文名回退→独立后备来源的顺序与 `references/material-query-sop-v2.md` 一致。当前通用自动站点是 anime_store、colleize、amiami、jumpcs、amnibus；MOVIC/Caravan/A3 等专项候选仍以已核验证据清单作为独立后备来源接入，未配置专项来源时保留 pending，不能伪称已查询。

自动站点标识：anime_store、colleize、amiami、jumpcs、amnibus。官方渠道名称检索的专项候选可通过evidence_manifests接入；Caravan/MOVIC/A3等专项采集目前不等于全部已通用自动化。队列next_step指明JAN→渠道→精确日文名。新批逐一完成专项队列或明确保留pending。

输出 material-review.json（每行library、website、comparison、binding）、full-website-queue.json及summary.json。后台保留数据库原文/全部字段版本和网站原文/译文/网址/快照，业务当前Excel仍是一份；R网站/S资料库展示的现有布局不移动，人工O保留。prepare 收尾时仅向空 S 写 `sku_exact` 或 `yd_collection_reference`，参考层级存 `material-reference-overlay.json`；仅向空 R 写完整身份与原始响应均合格的网站证据。

comparison=same_text仅表示文本规范化后一致；needs_review包括不同语言、比例、组件粒度差异，并不直接认定错误。YD成分集合仍只作关联参考，不自动分配到具体SKU。输出 adopted=false、confirmed=0。需要写R或业务采用时分别走已有装饰/明确确认流程。

工作区验收：reports/dual-source-material-integration-20261109/。已用本批保存证据做全量回放；本次接入不代表重新联网查询全部商品、不代表WorkBuddy原生安装通过。
