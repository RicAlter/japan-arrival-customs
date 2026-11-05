# 第一阶段：商品基础资料整理候选

独立`0.1.0-stage1-candidate`。只开发中文商品名、规格、采购单价、采购数量、YD、渠道、品类的整理和回传保存。材质人工栏和AI参考栏保留，材质不是第一阶段必填。

## 复用和隔离

- 实际调用既有KMT原表`v2_register.project_layout()`完成11列到16列基础投影，复用其原字段、公式/cache、箱重保全检查；只支持这份1275行实样，不另建转换引擎。
- 资料继续用P1只读查询及本批已有来源映射。采购单价重新读取真实来源的原精度，保留原规格文字、原币种、原计价单位未知状态和格坐标；不知道单位就不当最小单位价。
- 采购数量单列Q，仅来自独立采购/业务登记记录。一对多重复采购观察留后台不重复分配、不求和；不读取到货J作为采购数量。
- R采购计价单位、S采购数量单位可由同事一次核对；未知单位的数值可保存待核，不能确认为已明确单位的采购值。已确认盒/套单位也不会被标为最小单位。
- 原单位或商品/规格上下文变化后，采购值的当前确认转待复核；原始回执保留，可显式重认同一数值的新单位，不能借单位修改把整盒价格自动改称单个价格。
- 原M/N人工品类/材质保留，T/U为只读AI参考；参考不自动写入人工结果。H留给后续阶段，第一阶段不填写、不调用推导或差价判断。
- A02逐格比较、A03预览/范围保存、CAS、互斥锁、不可变快照、幂等回执和版本历史均执行原文件的方法。通过独立模块命名空间仅替换第一阶段模型接缝，不修改`a_confirm`全局模块，不复制交易/存储实现。
- 新保存目录使用独立版本标记；冻结A04/B00旧入口不能接管该目录。本候选不提供第二阶段日方更新、第三阶段盒规或正式双表入口。

## 开发者运行

使用已配置Python与Node/Artifact Tool，无需安装正式Skill。真实来源、请求和输出仅留本地，不进入仓库。

```powershell
$env:PYTHONPATH=(Resolve-Path a-stage-first-phase).Path
python -B -m stage1 prepare --request 私有请求.json --output 新候选目录
node a-stage-first-phase/author.mjs 新候选目录/technical/authoring-plan.json
python -B -m stage1 finalize --output 同一候选目录
python -B -m stage1 status --workflow 同一候选目录/workflow-manifest.json
python -B -m stage1 preview --workflow 同一候选目录/workflow-manifest.json --file 同事修改.xlsx --expected-hash 当前摘要
python -B -m stage1 plan --workflow 同一候选目录/workflow-manifest.json --preview 预览ID --selection 宿主明确范围.json
python -B -m stage1 commit --workflow 同一候选目录/workflow-manifest.json --plan 计划ID --confirmed-hash 已展示摘要 --explicit-confirmation --reference 真实确认出处
```

业务同事只修改Excel、回传并用对话明确范围；JSON、版本和来源由宿主管理。G采购单价/独立采购数量的明确采用须同时确认其单位。R/S写“原规格单位待核”不算单位已明确。原始Source/Raw不回写，人工改值与原始来源并列留存。

## 验收口径

真实1275行用于候选生成和只读核对；自动编辑/确认保存在隔离的测试服务副本并标为synthetic，不冒充真人确认。候选未收到同事真实回传，业务闭环未验证。`can_enter_b=false`、`formal_output=false`固定；完成本阶段后暂停。

本批品类参考仍位于T，业务M人工栏不自动填入AI结果；可在同一次编辑中明确选择并回填M。材质N非必填，U仅参考。旧A阶段当前指针及其确认历史原样保留；此候选通过独立workflow入口回传，不接管旧状态或正式Skill。

自动测试：仓库根目录执行`python -m unittest discover -s a-stage-first-phase/tests -v`。默认仅模型检查；需验证实样时，将`STAGE1_WORKFLOW`设为本地候选workflow路径，程序只复制状态到临时目录做合成修改/确认。技术读数写入候选technical目录，真实状态不变。测试不依赖下载文件夹，不在仓库内包含业务工作簿或来源数据。
