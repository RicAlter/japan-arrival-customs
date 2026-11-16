# 统一材质与采购图片补充

2026-11-15新增。仍用run.py、workflow=rebuild_mvp_v1，prepare增加mode=enrich_review；current/resume从任务记录自动识别。旧匹配和material_query_v1接口保持兼容。只处理已有固定24列确认表，不重新匹配名称/价格，不审批O材质、不收运营回传、不正式安装。

prepare最小配置：batch_id、input_file、output；sources为实际采购清单列表，每条包含path、role=purchase_list，可带sha256、version、sheets、field_map。配置开关materials/pictures/allow_online必须为JSON布尔值，默认前两项true、网络false；max_operations默认50，上限100，每次分别限制图片行和材质请求数。sheet默认invoice (計算)。图片列由表头识别；重复表头可通过field_map.code/sku/yd/image_url显式映射到表头或列，记录原字段位置。

商品图优先保全现有图，缺图才查采购清单。完整编码精确对应，现有YD约束来源版本；DG关联须同时核实YD。YD或图片链接不唯一时留空及原因，不靠名称猜图。下载后实际解码，验证页不当图片，缓存保留原URL、最终URL、图像哈希及来源单元格。网络错误最多自动两次；成功缓存恢复时不重复下载。材质复用material_foundation解析器和六站政策，新模式允许站点冷却时处理其他商品/站点，单站失败两次后记deferred，不能记查无。

外部取页通过返回的requests执行；resume.responses每条只允许request_id、http_status、body、final_url、transport_error。body是网页/接口真实原文，不接受模型填入一个材质结论。请求ID和回传摘要由已有材质接口校验，重复回传幂等。Skill可用operate.py --responses <JSON文件>传入，配置与规则保持冻结。未完成外部取页则partial，其他图片和已查材质仍出表。

先补材质、收集图片，再统一最后出表。Excel原件只读，生成带序号副本和对应待补CSV；R只补空格，O/S和其他业务内容、原图均保留。来源及详细错误在field-evidence.json；不增加业务列。图片使用普通ZIP头、UTF-8 XML、唯一关系ID及单元格锚点；新增图片保持比例。导出先校验原值/公式缓存/箱重及其他ZIP部件，再发布副本。export.json回执支持文件发布后、任务记录保存前的中断恢复；输入、程序、规则或已发布文件变化则拒绝继续覆盖。

current返回任务阶段、pending数量、文件、缺项原因、外部取页请求和等待时间。completed_with_gaps代表所有已配置路径结束但仍有缺项，partial代表还有待下载/续查；都不代表运营认可或正式安装。业务Excel、来源链接、图片与网页证据仅本机保存，不提交Git。

验证：rebuild_mvp/tests/test_enrichment.py；实际run.py整批运行、WPS和Terra结果另见本机任务报告，不把合成测试当业务验收。


## 2026-11-16 链接预填与材质修复

新任务默认picture_mode=links：E列空格先填唯一核实的采购图片URL；已有图片和人工文字保留。此阶段不下载图片，current分别列picture_link_rows、missing_picture_link_rows、blank_picture_rows，待补CSV区分缺链接与已有链接待最后嵌图。链接存在不等于图片已下载或已嵌入。E列已有HTTP链接可作为本行来源继续使用。

最后在同一任务resume传finalize_pictures=true，或operate.py --action resume --finalize-pictures，才下载并嵌图；仍需allow_online=true。旧任务未设置picture_mode时维持原嵌图模式；旧冻结程序及状态不迁移。显式picture_mode=embed可直接嵌图。

材质404记HTTP_404_UNVERIFIED错误，可重试；接口返回HTML、null或数组记INVALID_API_RESPONSE，不再当成功空结果。非阻塞模式继续其他站点，重试耗尽保留deferred，不当作查无。站点实际可用性仍须真实联网验证。
