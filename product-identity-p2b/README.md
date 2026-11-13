# P2-B 离线商品身份补充

基于 P1 `1ea746a`、P2-A `eea43c4` 的独立开发模块。只读取本地既有资料，复用 P1 的数据库只读/显式副本接口；不加载网站适配器、rc.5 报单引擎或 D1。P2-A 授权门禁保持不变。

## 范围和身份规则

- 编码和编码命名空间保持原值；JAN 不能仅凭13位长度推定。编码相同只是候选，还须核对日文名、版本、规格。无码原记录保留，不能补造编码。
- 编码加日文名、有效YD或明确中文名可建立**部分基础资料关联**。已知日文名/版本/规格冲突不自动关联；缺少版本不等同“无版本”。完整身份必须有五项依据且没有身份冲突。
- 配置中明示的 SKU/颜色规格可以作为规格候选；本批 F 款式/盒数文本仅作 `packaging_label`，不删尾部数字推导规格，不把系列列或品名中的数字自动当版本。
- 每项保留原文件哈希、工作表、原行、单元格及原值。公式/错误值留证但不猜缓存。开订、订单、商品档案和历史到货的映射由维护者核对表头后显式配置，不猜文件角色。
- 同批上下文、独立历史资料分开统计。当前批次已有的材质不能算作新增跨批覆盖；未独立人工标注，不称准确率或零错误率。
- 人工表按身份和相同业务上下文合并重复操作，保留全部原行关联。主表只列待补项；第二页是可筛选的原始候选与来源。完整原候选、被拒候选和字段证据保留在私有计划中。

## 本地入口

Python 3.11+，依赖沿用相邻 `product-library-p1/requirements.txt`。从本目录运行；所有参数文件和输出必须位于私有本地目录。已有输出拒绝覆盖。

```powershell
python -X utf8 -B -m offline_identity collect --config <本地映射配置.json> --output <新来源目录>
python -X utf8 -B -m offline_identity prepare --p1-results <P1跨批结果.json> --facts <来源目录/facts.json> --context-config <本地映射配置.json> --p1-database <P1对应快照.sqlite3> --output <新计划.json>
python -X utf8 -B -m offline_identity copy-register --source-database <P1对应快照.sqlite3> --destination <新身份资料副本.sqlite3> --plan <新计划.json> --reference <本次资料维护授权引用>
python -X utf8 -B -m offline_identity book-model --plan <新计划.json> --output <新补充表模型.json>
node build_review.mjs --model <新补充表模型.json> --output <新人工补充表.xlsx> --previews <技术预览目录>
```

Excel 作者使用已配备的 `@oai/artifact-tool` 公共API；不下载依赖。生产调用不传 `--edits`（该选项仅供合成隔离夹具）。模型和工作簿都含私有候选，不得提交版本库。

配置结构见 [CONFIGURATION.md](CONFIGURATION.md)。超大表按行流式读取；对错误的 `A1:A1` 维度重新读取实际行，按明确列映射限制列宽，不加载整表到内存。

## 人工填写与维护回写

1. 在“人工补充”填写浅黄项；资料不足继续留空。到“候选与来源”按商品编码筛选，填写来源编号，多个编号用逗号分隔。候选原文不代表身份已确认。
2. 填写有明确依据的日文名、版本、规格或材质参考；写明确认依据，在最后一列填“确认”。选择单一明确来源可复用其中的品牌、品类、渠道等基础字段。原编码、原候选、来源页不得改写；允许按稳定编号筛选/重新排序。
3. 填写本身不写库。维护侧生成预览，检查来源、身份差异和待缺字段，再显式确认该预览哈希。维护人员引用由调用侧提供，Excel 不自报可信身份。

```powershell
python -X utf8 -B -m offline_identity preview-return --database <身份资料副本.sqlite3> --plan-id <计划哈希> --workbook <填写后的表.xlsx> --output <新预览.json>
python -X utf8 -B -m offline_identity apply-return --database <身份资料副本.sqlite3> --preview <新预览.json> --confirm-preview <该预览哈希> --operator-reference <维护侧操作人及确认依据引用> --output <新维护结果.json>
python -X utf8 -B -m offline_identity batch-query --database <身份资料副本.sqlite3> --queries <新批查询.json> --batch-id <当前查询批次号> --output <新候选.json>
```

回写重新读取原回传文件和来源哈希，检查副本状态、只读字段、编号范围和冲突；拒绝公式/宏/外链、错误来源、篡改的预览、旧预览和空确认表。重复提交同一预览幂等。未确认字段不补值，部分补充不冒充完整身份。

副本仅新增 `p2b_facts`、`p2b_plans`、`p2b_basic_events` 表。B4 原观察不覆盖。维护事件通过独立 `batch-query` 读取，不向原 B4 或 D1 发布，不改旧 P1 查询语义。材质始终 `reference_only/material_approval=false`，基础身份确认不能批准申报材质。没有正式输出入口。

本入口的范围是已登记的离线事实与基础维护事件；不宣称原B4全部商品已经补全。其余商品的原库候选仍由P1的全库批量查询入口提供，再按同一离线来源流程建立补充计划。

回滚：停用本分支/本身份资料副本，继续使用原 P1/P2-A 即可；原库无需恢复。误填尚未回写时重新从原模板填写；已回写后保留原副本作证据，由原快照建立新副本重放正确确认，不直接删改历史维护事件。

## 验证和隐私

```powershell
# P2B_NODE 指向具备 artifact-tool 的已配备 Node，或确保 node 可用。
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B validate_private.py --config <私有真实验收配置.json>
```

单元测试使用合成身份和临时微型 B4 副本。真实回放分别报告完整身份、部分基础关联、规格缺失、原候选冲突、跨批材质参考、同批已有材质、原行/去重人工项，不把同批命中当新批覆盖。不通过虚填版本制造提升；真实人工尚未回传时，维护事件为零。

私有数据库、原表、映射路径配置、补充表、逐行候选、计划、真实回写、日志与截图全部留本地，不提交 GitHub。不安装或测试 WorkBuddy，不访问五站，不修改任何冻结版本、报单计算或正式关务门禁。
