# 宿主请求合同

业务不填写JSON。运行工作区run.py --request request.json --result-file result.json；除prepare外须传--config session.json。operate.py从runtime.json读取入口和默认session；新批prepare不要求session。

## prepare

必填：action=prepare、input_file、batch_id、database、output。output为独立新目录；相同附件和批次再次调用恢复session，不覆盖人工编辑。

可选：sources来源映射列表、image_caches下载索引、history_rules有来源的历史参考、node、mode（business或synthetic）。来源须指定path、sheet、header_row及columns（字段→唯一表头或1基列号）。重复表头用明确列号。

字段：jan、pcs、sku、name、name_ja、spec、yd、channel、currency、price、actual_price、image、material、packaging、purchase_required/purchase_bought/purchase_current。订单总额来源price_scope=order_total。kind=registry用于保留完整名称、规格尾数和pcs关联。database为包含catalogue_entries/field_variants/record_links的商品资料库；不接任意旧SQLite。

返回session、business_files、补齐统计。后台website-queue.json包含全部商品，包括本地资料完整者。N/O人工栏不预填，R初始空，S/T参考。

## material-review（全量网站与数据库，推荐入口）

详见[双来源查询合同](material-review.md)。prepare后自动生成本阶段数据库/缓存核对；可传material_review对象配置已有证据和联网范围。已有批次使用此action及output新后台目录，input_file/database默认取session。全量取所有商品，同JAN下载可复用，每行独立核验；数据库命中及人工材质均不跳过网站队列。结果后台同时保留数据库完整记录、字段版本、来源与网站原文/译文/URL，冲突待核。默认离线证据回放，allow_online=true须绑定已授权访问范围和请求预算。原业务Excel与A03状态保持。

## query-materials（既有兼容入口）

必填action=query-materials、queue_sha256（全量website-queue.json摘要）、authorized=true、plugin源码目录。默认查全部行，可用rows具体行号列表分段。

离线传snapshots目录，使用插件真实HTML/JSON接口。联网须allow_online=true和access_review，包含robots、允许路径、请求预算和间隔。默认仅启用Anime Store，其他站不随插件默认配置自动查询。refresh=true可重查已有成功记录；默认复用同完整身份的已成功结果，失败可重试，站点熔断及预算仍生效。

每行记录JAN/名称/规格/YD/关联码及原文、中文、URL、时间。网站失败不阻断，身份改变或已有不同R值保留冲突。系统R装饰按已记录结果归一化后交原A03比较，不把网站结果当人工确认。查询期间Excel变化时保留证据、停止写入。

## 已有流程

- start/current：仅返回当前阶段business_files。
- upload：file、reference，可明确kind=basics/update/calculation；展示变更和具体拟确认范围。
- selection沿用save_changes、confirm_fields、adopt_candidates、evidence。采购采用须purchase_evidence真实来源和原计价单位；默认不确认材质，用户明确后confirm_material=true。
- update须用户明确实际价格版本；calculation提供真实price_basis_reference。重复身份links须有明确依据。
- confirm：confirmation_id、explicit_confirmation=true、reference，对应刚展示范围。原CAS、幂等、旧版本保护及正式外发关闭保持。

宿主负责命令和JSON；业务仅查看摘要、编辑和回传Excel、明确确认。
# 最终Codex候选补充（2026-11-09）

新prepare绑定references/business-preparation-sop.md的SHA，交付自动返回completeness。download_images默认true；image_max_downloads为可选非负整数，仅控制本次新下载次数，缓存复用不占次数。显式关闭/耗尽会记录为未执行，不称缺来源。material_review的联网授权、访问检查及停站合同继续有效；默认缓存未命中须报告未执行，不称全批已查。

action=delivery-review配合--config <session.json>可只读审计，output指定独立后台JSON；不重建业务状态，不新增Excel。准备会话的current/upload/confirm仍复用原session。冻结包runtime如包含source_manifest/source_root/source_manifest_sha256，operate.py在调用前逐文件验证源码及入口边界，漂移即停止。
