# 验收要求与证据

| # | 验收要求 | 实现/证据 | 测试 |
| --- | --- | --- | --- |
| 1 | 已保存的历史样本能正确解析 | 五站离线夹具；`output/historical_cases_results.xlsx`；5/5 `candidate_ready` | `test_acceptance.test_01_historical_samples_parse`、`test_engine.test_offline_historical_cases` |
| 2 | 多成分材质不丢失 | 保留 `、`、`,`、`等`、百分比；未知词保留原文 | `test_acceptance.test_02_multi_component_lossless`、`test_material_translate` 多成分/翻译用例 |
| 3 | 不同版本或规格不会错误匹配 | 版本标记核对；JAN 一致但 `通常版/限定版` 冲突 -> `version_mismatch`，不推荐 | `test_acceptance.test_03_version_mismatch_not_exact`、`test_identity`、`test_adapters.test_version_mismatch` |
| 4 | 查询失败不会误报为无材质 | 网络/403/429/HTTP/解析异常单独归类；`no_material` 仅在页面确实无材质/仅尺寸时出现 | `test_acceptance.test_04_network_error_not_no_material`、`test_gate_cache`、`test_engine.test_no_material_overall` |
| 5 | 结果包含可靠来源 | 每条 Evidence 含站点、URL、抓取时间、原文、内容哈希、摘要 | `test_adapters`、`test_output.test_json_schema`、Excel「查询结果」 |
| 6 | 重复查询不会产生重复业务记录 | 同 JAN 只查一次；`输入行映射` 保留行号；缓存复用 | `test_output.test_batch_duplicate_jan_one_record`、`test_gate_cache.test_cache_reuse` |
| 7 | 未授权网站不会被实际请求 | 默认 `authorized=false`；`--allow-online` 也不越过授权；FakeTransport 断言 0 次调用 | `test_acceptance.test_05_unauthorized_no_request`、`test_gate_cache.test_unauthorized_makes_no_network_call`、`test_engine.test_unauthorized_all_sites_no_request` |
| 8 | 原始业务表和正式海关数据不受影响 | 只读输入；输出路径相同直接拒绝；写入前后 SHA256 对比 | `test_acceptance.test_06_input_not_modified`、`test_output.test_refuse_overwrite_input`；目标表 SHA256 未变 |

## 额外验证

- 403 后停止该站，人工 reset 后才恢复：`test_403_blocks_site_until_reset`
- 429 按 Retry-After 退避后重试：`test_429_retry_then_success`
- 本地资料库优先：`test_local_library_priority`
- 本地多记录冲突：`test_local_conflict`
- 多来源材质冲突：`test_conflict_between_sources`
- 原表已有材质不覆盖：`test_existing_material_skips`
- 本地快照不登录、不联网：`test_snapshot_query_without_login_or_network`
- 快照缺失不误报无材质：`test_snapshot_missing_is_not_no_material`

## 测试报告

- `output/test_report.txt`
- `output/test_report.json`
- 当前结果：63 tests, 0 failures, 0 errors, 0 skipped。
