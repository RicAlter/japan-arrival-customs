# WorkBuddy / Python 边界和审核协议

Python 3.12及以上，依赖requirements.txt中的openpyxl 3.1.5。WorkBuddy现有环境回执已有Python和Excel证据，本版无需重跑环境探针。此包不包含实际业务资料、审核人配置或已确认的业务规则。

## 调用

在Skill文件夹内执行，所有路径作为独立命令参数传递，不能拼接未转义用户文本为shell代码：

```text
python scripts/run.py --output <独立输出根目录> import-stage3 --source <第3步Excel> --currency JPY --quantity-unit <单位或空字符串>
python scripts/run.py --output <同一目录> review-package --batch <批次ID>
python scripts/run.py --output <同一目录> apply --batch <批次ID> --request <请求JSON> --permissions <可信角色JSON>
python scripts/run.py --output <同一目录> status --batch <批次ID>
python scripts/run.py --output <同一目录> customs-preview --batch <批次ID>
python scripts/run.py --output <同一目录> calculation-preview --batch <批次ID>
python scripts/run.py --output <同一目录> check-amounts --batch <批次ID> --proposed <完整ID到金额映射JSON>
```

仅开发回放可增加`import-stage3 --p0-evidence <reports/p0目录>`，程序要求源SHA与冻结样本一致，再挂接已有争议线索，不重跑P0审计。安装包运行不依赖该目录。重复导入既有批次拒绝覆盖，改用已有批次ID读取；源文件变更须建立新批次。

输出为版本化JSON审核中间文件；不是最终业务单据。失败返回码2和`status=rejected`。确认成功返回新revision与state_hash。每次保存新快照、刷新head并重读校验，保留旧快照。单写锁和哈希版本检查拒绝并发/陈旧覆盖；异常中断遗留锁需核实后人工移除，不能自行忽略。

calculation-preview仅对显式确认的价格/盒规及税费参数演算，其他值保持pending；不产生正式单价。check-amounts必须覆盖所有技术行ID，报告行、商品与批次差异，`passed=false`表示金额核对未通过（命令成功生成核验报告不代表核验通过），不修改单价。

## 正常批量与争议流程

1. 导入后的所有域都是未确认。源3中文名/品类/渠道/YD仅预填，申报名称不从内部名复制。
2. 业务补录必要资料；`frontend_status`为exists或absent，确无前台/YD分别写原因。可用supplement-group一次提交明确多行的预填/补录内容，不要求每行点击，也不自动确认。任意行含非法字段/未知行则整次拒绝。每次补录都会使该行商品确认失效；归类/申报名称变化还会使税率确认失效。补录后重新导出审核包。
3. 审核包给出所有明细、明确ordinary_ids与individual_ids、源证据、缺项、争议、版本及全状态哈希。WorkBuddy向业务展示这些内容，业务明确选择批量范围和确认后，才能构造确认请求。不得把“未回复”或“AI找到唯一结果”当成已确认。
4. 普通行资格只针对商品域：基础资料完整、尚未确认、无product/identity争议即可进入ordinary_ids；纯price/material/packaging/tax争议不阻断商品批量确认，其原始争议与专业确认状态不变。未知/缺少domain的争议保守留individual_ids。一次batch请求只允许普通行的非空子集。混入商品/身份争议D1、未知行、缺项行、重复行、已确认行，或审核包被改动/已过期，整次失败且状态不变。
5. individual一次处理一行，必须说明每项商品/身份争议的依据，不要求替价格/材质/盒规/税率争议作结论；兼容旧请求中附带的已知专业争议说明，但这些说明不会批准或消除专业争议。商品确认只解决product域争议；身份及各专业争议依旧待对应审核。D06改码/版本拆分目前不能自动解除，留独立映射合同处理。
   batch和individual均拒绝直接再次确认已确认商品，原确认依据和状态SHA不变。纠错沿用“带依据及权限的补录修改→商品确认失效→导出新审核包→重新确认”，历史快照和events保留原确认。升级至0.1.1后重新导出审核包，无需迁移明细或改变JSON字段结构。
6. 价格审核只确认绑定的第3步金额及单位，不能改价。专业域通过approve-domain单独提供完整参数/适用context及依据，角色不符拒绝。没有证据的材质/盒规/税率保持待确认。
7. status始终显示P1-A正式输出禁用及集成门槛。所有行保留在批次中，不为满足放行条件静默排除争议商品。

角色配置由业务负责人/管理员确认维护：`{"实际审核人": ["business", "identity", "amount", "material", "packaging"], "实际关务": ["customs"]}`。实际角色分配尚待D08确认，不附默认可用人名。该JSON是本机可信配置，actor为操作者声明；不是登录鉴权、签名或多人防篡改系统，不能把它当作身份验证证据。

## JSON请求

共用字段：`state_hash`（最新全状态哈希）、`actor`、`evidence`。业务确认来源需可追溯到业务实际回复或签核资料，AI不能伪造。

| action | 另需字段 |
|---|---|
| supplement | row_id、values（只允许product字段） |
| supplement-group | items={技术行ID:该行values}，一次成组补录，仍需重新批量确认 |
| confirm-products | package（完整未修改审核包）、row_ids、mode=batch或individual；争议需resolutions={争议ID:处理依据} |
| approve-domain | row_id、domain、payload；参见数据合同及core.py的显式参数校验 |

`approve-domain`支持identity、price、material、packaging、tax，分别需identity、amount、material、packaging、customs角色。price的payload必须与该行authority的amount/currency/quantity/quantity_unit完全相同。identity只接受version/specification，不接受改写code。材质/盒规/税率payload的context必须与已确认的code/version/specification完全相同。

## 安装与集成验收

解压后得到一个`japan-arrival-customs`主Skill目录，scripts与references随包携带；开发目录之外运行不依赖analysis或reports。当前只验证包结构及独立Python执行，不宣称已在WorkBuddy原生安装/触发。

P1集成验收前只补两项必过证据：①原生触发本Skill的界面/调用记录；②将D1混入普通批量，保留原始拒绝信息、进程返回码、操作前后状态哈希且哈希相同。开发单测里的D1拒绝不能替代WorkBuddy实测。原有43离线、24回传证据继续保留，不重跑其他已通过项目。
