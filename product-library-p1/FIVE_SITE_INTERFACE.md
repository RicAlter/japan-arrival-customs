# 后续五站查询接入接口

此阶段只有离线接口，无HTTP、浏览器、网站权限或WorkBuddy安装。五站来自项目历史来源范围：anime-store、amiami、animate、1999、jumpcs；域名只是注册配置，不代表已核验当前站点能力或授权。真实接入时逐站核实权限、查询方式和实际返回。

`product_reference.sites.requests_for(items)`生成各行的五站请求计划；CLI为：

```powershell
python -X utf8 -B -m product_reference site-plan --request <批量请求.json> --output <新离线计划.json>
```

请求含`schema=product-site-query/1`、site_id、query_id、五项identity、domain、`status=not_connected`、`authorization_required=true`、`network_enabled=false`。只传查询身份，不传内部名称、YD、渠道、金额、数据库路径、令牌或最终申报字段。

后续站点适配器按一个逐查询身份响应实现`collect(request) -> response`，响应须经`validate_response`校验：

```json
{
  "site_id":"amiami",
  "query_id":"synthetic-row-1",
  "identity":{"code_raw":"00123","code_type":"JAN","japanese_name":null,"version":null,"specification":null},
  "status":"rate_limited",
  "references":[],
  "approval":false
}
```

状态分别保留`succeeded/no_match/no_data/permission_denied/rate_limited/network_error/unsupported_mapping/partial_failure`。限流、封禁、权限不足或网络错误不能变成“没有材质”。失败不得清空既有参考，是否重试及节流由未来已授权站点组件负责，本模块不伪造网络成功。

成功`references`至少一项，包含url、retrieved_at、content_sha256、identity_quote、material_original、material_translation（未知可null）、evidence_file。URL必须属于所声明站点的HTTPS域，内容哈希是64位十六进制；材质保留完整原文、“等”及全部成分，译文不明时留空。引用须有版本/规格及身份原文依据，JAN匹配不能覆盖页面版本冲突。

未来采集到的离线证据仍需转换成冻结`product-source-bundle/1`材质包，再由维护侧走授权、证据哈希、有效子包与备份导入工作副本。该响应本身不是数据库写入请求，不允许直接写D1、selected material、税号税率、盒规系数、业务金额或正式放行标志。
