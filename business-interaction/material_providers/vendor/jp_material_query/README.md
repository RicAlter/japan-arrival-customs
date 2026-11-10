# 日本商品材质查询插件（DSH 交接版）

独立、只读、离线优先的商品材质查询插件。输入 JAN 与商品信息，输出**有来源、可核对、可审计**的中文材质候选；不修改日本到货原表，不直接生成海关申报结论。

> 当前版本：0.1.0  
> 默认状态：**五个网站全部未授权、全部不联网**；Animate 站点默认关闭。  
> 本仓库内的历史样本仅用于离线解析验证，不代表站方当前页面结构或在售商品。

---

## 1. 交付内容

| 路径 | 作用 |
| --- | --- |
| `jpmaterial/` | 插件主包：模型、JAN 校验、身份匹配、材质提取/翻译、五站适配器、缓存、授权门禁、查询引擎、Excel/JSON 输出、CLI |
| `config/sites.json` | 站点授权开关。默认全部 `authorized=false` |
| `config/glossary.json` | 材质词表；未匹配词保留原文 |
| `fixtures/` | 五站历史字段结构的离线样本、负样本、历史案例 |
| `tests/` | 63 个离线测试（解析、翻译、身份、门禁、缓存、输出、验收） |
| `scripts/run_tests.py` | 跑测试并生成 `output/test_report.txt/.json` |
| `scripts/run_demo.py` | 用历史样本生成独立演示 JSON/Excel |
| `scripts/build_local_index.py` | 从已有业务表生成只读本地材质索引（第三阶段可选） |
| `scripts/verify_delivery.py` | 交付自检：授权默认关闭、历史案例、目标表 SHA256、测试状态 |
| `output/` | 测试报告、历史案例结果、目标表离线预览 |
| `docs/SITE_STATUS.md` | 各站适配与授权状态 |
| `docs/ACCEPTANCE.md` | 验收要求与对应测试 |
| `docs/HANDOVER.md` | 技术交接、数据结构、接入方式、下一步 |

**不做的事**：不写回原始 Excel；不修改商品主数据；不覆盖正式海关文件；不把网站材质自动当成申报材质；不实现品类/盒规自动采集。

---

## 2. 快速开始

在项目目录 `jp_material_query` 下执行：

~~~bash
# 1) 查看五站授权/熔断状态
python run.py sites

# 2) 跑全部离线测试
python scripts/run_tests.py

# 3) 用历史样本做单条离线查询（不联网）
python run.py query --jan 4571608537527 --name-ja "テスト フィギュア 通常版" --offline-dir fixtures/historical

# 4) 批量读取到货原表，输出独立候选表（默认不联网）
python run.py batch ^
  --input "C:\Users\Administrator\Downloads\KMT20261101_原表修改确认表_材质参考补充版.xlsx" ^
  --output "output\KMT20261101_材质候选_离线预览.xlsx"

# 5) 生成历史样本演示结果
python scripts/run_demo.py

# 6) 交付自检
python scripts/verify_delivery.py
~~~

输出：

- `output/KMT20261101_材质候选_离线预览.xlsx`：独立候选表（查询结果 / 站点尝试 / 输入行映射 / 无法查询（如有） / 说明）
- `output/KMT20261101_材质候选_离线预览.json`：完整证据 JSON
- `output/historical_cases_results.xlsx` / `.json` / `.md`：五站历史材质案例的离线验证结果
- `output/test_report.txt` / `.json`：测试报告

---

## 3. 查询流程

1. **JAN 规范化与校验**：13 位、EAN-13 校验位；无效 JAN 单独标记，不进入网站查询。
2. **本地资料库优先**：如果配置了 `--local-index`，先按 JAN 查本地业务记录；唯一命中则直接作为候选。
3. **站点授权门禁**：只有同时满足
   - `config/sites.json` 中 `enabled=true`
   - `authorized=true`
   - 命令行显式 `--allow-online`
   才会发出真实请求；任一条件不满足都不联网。
4. **缓存**：有效缓存直接复用，保留原始抓取时间、来源 URL、内容哈希；同一 JAN 不重复抓取。
5. **身份匹配**：JAN 必须一致；再核对日文商品名、版本/规格（`通常版/限定版/第N弾/vol./BOX/全N種` 等）。JAN 一致但版本不同，不自动采用。
6. **材质提取**：支持 `■素材`、`素材`、`材質`、`材料`、`製品素材`、`Material`、`本体：PVC・ABS`、表格 `th/td`、标签换行；严格排除 `サイズ`。
7. **翻译**：完整保留成分、比例、`等`；无法可靠翻译的词保留日文原文并列在“未知词”。
8. **聚合**：同一 JAN 多来源材质不同 -> `conflict`；唯一可靠候选 -> `candidate_ready`，但仍标记“需人工核对”。
9. **输出**：独立 JSON/Excel；原表只读，输出文件与输入路径相同时直接拒绝。

