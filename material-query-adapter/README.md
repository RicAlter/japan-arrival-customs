# 材质查询只读适配层

兼容锚点fb21d4c，仅新增本目录；不回退e087ecc后续资产，不修改业务入口、计算引擎或正式Skill。

统一流程：最新商品资料库只读backup固定版本 → 精确SKU资料优先 → 人工材质已有值则保持 → 缺材质/具体SKU不明才查插件 → 保存原始结果和重新核对身份 → 仅后台候选JSON。不会写Excel、资料库或A03，不增加业务必填表。

运行`python adapter.py --help`查看参数。输入为JSON列表，每条包含jan/name_ja/name_zh/spec/yd/brand/source_sha256/source_sheet/source_row，manual_material非空将跳过插件。插件路径、数据库路径、输入、独立state及输出通过参数显式指定。默认离线；支持人工页面快照。所有候选不自动采用。

缓存绑定JAN、名称、规格、YD、品牌、来源SHA/页/行及库快照，不能以JAN单独采用；缓存命中仍重新核对。页面无JAN、版本信息不足保持身份未明；明显名称/JAN/vol数字版本冲突保留冲突。原文、译文、URL、时间、内容哈希、摘录、插件完整输出、固定库来源全部保留。

联网还需access-review指定robots正文、审核过的站点和路径、请求预算。默认传输层拒绝未审核站点，记录网页正文和请求证据。站点共享403熔断/429退避；查询错误非阻断并继续下一行。不要使用上游batch直接处理业务输入，其去重主要按JAN。

19列N是人工材质、R是材质参考；本批20列O是人工材质、S是材质参考。目前没有改表，也没有将R参考品类替换为网络材质。WorkBuddy调用参数在工作区reports/material-plugin-20261106/workbuddy-command.json，仅离线准备，未安装/原生验证。

上游ZIP实际通过8项CLI接口检查、63项离线测试；本适配层12项检查通过。详细报告和固定样本在reports/material-plugin-20261106。合成夹具不算本批新增材质。此前真实商品联网测试被自动审批拒绝；用户随后明确批准仅公开JAN发往Anime Store/HobbySearch、最多4次的有限测试，实际结果见authorized-test-20261106/。该授权不扩大为全批次或其他站点授权。
