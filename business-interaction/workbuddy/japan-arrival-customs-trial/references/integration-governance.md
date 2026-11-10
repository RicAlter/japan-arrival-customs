# 集成治理与已确认业务规则

唯一开发基准为 codex/unified-development-20261110；确切SHA与可运行入口由项目根 outputs/统一开发候选_当前.json 绑定。新Codex会话先读项目 START_HERE.md、BUSINESS_RULES.md、SOP_INDEX.md。

采购价以适用有效订单为先，普通多YD正常；币种/单位/实质款式冲突和特典重复码单独核对。精度差不作价格冲突；pcs/DG关联须独立核商品规格，保留盒价单位和CNY元标签。正常白底，真正待改缺项浅黄、冲突浅红。

材质遵循 material-query-sop-v2.md 与 linked-material-original.md：具体商品原文优先，缺失允许YD级材质集合参考并记录层级，不将集合拆猜为SKU材质，不覆盖O；已有非空R受保护。100商品多站联网零有效材质是未完成业务效果问题，200响应或技术回归通过不代表该问题通过。

新测试显式选择数据库release及SHA；正式Skill、历史session及数据库原件保持各自绑定。历史确认表只作比对，不反向补填。

发布必须通过 governance/release.py 的匹配、颜色、pcs/DG、材质、大图回传、数量、交付保全及计算/包装套件，并保存 governance/audit.py 的三批实样与历史材质证据审阅结果。源代码逐文件SHA、锁定依赖和完整源码包一同交付。旧模块保留依赖，旧会话只读登记，不能将模拟回传视作真人批准。