---

## 3.1 不登录、不自动联网：本地页面快照

如果不想申请站方接口授权，也不想登录账号，推荐使用**人工保存页面 + 本地快照解析**：

- 你自己在浏览器里打开商品页（公开页面，无需登录）。
- 另存为 HTML，或把页面源码保存到本地。
- 插件只读取本地文件，**不发起任何站点请求，不使用账号/Cookie**。
- 仍请遵守站方条款：不要用脚本/插件批量抓取，只保存你需要核对的那几个商品页。

目录结构（推荐）：

~~~text
snapshots/
  anime_store/
    4571608537527/
      detail.html
  amiami/
    4571608537534/
      search.json
      detail.json
  hobbysearch/
    4571601234072/
      search.html
      detail.html
~~~

也支持单文件：

~~~text
snapshots/anime_store/4571608537527.html
snapshots/anime_store/4571608537527.json
~~~

单条查询：

~~~bash
python run.py query --jan 4571608537527 --snapshot-dir snapshots
~~~

批量查询：

~~~bash
python run.py batch ^
  --input "C:\path\到货原表.xlsx" ^
  --output "output\材质候选_快照版.xlsx" ^
  --snapshot-dir snapshots
~~~

说明：

- 快照缺失时输出 `not_checked` / `manual_snapshot`，不会误报“无材质”。
- 快照解析仍会做 JAN、日文名、版本/规格核对；JAN 不一致不会采用。
- 本地快照不需要站方授权，但**不代表站方授权自动采集**；它只是替代“人工翻页查找”的离线解析。
- 如果后续取得授权，可在同一套输出上切换为 `--allow-online`。

---

## 4. 输出字段（Excel「查询结果」）

`JAN`、`商品名称(中文)`、`日文描述`、`规格/版本`、`原表材质`、`处理建议`、`查询状态`、`匹配状态`、`材质状态`、`日文材质原文`、`中文材质参考`、`未知词(保留日文)`、`来源网站`、`来源类型`、`商品详情URL`、`查询时间`、`内容哈希`、`来源商品名(日文)`、`来源规格`、`来源尺寸`、`来源摘要`、`是否需要人工核对`、`错误码`、`备注`、`候选数`、`出现行号`、`状态码`。

- 列位由输出模板决定，**没有写死 G/H/I**；输入列位由表头别名自动识别。
- 同一 JAN 多行只产生一条查询记录；`输入行映射` 保留每行行号，避免重复业务记录。
- `是否需要人工核对`：网站/本地记录产生的候选一律为“是”；网站材质不自动等于最终申报材质。

### 状态码

| 层 | 取值 |
| --- | --- |
| 查询状态 | `candidate_ready` / `needs_review` / `conflict` / `not_found` / `no_material` / `not_authorized` / `error` / `invalid_input` / `existing_material` / `not_checked` |
| 匹配状态 | `exact` / `jan_only` / `version_mismatch` / `name_mismatch` / `jan_mismatch` / `multiple_candidates` / `not_found` / `invalid_jan` / `not_checked` |
| 材质状态 | `found` / `no_material` / `size_only` / `extract_failed` / `not_checked` |
| 访问状态 | `ok` / `cached` / `not_authorized` / `site_disabled` / `blocked_403` / `rate_limited` / `network_error` / `http_error` / `parse_error` / `skipped` |

---

## 5. 站点适配状态

| 站点 | 适配器 | 离线解析 | 真实联网 | 授权 |
| --- | --- | --- | --- | --- |
| Anime Store | 完成 | 已验证 | **关闭** | 未取得 |
| AmiAmi | 完成 | 已验证 | **关闭** | 未取得 |
| Jump Character Store | 完成 | 已验证 | **关闭** | 未取得 |
| HobbySearch | 完成 | 已验证 | **关闭** | 未取得 |
| Animate | 完成 | 已验证 | **关闭（默认禁用）** | 未取得 |
| 本地商品资料库 | 完成 | 可选 JSON | 不联网 | 使用自有数据 |

详细限制见 [docs/SITE_STATUS.md](docs/SITE_STATUS.md)。

