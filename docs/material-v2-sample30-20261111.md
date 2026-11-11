# SOP V2.0：30个真实商品查询验收

开发基准：`a295af8fc96c00a50db974d0eeaf7cc277436633`；独立分支 `codex/material-v2-sample30-20261111`。本报告覆盖材质查询与证据可靠性，不修改原业务Excel或执行1967行查询。

30个不同JAN：KMT20261101历史成功证据27个，KMT20261003已保存Jump证据3个；覆盖14个实际采购渠道（Jump样本采购渠道为Shueisha）。样本按站点、材质、百分比、组件和回退路线分层选择，历史成功样本占主导，不能据此推算全批命中率。

结果：离线原文提取、译文、身份与来源证据核验30/30；必要联网4/4取得可采用材质，合计8次实际HTTP请求，均为200。AMNIBUS初次找到详情但被误报查无，修复后另发2次请求复测；这2次计入8次总数。本轮没有真实触发403/429，不为触发限流而请求。

当前权限首次拦截的WinError10013单独保留为环境权限事件，不算网站失败；经批准的有限联网随后完成。Anime Store、MOVIC、COCOLLABO、Tower等已停站域名没有新访问。

## 30个商品逐项结果

“通过”表示本轮重新读取保存响应并解析/核证通过；并非30次联网成功，也不表示30条身份均由程序从零自动认定。历史身份审核、JAN证据链及人工/Agent核验依据保留，未冒充新业务批准。下列查询路线为历史证据和本轮回放共同覆盖的路线；旧记录的“delegated”只表示分派，不计作请求已执行。

