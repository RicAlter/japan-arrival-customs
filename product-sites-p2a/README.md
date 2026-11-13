# P2-A 首站候选：anime-store

基线：`codex/product-library-p1-20261102`，`1ea746adb4df60882587b8c01851d153f025283d`。本目录独立新增，不修改P1、rc.5报单计算、冻结版本、D1或正式外发门禁，不安装WorkBuddy。

**当前状态：代码及离线保护已验证，真实商品查询未验证，首站未通过实机验收。** 2026-11-02核对五站访问及条款后，用户明确暂无站方授权。商品查询默认关闭；没有把公开页面可打开、robots允许或用户委托当作站方商业使用许可。五站核对及后续四站计划见[ACCESS_AND_FOUR_SITE_PLAN.md](ACCESS_AND_FOUR_SITE_PLAN.md)。

## 已实现

- 复用P1 `FIVE_SITE_INTERFACE.md`的核心响应合同，外层增加明确的抓取、观察身份和逐字段核对证据；状态与最终批准分开。
- 优先使用传入JAN，否则使用原商品编码的公开商品路径。该路径是技术候选，真实查询方式及当前站点兼容性仍待授权实测，不提供隐藏API或规避403的路径。
- 只用选定Product的GTIN/SKU精确值作为编码证据；URL尾码不构成商品身份。再核对日文名、版本和规格，缺项保持pending，已知差异拒绝关联，多Product同码不挑第一条。
- 日文名直接保存页面值；版本/规格只从显式结构化属性或标签读取，不从F数量后缀、BOX、全几种猜值。
- 完整提取素材原文，保留多行、成分、百分比及“等”。小词典译文可确定时逐项翻译；有未知词则完整原文保留、译文为null并列未知项，不静默删词。
- 保存网址、实际抓取时间、内容SHA-256及原始字节。查询时间与缓存原抓取时间分开；缓存命中仍按每行身份重算，合成缓存与实时缓存隔离。
- 同站串行锁、最小3秒间隔、robots的Crawl-delay/Request-rate、缓存TTL及最多一次重试。403不重试并停止该客户端后续商品请求；429尊重Retry-After，超过30秒的等待转为冷却状态，不强行等待或绕过。网络错误不写成未找到。
- 确认范围之前不发HTTP请求。robots拒绝、跨域/非HTTPS跳转、验证码页面、损坏缓存和来源不一致均停止，不代理轮换、不伪装浏览器、不登录或购物。

## 独立运行

Python 3.11+、标准库，依赖同仓库保留的P1合同组件。下面命令从本目录执行：

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B -m site_reference query --request <私有查询请求.json> --runtime <私有运行目录> --output <新候选目录>
```

未提供有效`--access-scope <私有站方授权记录.json>`时，逐行返回`permission_denied/site_permission_not_provided`，网络调用数为0。请求只含`items`数组，逐行身份与P1相同；不接受令牌/账号等额外字段。维护侧构造参数，不要求运营手写。

授权记录需`schema=product-site-access-scope/1`、site_id、purpose、authorization_reference、operator_review_reference、evidence_file、evidence_sha256、reviewed_terms_sha256、expires_at及allowed_path_prefixes。技术校验材料哈希、有效期和允许范围；站方材料真实性及其是否覆盖内部资料留存由维护者先核对。本仓库不附“已获授权”的配置，不使用用户自报身份代替站方材料。

候选目录含`candidates.json`和`unmatched.csv`，技术证据在独立runtime；不作为报单业务表或新增审核系统。未授权/网络失败与无商品/无材质分开。样本、请求、授权、真实结果与网页快照均不得入GitHub。

## 经校验后导出来源包

```powershell
python -X utf8 -B -m site_reference export --candidates <候选目录/candidates.json> --runtime <原私有运行目录> --output <新来源包目录> --authorization-reference <导入授权引用> --source-id <来源ID>
```

导出前复核P1响应合同、实时抓取记录、URL/时间/内容哈希、原始网页重解析、译文、身份状态。合成结果、授权阻断、身份冲突或没有成功候选时拒绝导出。原始快照字节随证据保存，仍为`reference_only/approval=false`；零售网站材质按历史/站点参考保存，不冒充制造商官方或D1批准。

导出只产生冻结V1候选来源包，不打开SQLite。后续维护者还须使用P1的`import-bundle`，核对用户授权、包哈希、备份和工作副本标记。当前没有导入任何网站候选，也没有向原库写数据。

## 实样与统计边界

```powershell
python -X utf8 -B validate_gate.py --p1-results <私有P1跨批结果.json> --output <新隔离门禁目录>
```

工具按P1原行序分层选择24个不同编码：无候选8、不完整身份且无材质8、歧义且无材质4、已有材质参考但身份待确认4。样本预先固定，不按网站结果挑成功案例。当前只验证24条授权门禁，真实HTTP商品请求0次；商品命中率、身份确认率、材质覆盖率与错误关联率全部null/未实测。

将来有授权时，分别报告行分母、不同编码数、实际新抓取、缓存复用、商品命中、完整身份确认、候选材质及完整译文。错误关联率需要独立人工标注；没有标注不称零错误。首站通过实测并验收前，不扩展另外四站。
