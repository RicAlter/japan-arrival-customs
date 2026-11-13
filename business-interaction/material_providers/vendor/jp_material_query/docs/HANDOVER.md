# 技术交接

## 1. 架构

~~~text
输入 Excel/单个 JAN
      │
      ▼
 input.py（表头自动识别，只读）
      │
      ▼
 QueryEngine ──► LocalLibrary（可选，本地资料库优先）
      │
      ├── AccessRegistry（授权/403 熔断/429 退避）
      ├── CacheStore（TTL、来源、抓取时间、内容哈希）
      ├── SiteAdapter × 5（统一 ProductQuery/Evidence）
      └── Transport（urllib；默认禁用代理）
      │
      ▼
 身份匹配（JAN + 日文名 + 版本/规格）
      │
      ▼
 材质提取（素材/材質/■素材/Material/本体；排除サイズ）
      │
      ▼
 中文翻译（完整保留成分/比例/等；未知词保留日文）
      │
      ▼
 聚合（唯一候选/冲突/无材质/未授权/异常）
      │
      ▼
 JSON + Excel（独立文件；候选，不写回）
~~~

## 2. 关键数据结构

### ProductQuery

`jan`、`name_zh`、`name_ja`、`spec`、`description_ja`、`source_row`、`raw`。

### Evidence

`site_id`、`site_name`、`source_type`、`product_url`、`jan_on_page`、`name_ja`、`spec_text`、`size_text`、`material_original`、`material_zh`、`material_unknown_terms`、`match_status`、`material_status`、`access_status`、`queried_at`、`fetched_at`、`from_cache`、`content_hash`、`source_excerpt`、`needs_review`、`error_code`、`notes`、`confidence`、`input_material`。

### QueryResult

`query`、`candidates`、`attempts`、`status`、`match_status`、`material_status`、`recommended`、`needs_review`、`reason`、`queried_at`、`cache_hit`、`input_material`、`action`、`input_rows`。

## 3. 代码入口

| 用途 | 入口 |
| --- | --- |
| CLI | `python run.py` / `python -m jpmaterial` |
| 单条查询 | `QueryEngine.query(ProductQuery, allow_online=False, all_sites=False)` |
| 离线解析 | `QueryEngine.query_offline(ProductQuery, fixture_root, site_ids=[...])` |
| 本地快照 | `QueryEngine.query_snapshots(ProductQuery, snapshot_root, site_ids=[...])` |
| 批量 | `jpmaterial.batch.run_batch` |
| Excel | `jpmaterial.output.write_excel` |
| JSON | `jpmaterial.output.write_json` |
| 本地索引 | `jpmaterial.adapters.LocalLibrary.load` + `scripts/build_local_index.py` |

## 4. 适配器接口

每个站点继承 `jpmaterial.adapters.base.SiteAdapter`：

- `build_detail_url(jan_or_gcode)`
- `build_search_url(query)`
- `parse_detail(payload, query, url, ref)` -> `Evidence`
- `parse_search(payload, query)` -> `list[ProductRef]`
- `requires_search`：是否需要先搜索再进详情

共享的 `parse_html` 负责：页面 JAN/名称/规格识别、`not_found` 判断、材质提取、身份核对、翻译、内容哈希。

## 5. 授权与错误处理

- `config/sites.json` 是唯一授权来源；代码不提供“自动授权”命令。
- `AccessRegistry` 持久化 `state/access_state.json`：
  - 403：`blocked=true`、`blocked_until=null`，人工 `sites --reset` 才能恢复。
  - 429：记录 `Retry-After`，超过 `max_retries` 后临时熔断。
- `CacheStore` 持久化 `state/cache.json`；缓存条目包含 `fetched_at`、`expires_at`、`url`、`data`。
- 错误分类：
  - `not_found`：页面 404/410 或明确“找不到商品”
  - `no_material`：页面有商品但无素材字段
  - `size_only`：只有尺寸
  - `identity_uncertain` / `version_mismatch` / `jan_mismatch`：身份不确定
  - `network_error` / `http_error` / `parse_error` / `blocked_403` / `rate_limited` / `not_authorized`
- **网络异常绝不映射为 `not_found` 或 `no_material`。**

## 6. 与日本到货处理 Skill 的接入

建议只调用批量入口，读取独立 JSON/Excel：

~~~bash
python run.py batch --input <到货原表.xlsx> --output <候选表.xlsx> [--local-index <本地索引.json>] [--snapshot-dir snapshots]
~~~

主流程只应读取：

- `status=candidate_ready`：候选，进入人工核对；
- `status=conflict`：保留冲突，人工判断；
- `status=no_material` / `not_found`：分别处理，不能混为一谈；
- `status=not_authorized`：等待授权，不是“没有材质”；
- `status=error`：先修网络/访问/解析，不能当作商品不存在。

**不要**把输出列写死到原表 G/H/I；**不要**自动覆盖原表 `材质` 列；**不要**把候选直接写入申报文件。

## 7. 测试

~~~bash
python scripts/run_tests.py
# 或
python -m unittest discover -s tests -v
~~~

测试覆盖：

- JAN 校验、名称相似度、版本标记
- `■素材` / 表格 / 标签换行 / `本体` / `Material` / `サイズ` 排除
- 多成分、`等`、百分比、未知词保留
- 五站历史夹具
- 未授权零请求、403 熔断、429 退避、网络异常分类
- 缓存复用、重复 JAN 去重
- 输出列、输出路径保护、输入 SHA256 不变

## 8. 后续工作

1. 逐站授权核验，填写 `authorization_reference`。
2. 用真实页面补/改适配器；保留离线夹具回归。
3. 接入本地商品资料库（只读），补 JAN 冲突与历史版本策略。
4. 增加品类/盒规是另一个独立项目，不要混入本插件。
5. 若要保存“业务人员确认采用”的记录，另建确认表/审计表，不覆盖网站证据。
