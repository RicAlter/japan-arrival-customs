# 项目总览

业务交付层 business-interaction 负责 prepare、唯一20列表、资料关联、回传及完整性检查。catalogue-pack-loop 与 business-loop 复用 A03/A04/B00、rc.5/ROUND0 计算依赖；这些依赖不改写。

集成提交通过 Git 合并 be90fb9 与 1e53292 的已验证分支，公共祖先068ddf2。包含98技术冻结、订单价/标色、pcs、DG、带图回传、关联材质原文、多站材质提供器。旧实现保留以支持依赖和历史复现，不能当并行开发主入口。

新会话从 START_HERE.md 开始。正式Skill、历史session和发布资料库独立于开发候选，不自动安装或切换。