|序号|JAN / 批次|采购渠道|查询路线 / 最终来源|材质原文 → 中文|结果、失败原因或修正|
|---:|---|---|---|---|---|
|1|4573643422394<br>KMT20261101|arma bianca|缓存核验 → JAN商品JSON<br>[详情](https://anime-store.jp/products/4573643422394)|紙、ブリキ → 纸、马口铁|通过；当前失败原因：无。原文、身份及快照核验通过|
|2|4589838312005<br>KMT20261101|A3|缓存核验 → JAN商品JSON<br>[详情](https://anime-store.jp/products/4589838312005)|金属、紙/フィルム → 金属、纸/フィルム|通过；当前失败原因：无。原文、身份及快照核验通过|
|3|4550451431046<br>KMT20261101|crux|缓存核验 → JAN商品JSON<br>[详情](https://anime-store.jp/products/4550451431046)|ブリキ → 马口铁|通过；当前失败原因：无。原文、身份及快照核验通过|
|4|4571696827388<br>KMT20261101|MENEGI|缓存核验 → JAN商品JSON<br>[详情](https://anime-store.jp/products/4571696827388)|アクリル → 亚克力|通过；当前失败原因：无。全半角、波浪号差异；旧身份审核已复核|
|5|4571601234010<br>KMT20261101|Shimizu Sangyo|缓存核验 → JAN商品JSON<br>[详情](https://anime-store.jp/products/4571601234010)|PET、ブリキ → PET塑料、马口铁|通过；当前失败原因：无。原文、身份及快照核验通过|
|6|4550687210439<br>KMT20261101|KADOKAWA|缓存核验 → JAN商品JSON<br>[详情](https://anime-store.jp/products/4550687210439)|紙 → 纸|通过；当前失败原因：无。原名PACK、历史规格整盒；不推换算|
|7|4573643235000<br>KMT20261101|arma bianca|Anime Store查无 → Colleize JAN搜索 → 精确详情<br>[详情](https://colleize.com/lineup/260/406974)|綿100% → 棉100%|通过；当前失败原因：无。原文、身份及快照核验通过|
|8|4573643235017<br>KMT20261101|arma bianca|Anime Store查无 → Colleize JAN搜索 → 精确详情<br>[详情](https://colleize.com/lineup/260/406975)|綿100% → 棉100%|通过；当前失败原因：无。原文、身份及快照核验通过|
|9|4573643235024<br>KMT20261101|arma bianca|Anime Store查无 → Colleize JAN搜索 → 精确详情<br>[详情](https://colleize.com/lineup/260/406976)|綿100% → 棉100%|通过；当前失败原因：无。原文、身份及快照核验通过|
|10|4549970307826<br>KMT20261101|cospa|快速站未解决 → AmiAmi JAN搜索 → 详情<br>[详情](https://www.amiami.jp/top/detail/detail?gcode=GOODS-04409465)|Cotton 100% → 棉 100%|通过；当前失败原因：无。清除颜色/作者信息；BLACK/M已核验|
|11|4580822011317<br>KMT20261101|Hobby Stock|快速站未解决 → AmiAmi JAN搜索 → 详情<br>[详情](https://www.amiami.jp/top/detail/detail?gcode=GOODS-04853066)|Acrylic → 亚克力|通过；当前失败原因：无。清除Features字段，不推底座成分|
|12|4580878446767<br>KMT20261101|Playful Mind Company|快速站未解决 → AmiAmi JAN搜索 → 详情<br>[详情](https://www.amiami.jp/top/detail/detail?gcode=GOODS-04848339)|Acrylic → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|
|13|4573643361693<br>KMT20261101|arma bianca|JAN证据链 → 渠道官网 → 日文名回退 → BOX范围核验<br>[详情](https://amnibus.com/products/detail/121311)|アクリル → 亚克力|通过；当前失败原因：无。清除尺寸；核验缓存JAN链|
|14|4573643326883<br>KMT20261101|arma bianca|JAN证据链 → 渠道官网 → 日文名回退 → BOX范围核验<br>[详情](https://amnibus.com/products/detail/118131)|紙、ブリキ → 纸、马口铁|通过；当前失败原因：无。现场误报查无已修复，联网复测通过|
|15|4573643326920<br>KMT20261101|arma bianca|JAN证据链 → 渠道官网 → 日文名回退 → BOX范围核验<br>[详情](https://amnibus.com/products/detail/118133)|紙 → 纸|通过；当前失败原因：无。原文、身份及快照核验通过|
|16|4573643326906<br>KMT20261101|arma bianca|JAN证据链 → 渠道官网 → 日文名回退 → BOX范围核验<br>[详情](https://amnibus.com/products/detail/118132)|紙 → 纸|通过；当前失败原因：无。原文、身份及快照核验通过|
|17|4550621569456<br>KMT20261101|movic|快速站未解决 → 官网/停站核对 → 独立Neowing精确JAN详情<br>[详情](https://www.neowing.co.jp/product/NEOGDS-1056488)|本体 : ポリエステル・鉄・PVC ボールチェーン (金属) → 主体 : 聚酯纤维・铁・PVC 珠链 (金属)|通过；当前失败原因：无。保留本体/珠链组件；补珠链译词|
|18|4550621759550<br>KMT20261101|movic|既有官方详情证据回放（不重新访问停站域名）<br>[详情](https://www.movic.jp/shop/g/g04161-00213-00162/)|PP製 → PP塑料制|通过；当前失败原因：无。复用浏览器响应快照，正确解包JSON文本|
|19|4550621675287<br>KMT20261101|movic|MOVIC历史503 → 独立METALBOX详情<br>[详情](https://www.metal-box.jp/product_detail/hobby/goods_miscellaneous_goods/900395)|アクリル製、裏面オーロラホロ → 亚克力制、背面オーロラホロ|通过；当前失败原因：无。识别分隔空白的材质标签|
|20|4550621691898<br>KMT20261101|movic|MOVIC历史503 → 独立Hobby Genki详情<br>[详情](https://hobby-genki.com/en/puella-magi-madoka-magica/98176-puella-magi-madoka-magica-memorial-clear-card-collection-6-pack-box-movic--4550621691898.html)|Polypropylene (PP) → 聚丙烯 (PP塑料)|通过；当前失败原因：无。明确Materials字段，聚丙烯译词补全|
|21|4570140158269<br>KMT20261101|Caravan|快速站未解决 → 官网/停站核对 → 独立Neowing精确JAN详情<br>[详情](https://www.neowing.co.jp/product/NEOGDS-1048483)|アクリル → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|
|22|4570140158238<br>KMT20261101|Caravan|快速站未解决 → 官网/停站核对 → 独立Neowing精确JAN详情<br>[详情](https://www.neowing.co.jp/product/NEOGDS-1048480)|アクリル → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|
|23|4549502243455<br>KMT20261101|Chugai Kogyo|渠道官网 → 精确商品编号/名称/套组核验<br>[详情](https://www.chugai-contents.jp/shopdetail/000000015321/ct420/page1/recommend/)|ブリキ → 马口铁|通过；当前失败原因：无。原文、身份及快照核验通过|
|24|4550451387497<br>KMT20261101|crux|快速站未解决 → 官网/停站核对 → 独立Neowing精确JAN详情<br>[详情](https://www.neowing.co.jp/product/NEOGDS-1027387)|アクリル → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|
|25|4570194458827<br>KMT20261101|Bushiroad Creative|快速站未解决 → 独立Tsurumai精确JAN详情<br>[详情](https://tsurumai-hobby.jp/item/4570194458827)|製品素材 本体:PVC → 产品材质 主体:PVC|通过；当前失败原因：无。清除商品规格/版权；不推BOX数量|
|26|4570194459930<br>KMT20261101|Bushiroad Creative|快速站未解决 → 独立Tsurumai精确JAN详情<br>[详情](https://tsurumai-hobby.jp/item/4570194459930)|本体:PVC・ABS/ステッカー:紙 → 主体:PVC・ABS塑料/贴纸:纸|通过；当前失败原因：无。保留本体与贴纸组件；不推BOX数量|
|27|4571696826039<br>KMT20261101|MENEGI|快速站未解决 → 独立零售详情及商品元数据<br>[详情](https://store.shopping.yahoo.co.jp/honyaclub/4571696826039.html)|ブリキ、PP → 马口铁、PP塑料|通过；当前失败原因：无。从商品描述元数据提取明确素材字段|
|28|4530430565337<br>KMT20261003|Shueisha|相关渠道 → JAN官方商品页<br>[详情](https://jumpcs.shueisha.co.jp/shop/g/g4530430565337/)|アクリル → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|
|29|4530430565320<br>KMT20261003|Shueisha|相关渠道 → JAN官方商品页<br>[详情](https://jumpcs.shueisha.co.jp/shop/g/g4530430565320/)|アクリル → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|
|30|4530430565344<br>KMT20261003|Shueisha|相关渠道 → JAN官方商品页<br>[详情](https://jumpcs.shueisha.co.jp/shop/g/g4530430565344/)|アクリル → 亚克力|通过；当前失败原因：无。原文、身份及快照核验通过|

## 异常处理与证据边界

- 历史真实错误记录：Tower HTTP403一条、COCOLLABO HTTP429一条、MOVIC HTTP503两条；保留记录的URL、时间、原文件与SHA。原记录没有完整错误响应体，不能称为已复现当时响应正文。
- Anime Store历史停站状态保留。93个条目带429/停站标签，不当作93次服务器429；没有重启清空停站状态。
- 403/429处理用离线异常注入验证：同站首次错误后停止、第二次不发请求、其他站不被停掉，保存错误响应字节/哈希/Retry-After。注入数据只用于测试，不属于30商品业务材质。
- 查无、无材质、身份未核实、解析失败、HTTP请求失败和环境权限阻断分别验证；找到了不匹配的官网详情不再笼统写查无。
- JAN-less AMNIBUS必须核验已保存JAN来源的真实结构化商品记录、标题和SHA，以及对应官网URL。只凭相似名字不自动发布；原有经过独立审核的缓存仍按其来源层级使用。

## 本轮实际修复

1. 材质字段边界：优先读取明确dt/dd、th/td、li/p中的材质字段；不吞入尺寸、颜色、作者、商品规格、版权、网页JSON和导航。
2. 保存响应格式：支持既有MOVIC浏览器JSON字符串/行号文本、分隔空白的“素材”标签和商品描述元数据；复用原提取器，没有开发新查询器。
3. AMNIBUS单位括注不再导致已找到的商品详情误报查无；无JAN页面仍须可靠证据链，缺链保留身份未知。主入口读缓存时同时核验二级JAN快照。
4. 补齐明确的Polypropylene→聚丙烯、ボールチェーン→珠链及贴纸/背面等字面译词，保留组件、百分比和未知词，不按品类猜材质。
5. 错误存证保存响应体、SHA及Retry-After；深层Windows运行目录支持长路径。WinError10013归为环境权限，不能当成网站失败。

## 回归、保全和未完成项

- 自动回归：150项实际执行，150通过，0失败、0错误、0跳过；包含本轮12项回归方法。原提供器20项规则自检另通过，不与unittest重复累加。
- 原业务Excel、旧session、数据库release及正式Skill清单的保全SHA已核对；所有新增响应、测试运行及报告都在当前隔离工作树。没有调用confirm，没有生成第二阶段计算或海关外发表。
- 通过的是30样本的材质核证与所覆盖路线；现有prepare自动提供器仍只调度5站。MOVIC/Neowing/METALBOX等本轮验证的是既有定向查询与已审核证据回放，尚未全部接入无人值守自动分流。没有把这项缺口包装为完整自动链已通过。
- 可以继续分批扩展SOP查询验证；尚不能仅凭本轮宣告1967行全批无人值守查询验收完成。

后台证据：acceptance-30.json（逐项路线、原文、译文和身份依据）、source-lock.json（来源SHA）、live-results.json与live-after-fix-results.json（8次实际请求）、network-permission-blocked.json（权限阻断）、regression-final.json与日志。用户无需修改这些技术文件。
