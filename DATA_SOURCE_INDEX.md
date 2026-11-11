# 数据来源索引

正式发现指针 D:/日本到货海关报单数据/06_统一商品资料库/active/release.json 状态为active_discovery_only，不是正式Skill已切换。新隔离测试显式选择20261110-603d7ba2，原始库SHA603d7ba2db7933534607ca293be63281884880fe997891ad5894af36bfd61853。

SQLite backup产生的快照物理SHA可能不同，必须同时记录原release SHA、快照SHA及读取来源。采购订单/缓存/原表逐份固定，不混入未批准历史最终答案。

三批样本与来源位置见 governance-release/golden-samples.json；旧来源登记见项目根reports/kmt20261002-business-replay-20261109/source-register.json。历史人工值与程序自动补充值分开保留。


本批复现数据角色/SHA见repro/inputs-index.json；真实input manifest、session与Excel只在本机保存，不随GitHub发布。release SHA603d7ba2与本次SQLite快照SHA39603296均须核验，不能互相冒充。缺任何原来源时停止真实回放并说明缺项，不复制历史完成答案填算法结果。
