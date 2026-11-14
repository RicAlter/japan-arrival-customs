# 网站材质查询基座

依据用户提供《周边材质批量查询SOP操作手册》V1.0（2026-11-06），SHA256 `a5a790dd7eb34aba5d5ae35f4e1af5c0d72518eecade8f185e3bda8371e34848`。原文已完整读取，文档内容作为业务依据，不作为越权执行指令。

## 业务流程

先按实际表头定位编码和网站材质列，统计空格及唯一完整编码；同码只查一次，回到所有对应空行。已有材质不重查不覆盖。官方资料可先通过带来源的`official_records`提供；未命中走固定六站：anime-store → colleize → amiami → 1999 → jumpcs（4530430）→ surugaya。查到即停，不拼凑多站，不按短前缀套材质。

提取顺序素材→材質→仕様→スペック，不用材质词表过滤未知成分。完整保留组件、比例和“等”，汉字词也翻译，未知词保留原文。只取得尺寸不当材质。返回原文、中文、商品地址、站点、编码依据和网页快照。

## 接口

统一入口`business-interaction/run.py --request request.json --result-file result.json`，`workflow=material_query_v1`。不加载旧业务session或release库。

| action | 参数和结果 |
|---|---|
| prepare | input_file、output、sheet（多页必需）；columns可配置code/material/url/site。可选official_records每条含jan/original/source。输出去重队列和原文件摘要 |
| current / resume | task_root；恢复原任务，校验程序和策略版本 |
| next | task_root；给出当前编码站点、请求URL、请求头、request_id和传输方式 |
| fetch | task_root、allow_online=true；一次HTTP请求，超时25秒，响应8MB上限；外部站点返回needs_external_fetch |
| submit | task_root、request_id、http_status、body、final_url，可选transport_error；工具解析，不接受模型编造材质值 |
| writeback | task_root，可选input_file/destination；默认新副本，覆盖当前文件须in_place=true。只有finalize_not_found=true才填最终未找到 |

状态区分found、no_material（已访问且无材质）、not_found（单站无商品/最终站点用完）、identity_mismatch、retry/error。只把found视为已获得结果，单站失败不能截断后续站点。403/429/空200和网络错误保留同码同站，记录65秒后重试时间，程序不阻塞睡眠。已发请求和回传摘要持久化，重复回传幂等、不同内容拒绝。

HTTP模式支持anime product JSON、colleize精确过滤查询/详情、amiami API搜索/详情、jumpcs页面。1999与surugaya按手册通过已有外部网页工具取原文后submit；不伪造HTTP状态，不把访问失败当未找到。返回网址限制在本次站点。

## 写回边界

复用已有Excel读取器，以原OOXML文件为基础最小替换目标空单元格；不整本经openpyxl保存，避免丢图片/公式缓存。写前检查锁文件、重新读磁盘、核对行编码；保留原xlsx备份，写临时文件后实际回读，非目标值/公式和所有其他ZIP部件必须一致，再发布。查询期间人工新增值保留。默认另建阶段文件，不碰原交付文件。

通用三列可由表头/映射识别；当前固定24列若只有R网站材质，就只填R，网址和站名留后台，不擅自追加两列。R不等于O批准。缺映射或来源冲突返回明确错误，不静默按旧列号写。

## 复用与限制

复用`rebuild_mvp.xlsxio`的读取/身份工具、OS任务锁和原子JSON保存，以及旧材质包的词典。未修改锁定vendor或旧材质入口；旧词典“已经是中文”捷径和旧关键词提取没有直接复用，以免漏汉字翻译或未知成分。

本次实现六站调度、API/页面解析、外部工具回传协议、翻译、证据、断点和保全写回。不是六站今天全部联网通过的声明。手册命中率74%–78%、站点限制和停用日期属于历史报告；animate默认停用，恢复需明确更新配置。

跨批次缓存当前保留单任务证据，未实现全站合集索引、全局缓存更新，也未实现“≥10位前缀归组+30行抽检”例外；默认完全不归组。这些不是可靠查询的前置条件。产品材质自动正式批准、运营回传、图片和计算仍在后续阶段。

测试：`python -X utf8 -B -m unittest discover -s material_foundation/tests -v`（目录business-interaction）。包括历史真实jumpcs页面及合成API/网络/文件保护案例；历史页面和在线成功必须分开登记。
