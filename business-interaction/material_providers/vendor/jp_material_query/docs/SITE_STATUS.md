# 五站适配与授权状态

更新日期：2026-11-05  
结论：**五站适配器均已完成离线解析验证；真实联网全部关闭；均未取得站方授权。**

| 站点 | 历史入口 | 适配器实现 | 离线样本 | 真实联网 | 授权状态 | 已知限制 |
| --- | --- | --- | --- | --- | --- | --- |
| Anime Store | `https://anime-store.jp/products/<JAN>` | 直接 JAN 详情页；支持 `■素材`、`素材`、表格、`本体` | 通过 | **关闭** | **未取得** | 历史高并发曾触发限制；旧解析器曾漏 `■` 字段；需真实页面回归 |
| AmiAmi | 历史搜索/详情 API：`api.amiami.com/api/v1.0/...` | 搜索 JSON -> 核对 `jancode` -> `gcode` -> 详情 `spec` | 通过 | **关闭** | **未取得** | 历史 API 不是当前合同；429 限流；下架商品搜索不到；网页截断 |
| Jump Character Store | `https://jumpcs.shueisha.co.jp/shop/g/g<JAN>/` | 直接 JAN 详情页；`素材` 字段 | 通过 | **关闭** | **未取得** | 历史 403；`4530430` 前缀只是筛选线索，不构成身份认定 |
| HobbySearch | `https://www.1999.co.jp/search/?q=<JAN>` | 搜索页链接 -> 详情页；`商品説明/商品仕様/素材` | 通过 | **关闭** | **未取得** | 历史 403；禁止代理轮换；搜索页结构需真实回归 |
| Animate | `https://www.animate-onlineshop.jp/products/list.php?mode=search&smt=<JAN>` | 搜索页链接 -> 详情页；`素材/材質/製品素材` | 通过 | **关闭（默认禁用）** | **未取得** | 2026-10 起持续 403；未满足许可及可用性条件前不自动重试 |
| 本地商品资料库 | 自有业务记录（JSON） | 按 JAN 读取本地材质记录 | 通过 | 不联网 | 使用自有数据 | 仅中文/原文记录；多记录冲突保留；需人工确认 |

## 适配器文件

| 站点 | 文件 |
| --- | --- |
| Anime Store | `jpmaterial/adapters/anime_store.py` |
| AmiAmi | `jpmaterial/adapters/amiami.py` |
| Jump Character Store | `jpmaterial/adapters/jumpcs.py` |
| HobbySearch | `jpmaterial/adapters/hobbysearch.py` |
| Animate | `jpmaterial/adapters/animate.py` |
| 本地资料库 | `jpmaterial/adapters/local_library.py` |

## 真实联网前的检查清单

- [ ] 站方明确允许的用途、接口/页面、访问频率、资料保存范围
- [ ] 许可依据写入 `config/sites.json` 的 `authorization_reference`
- [ ] `enabled=true` 且 `authorized=true`
- [ ] 先用已知 JAN 做单条 `--allow-online` 验证
- [ ] 用故意不匹配的 JAN/版本做负样本验证
- [ ] 确认 403 会停止、429 会退避、网络异常不会误报无材质
- [ ] 确认输出仍是独立候选表，不覆盖原表/主数据/海关文件


## 不登录、不自动联网时的替代方式

如果暂时不申请站方接口授权，也不想使用账号登录，可以让人工在浏览器中打开商品页并另存为 HTML，放入：

~~~text
snapshots/<site_id>/<JAN>/detail.html
~~~

然后运行：

~~~bash
python run.py batch --input <原表.xlsx> --output <候选表.xlsx> --snapshot-dir snapshots
~~~

插件只解析本地文件，不发起站点请求。此方式不需要站方接口授权，但仍须遵守站方条款，且不得用脚本批量抓取页面。
