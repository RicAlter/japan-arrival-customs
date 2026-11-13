# 日本到货完整闭环候选

独立适配层复用 c130a9b 第一阶段、ff05cfb 采购分表布局、A02/A03 回传事务、A04/B00 和 rc.5 双表/ROUND0。原代码、已安装 Skill、正式门禁均不修改。当前仅本机候选；真人 Excel/WorkBuddy 操作未验证。

## 数据流

已登记第一阶段 workflow → 独立 business/synthetic 状态副本 → 原 A03 基础资料回传/指定确认 → 日方更新文件预览/明确提交 → 可编辑计算审核 Excel → 服务端重算/明确确认 → 原 B00 事务/A04 门禁 → 原 rc.5 两张受控草稿。

`loop.updates` 按箱号、Ref、JAN、日文品名、原HS字段及产地完整身份唯一匹配。重复身份只接受同身份的明确行关联，不能按JAN猜跨商品或自动拆分/合并。变更和新行保留待核，已确认且上下文未变基础字段继承。价格/数量/金额变化对比上一个有效日方文件版本，原文件按SHA归档。箱重、总数总额不一致或未关联新行阻止交付。新增商品暂需先整理基础资料并建立可靠关联，不自动拼接。

采购价只有原有基础字段确认及原计价单位证据有效时才可成为最小单位价格候选；另须明确确认同币种、税/折扣、产品版本以及最小/最大计价口径可比。价格比为最大价/最小价，以原始精度精确求有理数；非正、非整数、缺依据均转人工。人工不能通过改成整数绕过不可靠价格比。日方Qty须明确为最大计价单位；盒数仅在Qty明确为盒时沿用，否则需独立盒数。物理每盒最小数与每最大单位换算倍数独立保存。旧接口无法精确表示的内部数量/单价转人工。采购数量只读查询，绝不按日方Qty兜底或作为计算操作数。规格尾部来源采购数量原文保留。

审核表Excel公式提供即时参考，服务端以已登记原始事实重算，不信任客户端缓存；原JAN、来源价、公式及身份列只读。人工金额调整需出处，执行价继续旧ROUND0，差额保留而不自动调平。申报名称/品牌为独立公开字段，内部YD/渠道不进入海关白名单。税率无默认值，参考税费不等于专业归类审核。两表共同验证通过才交付，正式外发保持关闭。

## 本机调用

在本目录使用已配置 Python：`python -m loop --help`。命令支持 `--result-file`，大预览写JSON后按其明确范围处理。确认步骤均需当前完整哈希、`--explicit-confirmation` 和实际依据，不提供默认全表批准。

1. `fork --workflow <已登记workflow.json> --root <新目录> --mode business`
2. `basics-preview --root <目录> --file <业务回传.xlsx>`，随后 `basics-plan --preview <id> --selection <指定范围.json>`，`basics-commit --plan <id> --confirmed-hash <id> --explicit-confirmation --reference <依据>`。
3. `update-preview --root <目录> --file <新日方11列.xlsx> --role actual_price_update --reference <来源及价格角色>`。`update-commit --preview <id> --confirmed-hash <id> --explicit-confirmation --reference <依据>`。原售价文件只能用 `initial_price_observation`。
4. `review-export --root <目录> --output <审核.xlsx> --node <配置Node路径>`。
5. `review-preview --root <目录> --export-id <id> --file <回传审核.xlsx> --reference <修改审核范围> --price-basis-reference <币种税折扣版本及最小最大口径依据>`。
6. `review-confirm --root <目录> --preview <id> --confirmed-hash <id> --explicit-confirmation --reference <明确计算确认>`。
7. `render --root <上一步compute_root> --output <新双表目录>`。

审核存在阻断行、缺价格可比依据或旧版本冲突时，不确认部分表、不交半份双表。同一次提交幂等；新价格或上游资料变化使旧计算失效；新计算选择阻止旧计算结果再次交付。基础资料和计算确认均只是本地宿主显式事件，不能声称已核验真实人员或专业审批。

隔离模式用 `--mode synthetic` 和 `synthetic_actual_price_update`；文件、状态、审核和草稿均标记SYNTHETIC，不能升格为business。当前真实状态确认0、实际更新未收到。真实验收只覆盖第一阶段原表与受控回传技术路径，后续完整演示属于隔离测试。

末列S含601条盒规的19列独立核对版仍是参考附件，未切换原18列受控workflow，不支持作为通用19列原表导入或直接受控回传。第一阶段可提供18列待预览参考修改副本，所有预填变化需走A03明确范围保存；不覆盖已登记底稿。

## 验证与追溯

`python -m unittest discover -s tests -v`；完整1275行回放需 `LOOP_REPLAY_DIR` 指向私有隔离输出根。测试不包含真实业务自动批准。原有193项回归独立运行，依赖锁保护旧代码；运行代码锁和每个审核计划的代码SHA检测候选代码变化。私有数据/状态/回放证据不入Git。

本候选仅适配已验证KMT 11列入口与既有第一阶段18列回传。价格比不可靠、变更商品身份、单位复杂或无法精确表示的旧接口数值保留人工处理；没有新增通用计算引擎、拆分合并、专业归类规则或在线审批UI。
