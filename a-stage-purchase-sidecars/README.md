# 第一阶段采购查询分表

按用户截图所示范围，将旧候选主表Q采购数量、R计价单位、S数量单位移出。G原采购价参考保留，M/N人工品类和材质保留，T/U的AI参考移至主表最后Q/R。主表18列，原A:P单元格原字节、公式/cache、行高/原序、箱重、链接及其他部件保持。

另交采购查询表及采购数量核对表。查询表1275行，数量核对第一页80行原数值不同，第二页93行来源缺失或重复；1102行仅原数值相同。未核实单位和本批适用范围，不把数值不同当作已确认错数/短到/超到。无可靠采购数就留空，不用日方Qty兜底，不重复分配共享采购记录，不作盒规换算，不汇总采购数量。表中差数仅为两个原数值的减法。

两份附表是发出时的来源查询快照，不是主表的确认回传文件；来源文件、工作表、格坐标和原规格文字保留，不代表后续主表已保存的当前值。主表采购价可改并保存待核；明确采用仍须有独立出处和原计价单位，宿主通过范围依据传入`source_ref`和`unit`，不把未知单位或盒/套价格直接当最小单位价。不要求业务在主表补单位栏。

原11列转换结果直接复用，原`a-stage-first-phase`全部源码保持。A02比较、A03范围计划/CAS/幂等/历史实际执行冻结代码，只在本新版本模块命名空间提供布局对应的模型接缝。旧21列底稿及状态不覆盖；新版本采用不同的发出标记和保存目录，旧版/附表不能当新主表回传。原A04/B00、ROUND0和双表引擎不改，不安装正式Skill。

使用现有Python和Artifact Tool运行：

```powershell
$env:PYTHONPATH=(Resolve-Path a-stage-purchase-sidecars).Path
python -m separated status --workflow 本地workflow.json
python -m separated preview --workflow 本地workflow.json --file 修改的主表.xlsx --expected-hash 当前摘要
python -m separated plan --workflow 本地workflow.json --preview 预览ID --selection 明确范围.json
python -m separated commit --workflow 本地workflow.json --plan 计划ID --confirmed-hash 已展示摘要 --explicit-confirmation --reference 真实确认出处
```

范围JSON由宿主管理；业务只修改主表并回传、明确保存范围。本批技术测试使用临时状态克隆和SYNTHETIC出处，未收到真人回传，实际候选revision0/确认0，业务闭环未验证。独立查询表不增加主表必填项目。当前只完成本布局调整，第二/三阶段保持暂停。

测试：`python -m unittest discover -s a-stage-purchase-sidecars/tests -v`；`SEPARATED_WORKFLOW`仅在需要真实1275行隔离回放时指定。4项纯模型检查及1项实样测试通过，实样包含29项检查；真实数据/运行证据不入仓库。
