# 配置说明

## sites.json

每个站点：

- `enabled`：是否启用适配器。
- `authorized`：是否已取得站方许可。**默认全部 false。**
- `authorization_note`：当前授权状态说明。
- `allowed_purpose`：许可允许的用途。
- `authorization_reference`：许可依据（邮件/合同/工单号）。
- `rate_limit_seconds`：两次请求之间的最小间隔。
- `max_retries`：429 最大重试次数。
- `ttl_seconds`：缓存有效期。

只有 `enabled=true` + `authorized=true` + 命令行 `--allow-online` 三者同时成立才会联网。

## glossary.json

- `materials`：日文/英文材质 -> 中文参考。
- 词表按最长匹配优先；未匹配词保留原文并计入“未知词”。
- `等`、`など` 必须保留，不要删除。
- 不要凭经验添加原文没有的成分。

## 本地索引

`scripts/build_local_index.py` 可从已有业务表生成：

~~~bash
python scripts/build_local_index.py ^
  --input "C:\path\报单汇总.xlsx" ^
  --jan-column "jan code" ^
  --material-column "材质" ^
  --source "历史报单汇总" ^
  --out "data\local_index.json"
~~~

然后：

~~~bash
python run.py batch --input <原表> --output <候选表> --local-index data\local_index.json
~~~

本地记录只作为候选，仍需人工确认。
