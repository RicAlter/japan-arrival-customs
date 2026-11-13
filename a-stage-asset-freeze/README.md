# A阶段规则与本地资产固化

独立辅助代码 `0.1.0-local-assets`。不修改既有A01/A02/A03/A04/B00、计算引擎、正式门禁或商品库；不包含私有资料。WorkBuddy原生、拆分合并、B计算与正式双表仍未验证或开放。

- `a_assets.rules`：商品名称必须同来源JAN+YD并取商品名称字段，禁止以SKU/角色名称兜底；DG+JAN仅支持YD；材质保留链接原文并分别记录具体商品类型、选择依据及参考状态。
- `a_assets.archive`：仅按显式文件清单原字节复制、逐份前后SHA核验、同内容别名去重、冲突拒绝与旧版本精确定位。不会递归把整个资料目录当业务输入，不按修改时间选“最终版本”，不删除或移动原文件。
- `RULES.md`：本轮规则边界和已证实状态；真实批次记录、截图、表格、运行状态与完整源码快照另留本地私有资产库。

独立Python标准库运行，无新增安装：

```powershell
python -B -m unittest discover -s tests -v
python -B -m a_assets archive --request 私有显式清单.json --destination 新归档目录
python -B -m a_assets verify --manifest 归档目录/资产索引.json
```

不提供确认、批准、金额调整或进入B计算的接口。新辅助代码尚未接入冻结生产实现；它用于本轮资料和规则固化、显式归档与后续维护。
