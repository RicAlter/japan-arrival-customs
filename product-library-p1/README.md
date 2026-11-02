# 商品资料库 P1 独立开发

基线：`RicAlter/japan-arrival-customs` 的 rc.5 提交 `4773446439e35968e592df702f86b0a411dd1f20`。本目录提供真实来源导入与逐行批量商品查询；不导入报单运行时，不修改rc.5计算引擎、旧版本或正式输出门禁，不安装/测试WorkBuddy，不接网站。

## 兼容与原库保护

现有B4-1来源库使用`metadata.source_bundle_schema_version=1`，基础商品表另有`schema_version=3`。rc.5旧`ProductLibrary`只支持基础v2且构造时可能迁移，不能直接用于该原库。本模块复用B4存储、来源合同及适配公共组件，直接读取B4来源观察，不重新建库、不降级、不调用旧迁移路径。

`inspect`和`query`通过SQLite `mode=ro`与`query_only=ON`打开现有库。导入仅允许`clone`显式创建、带源路径/哈希标记的独立工作副本；源库和输入前后哈希核验，拒绝覆盖副本或输出。没有生产`init`命令，也不提供D1导入/回写入口。撤回本阶段只需停用此分支及工作副本，原库不需要回滚。

## 独立入口

Python 3.11+，安装`requirements.txt`；从本目录运行。路径使用实际本地受保护目录，不能提交私有参数文件：

```powershell
python -X utf8 -B -m product_reference inspect --database <原库.sqlite3> --output <新核对结果.json>
python -X utf8 -B -m product_reference clone --source <原库.sqlite3> --destination <新工作副本.sqlite3>
python -X utf8 -B -m product_reference collect-source --request <显式列名来源请求.json> --output <新来源包目录>
python -X utf8 -B -m product_reference collect --file <运营表.xlsx> --mapping mappings/kmt-internal20.json --source-id <来源ID> --source-version <来源版本> --authorization-reference <用户授权引用> --output <新来源包目录>
python -X utf8 -B -m product_reference import-bundle --database <工作副本.sqlite3> --bundle <已核验来源包> --authorization <真实授权记录.json> --output <新导入结果.json>
python -X utf8 -B -m product_reference query --database <原库或工作副本.sqlite3> --request <批量请求.json> --output <新候选结果.json>
python -X utf8 -B -m product_reference query --database <原库或工作副本.sqlite3> --file <运营表.xlsx> --mapping mappings/kmt-internal20.json --output <新候选结果.json>
python -X utf8 -B -m product_reference evidence --database <库.sqlite3> --observation <观察SHA> --file <包内证据相对路径> --output <新证据.json>
```

采购订单来源导入仍须提供既有逐行`--purchase-policy`；有效采购数只是待确认候选，撤销/砍单等原因不删除。来源V1合同、部分失败子包、用户授权及导入前备份沿用B4规则。导入幂等，既有观察及人工纠正不覆盖。

批量请求示例（全部合成）：

```json
{"items":[{"row_id":"synthetic-row-1","code_raw":"00123","code_type":"source_identifier","jan":null,"japanese_name":"Synthetic Japanese","version":"v1","specification":"red"}],"exclude_source_ids":[],"exclude_file_sha256":[]}
```

返回数组保持输入顺序，含原行ID、商品候选、五项身份比较、材质参考、字段冲突/缺失、源文件/表/行/字段证据和未解析源值。重复编码的不同版本、重复查询和无码行都保留，不按编码字典折叠。

编码按源字符串保存，不补零、不强转13位、不凭长度认定JAN。`jan`走独立JAN命名空间；若确需跨命名空间查候选，必须提供`namespace_aliases:[{"from":"JAN","to":"source_identifier","reference":"明确依据"}]`，别名记录随结果返回。不把中文译名冒充日文身份，也不模糊名称合并。

相同五项观察身份且有编码和日文名/版本/规格依据时可标`exact_reference`；这只表示来源字段一致，缺失版本仍显式缺失，不证明未来版本适用。已知身份差异进入`rejected_candidates`，缺失依据只给候选；同码多身份保留歧义。无码只能按明确日文名找候选，不建立永久合并。所有结果`automatic_approval=false`，历史材质不升级官方事实或最终申报选择。

## 显式Excel映射

`mappings/`提供第3步、20列内部运营表、日方原始表三种独立配置；按已核对的工作表/表头和列字母读取无名列，不猜列、不依文件名选角色。身份、版本、规格各自保留。真实KMT的F混有款式、整盒及本批数量，不是可直接等同开订SKU的稳定规格，因此原样存为`packaging_label`参考，不删尾部数字、不从中推导版本/规格/换算系数；稳定规格缺失仍列缺失。其他来源有明确SKU时可显式映射`specification`。所有原行单元格、公式、错误值及数字格式留证；映射字段为公式/错误时值留空，报告`unresolved_source_value`，不猜缓存或解析外链。宏拒绝，旧表外链元数据留证但不访问。超过512列的异常宽表拒绝静默截断。

## 验证与隔离

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B validate_private.py --config <私有本地验证配置.json>
```

私有验证配置包含`database`、`output`、`protected_files`、`authorization`、`training`（file/mapping/source_id）、`holdout`（file/mapping）及可选既有来源包重放。脚本分别保存原B4查询、训练导入后跨批查询、同批诊断；排除留出文件哈希，检查原库/原表/冻结文件不变。名称一致率只是独立字段对照，不能替代人工标注准确率；回溯跨批检索不代表未来批次覆盖率。

本目录无业务数据，不提交数据库、原表、来源包、授权/请求、日志、真实候选、截图或逐行缺失清单。详细真实库核对、数据缺失清单和实样报告只留本地。五站接口见[FIVE_SITE_INTERFACE.md](FIVE_SITE_INTERFACE.md)。
