# 离线配置合同

本文件全部示例为合成占位；真实文件路径、映射和授权引用只放私有配置。

`collect` / `prepare` 的配置：

```json
{
  "p1_results": "<P1跨批结果.json>",
  "target_batch_id": "SYNTHETIC-CURRENT",
  "query_workbook": "<当前已确认运营表.xlsx>",
  "query_mapping": {"code_raw":"B","japanese_name":"C","internal_name":"D","yd":"E","material_original":"F"},
  "source_specs": [{
    "file":"<来源表.xlsx>","sheet":"商品资料",
    "headers":{"A":"商品编码","B":"日文名","C":"规格"},
    "columns":{"code_raw":"A","japanese_name":"B","specification":"C"},
    "role":"product_archive","batch_id":"SYNTHETIC-HISTORY","mapping_version":"synthetic-v1"
  }]
}
```

映射列是Excel列字母，表头必须逐格一致。只将明确字段映射到身份；未知字段不映射、同批内容必须使用当前 `target_batch_id`。`query_mapping` 字段列直接列在对象中，读取当前原查询工作簿的第一张表，并核对P1绑定的工作表、文件哈希及原行身份。

原始查询表哈希、行号、编码及日文名必须与 P1 留出结果绑定，不能换另一批数据冒充原验证集。

`batch-query --queries` 读取数组：

```json
[{"row_id":"synthetic-new-1","query":{"code_raw":"00123","code_type":"source_identifier","japanese_name":"合成商品","version":null,"specification":null},"context":{"yd":"SYNTHETIC-YD"}}]
```

每项行号唯一；身份值必须是文本或null，命名空间显式匹配。输出保留行序及关联事实，不批准材质。查询库须为已登记离线资料的工作副本。

`validate_private.py` 的配置：`output`（新目录）、`plan`、`p1_results`、`p1_database`、`database`（新身份资料副本）、`workbook`（真实空白补充表）和 `protected_files`（绝对路径→预期SHA256字典）。私有验证不填真实版本、不产生人工维护事件；源文件、原库及冻结文件前后哈希必须一致。
