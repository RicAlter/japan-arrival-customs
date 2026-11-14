---
name: japan-material-website-query
description: 按固定顺序查网站材质，保留原文、比例和来源，只补空格。
---

使用部署提供的`run.py`和请求模板，workflow固定为`material_query_v1`。

1. `prepare`建立本批任务；`current`查看；`resume`恢复原任务，不换目录。
2. `fetch`一次查当前站点；需要外部网页工具时按`request`获取页面，将原文、HTTP状态和最终网址用`submit`回传。不要自行翻译或按标题猜商品。
3. `waiting/retry`按`retry_after_seconds`稍后继续同一任务；403/429/空响应不能写成未找到。
4. 每完成一块调用`writeback`生成阶段结果，只填空格。无结果须全站查询结束后才以`finalize_not_found`填“未找到”。
5. 只交付返回的business_files；材质结果是网站参考，不是O正式批准。短报完成/待续/网络错误数量，不声称错误已查无。

输入配置和字段映射由工具固定；网址站名没有业务列时留后台，不擅自加列。代码、规则变化交开发处理，来源及人工值变化保留原内容。
