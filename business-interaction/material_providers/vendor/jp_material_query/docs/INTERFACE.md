# 接口文档（日本商品材质查询插件 v0.2.0）

独立、只读、离线优先的商品材质查询候选模块。定位：**当商品资料库查不到材质时查漏补缺**，
输入 JAN + 商品信息，输出有来源、可追溯的中文材质候选；不修改原表，不生成海关申报结论。

---

## 1. 版本与依赖

- 版本：**0.2.0**
- Python：>= 3.10
- 依赖：openpyxl>=3.1（见 requirements.txt；其余为标准库）

## 2. 安装说明

无需系统级安装。把整个目录 jp_material_query/ 拷贝到主流程可访问的位置即可：

~~~
# 方式 A：直接运行（推荐，零安装）
python run.py --help

# 方式 B：以包方式安装（可选）
pip install -e .
# 之后可用命令 jpmaterial ... 
~~~

配置目录 config/sites.json 控制各站是否启用/授权；状态目录 state/ 保存缓存与 403/429 熔断状态。

## 3. 命令行入口

统一入口：python run.py 命令（或 python -m jpmaterial / jpmaterial）。

### 3.1 单条查询（主 Skill 推荐调用方式）

~~~
python run.py query   --jan 4571608537527   --name-zh "反叛的鲁路修 amnibus校园时尚亚克力卡"   --name-ja "描き下ろし スクールファッションver. トレーディングAni-Frame(単位/BOX)"   --spec "拍立得整盒"   --brand "arma bianca"   --allow-online   --json-out result.json
~~~

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| --jan | 是 | 13 位 JAN（EAN-13，自动校验） |
| --name-zh | 否 | 商品中文名 |
| --name-ja | 否 | 商品日文名 |
| --desc-ja | 否 | 日文描述（用于身份核对与检索） |
| --spec | 否 | 规格/版本 |
| --brand | 否 | 品牌/渠道（如 arma bianca；写入结果供主流程路由） |
| --allow-online | 否 | 允许联网；否则只走离线/快照，不发请求 |
| --all-sites | 否 | 查询所有已授权站点，而非命中即停 |
| --offline-dir | 否 | 离线解析历史夹具目录（不联网） |
| --snapshot-dir | 否 | 人工保存的页面快照目录（不联网） |
| --timeout | 否 | 单次请求超时秒数，默认 20 |
| --json-out | 否 | 输出标准 JSON 文件路径 |

### 3.2 批量查询（查漏补缺主入口）

~~~
python run.py batch   --input "到货原表.xlsx"   --output "output/材质候选.xlsx"   --json-out "output/材质候选.json"   --allow-online   --max-seconds 3600
~~~

参数（关键项）：

| 参数 | 说明 |
| --- | --- |
| --input | 到货原表（只读，表头自动识别） |
| --output | 输出简化 Excel（默认） |
| --json-out | 输出标准 JSON（完整证据） |
| --detailed | 输出完整明细 Excel（含匹配状态/备注/站点尝试） |
| --include-filled | 原表已有材质也重新查询（默认跳过，不覆盖人工数据） |
| --max-seconds | 整批超时秒数，超时后剩余商品标“未查询” |
| --snapshot-dir / --local-index | 快照 / 本地资料库优先 |

其他命令：sites（站点状态/重置熔断）、cache（缓存统计/清理）、selftest（跑离线测试）。

## 4. 输出标准 JSON

顶层：schema_version、plugin_version、generated_at、mode、input_path、input_sha256、summary、site_status、results[]。

每条 results[i]：

~~~
{
  "query": {"jan": "...", "name_zh": "...", "name_ja": "...",
            "spec": "...", "brand": "arma bianca", "source_row": 2},
  "status": "needs_review",
  "match_status": "jan_only",
  "material_status": "found",
  "recommended": {
    "site_id": "amnibus", "site_name": "AMNIBUS",
    "product_url": "https://amnibus.com/products/detail/120286",
    "material_original": "紙", "material_zh": "纸",
    "match_status": "jan_only", "material_status": "found",
    "content_hash": "...", "queried_at": "..."
  },
  "candidates": [...], "attempts": [...],
  "reason": "...", "needs_review": true, "input_rows": [2]
}
~~~

## 5. 状态码（已区分五类）

| 维度 | 取值 | 含义 |
| --- | --- | --- |
| 查询状态 status | candidate_ready | 材质已查到且身份 JAN 核对一致 |
| | needs_review | 查到材质但身份未完全确认（如页面无 JAN），需复核 |
| | conflict | 多来源材质冲突 |
| | no_material | 找到商品但页面无材质字段 |
| | not_found | 未找到商品 |
| | error | 网络/解析/访问异常（不等于无材质） |
| | not_authorized | 未授权/未开启联网 |
| | existing_material | 原表已有材质，跳过不覆盖 |
| | not_checked | 未查询（如超时退出/无快照） |
| 匹配状态 match_status | exact / jan_only / version_mismatch / name_mismatch / jan_mismatch / multiple_candidates / ... | 身份核对结论 |
| 材质状态 material_status | found / no_material / size_only / extract_failed / not_checked | 材质提取结论 |
| 访问状态 attempts[].status | ok / cached / blocked_403 / rate_limited / network_error / http_error / parse_error / ... | 每次站点访问结果 |

约定：网络失败归 error/network_error，绝不归 no_material；403 停该站、429 按 Retry-After 退避。

## 6. 关键行为保证

1. 仅查询缺失字段：原表「材质」列已有值 → existing_material，不覆盖、不重复查询；--include-filled 才强制重查。
2. 超时退出：单请求 --timeout（默认 20s）；整批 --max-seconds 超时后剩余标 not_checked。
3. 单条失败不阻断整批：批处理对每个 JAN 单独 try/except，单条异常标 error 并继续。
4. 断点续跑：成功结果写 state/cache.json，重跑自动跳过已查 JAN（保留来源/抓取时间/内容哈希）。
5. 只读：输出路径与输入相同直接拒绝；写入前后校验原表 SHA256，原表与正式海关数据不受影响。

## 7. 回滚说明

- 数据回滚：模块从不写原表/主数据/海关文件，仅写独立 output/ 与 state/；删除这两个目录即回滚全部产物。
- 配置回滚：config/sites.json 把站点 authorized 改回 false 即恢复“默认不联网”状态。
- 版本回滚：保留 v0.1.0 目录备份；回退即替换目录（0.2.0 仅新增 brand 参数、批处理超时/隔离与简化输出，未改适配器与缓存核心）。
- 卸载：删除整个 jp_material_query/ 目录即可，无系统级安装、无残留注册项。

## 8. 接口验收

运行 python scripts/check_interface.py 做 CLI 级验收（离线，不联网）：验证 query 命令对 --jan/--name-ja/--brand/--json-out 的输入输出、状态码与推荐字段是否齐全。