---

## 6. 授权与安全边界

- **默认不联网**：`config/sites.json` 五个站点 `authorized` 全部为 `false`；Animate `enabled=false`。
- **双重开关**：即使把 `authorized` 改成 `true`，没有 `--allow-online` 也不会请求。
- **403**：记录并永久熔断该站，直到人工 `python run.py sites --reset <site_id>`；不会自动重试。
- **429**：按 `Retry-After` 退避，最多重试 `max_retries` 次；超过上限临时熔断。
- **网络异常/解析异常**：单独归类为 `network_error` / `parse_error`，绝不会写成“无材质”或“商品不存在”。
- **不使用代理轮换、不绕过站方限制、不把历史客户端凭据当作授权**。
- **原始文件只读**：输出路径与输入相同时直接拒绝；输出前/后计算输入 SHA256，写入「说明」页。

### 取得授权后如何开启

1. 按站方许可确认：允许的接口/页面、用途、访问频率、资料保存范围。
2. 编辑 `config/sites.json`：

~~~json
"anime_store": {
  "authorized": true,
  "allowed_purpose": "日本到货商品材质核对",
  "authorization_reference": "许可依据/邮件/合同编号"
}
~~~

3. 先跑 `python run.py sites` 确认 `可联网=True`。
4. 小批量验证：

~~~bash
python run.py query --jan <已知JAN> --allow-online --all-sites
~~~

5. 确认解析结果后再跑批量；仍只输出候选，不写回原表。

---

## 7. 测试与验收结果

- 测试：**63 个，全部通过**（0 failure / 0 error）。
- 历史样本：5 个站点案例均解析为 `candidate_ready`，材质原文与中文参考逐字匹配。
- 目标表离线预览：
  - 读取 1275 行有效业务行（另有 40 行空白行被跳过）
  - 1259 个唯一 JAN
  - 59 个 JAN 原表已有材质（保留，不覆盖）
  - 1200 个 JAN 因**未授权**标记 `not_authorized`
  - 16 行重复 JAN 复用同一查询记录
  - **0 条新增材质候选**（因为所有站点未授权；这是预期结果，不是解析失败）
- 联网请求：**0 次**；未访问任何站方页面。
- 原始工作簿 SHA256 写入前后一致：`315d458576034af17f46fbcc42d8ec3deb495810fc1968fae4848728a44a9402`。

验收对照见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)。

---

## 8. 已知限制与下一步

**已完成**

- 五站独立适配器、统一 Evidence/QueryResult 模型。
- 历史样本离线解析、材质提取、中文翻译、身份匹配。
- 缓存、403 熔断、429 退避、授权门禁、错误分类。
- 批量读取原表、独立 JSON/Excel 输出、重复 JAN 去重。
- 本地资料库接口与导入脚本。

**仍需授权/人工判断**

- 五站真实联网均未开启；需要逐站确认许可、接口/页面、频率与保存范围。
- 适配器基于历史字段结构编写；真实页面结构可能变化，需用授权后的真实页面做回归。
- AmiAmi 的历史 API 记录不是当前 API 合同；不得把历史客户端凭据当作授权。
- Animate 自 2026-10 持续 403，默认关闭；未满足许可及可用性条件前不自动重试。
- JAN 缺失时只标记为“无法查询”，不发起仅凭商品名的自动站点查询，避免把名称相似误当同一商品。
- 品类、盒规自动采集未实现，也不应被当作已完成能力。
- 网站材质只是候选，仍需业务人员确认、专业审核后才能成为申报材质。

**建议顺序**

1. 逐站完成授权核验（先 Anime Store / AmiAmi）。
2. 用已知 JAN + 故意不匹配 JAN 做小批量真实页面回归。
3. 接入本地商品资料库（只读候选查询）。
4. 再接入日本到货处理 Skill 的基础资料整理阶段；人工确认后才产生可复用业务记录。

---

## 9. 开发环境

- Python 3.10+（当前运行环境 3.x）
- 依赖：`openpyxl`（读写 Excel）
- 其余为标准库：`urllib`、`json`、`html.parser`、`unittest`
- Windows 控制台如出现编码问题，CLI 已强制 UTF-8 输出。

---

## 10. 免责声明

本插件输出的是**材质查询候选与证据**，不是海关申报结论。网站/本地记录中的材质可能过时、缺项或与实物不一致；采用前必须由业务人员核对商品身份、版本、规格与材质原文，并经专业审核。插件不修改原始业务表、商品主数据或正式海关文件。
