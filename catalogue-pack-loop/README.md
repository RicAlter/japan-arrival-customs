# 资料库与包装计价接入候选

开发基线d65230a。保留原B4/P1、c130a9b/ff05cfb、A02/A03、A04/B00、rc.5和正式Skill，全部旧源码不变。新增只读资料查询、19列登记及包装单位适配。无新计算引擎、正式放行或外发。

## 来源及登记

使用SQLite只读backup捕获固定库（含已提交WAL），19列核对版原字节另存固定输入；测试不追随其他Agent补数。来源库及工作表不写入。快照自身SHA才是测试依据，保留捕获来源路径/观察SHA，不能用原数据库主文件SHA代替WAL完整状态。

查询目录按JAN+YD返回，具体规格精确一致单独标识；同JAN/YD其他规格另列，不覆盖工作值。目录描述归并不是商品身份批准。采购/渠道/材质/产品卡原值、各来源SHA/位置及冲突均保留，同源同位置的多次适配不当成独立证据。链接材质集合仍需适用具体商品。已有采购原值不因reference_only标签要求全库重审；单位换算、当前采用范围及专业归类按各自依据处理。

19列登记仅变更不可变发出副本的版本属性，工作簿所有其余ZIP成员保持原字节，包括E/F/G/M/N/O/P、Q/R/S、空H、公式/cache、箱重、页签、筛选和隐藏行。M/N已有工作值不清空，来源标为source-derived/assistant-derived、confirmed=false。采购数量保留独立查询，S仅盒规参考。复用separated.service.Service和原A03方法登记/差异预览/范围保存/CAS/幂等；旧18列或未登记19列无法冒充新版本。

若旧受控状态已有保存或人工确认，登记器拒绝重新初始化，保留原状态等待显式迁移，避免丢失记录。本批实际原状态revision0/确认0。新旧目录和指针快照分别保存，不更换原补充资料及资料库指针。

## 包装与计价

内部独立字段：packs_per_box、units_per_pack、declaration_units_per_box、original_quantity、original_quantity_unit、purchase_price_unit、internal_pricing_unit、declaration_unit，以及原文/坐标/适用依据。数量关系和单价单位都要明确，不能仅从S、BOX、全N种、N枚套组、本体=1猜单位。

例如7包/盒×2张/包=14张/盒：原数量B盒→7B包、14B张；原P包→P包、2P张、P/7盒当量。金额A不变：内部单包A/(7B)，海关单张未取整A/(14B)，执行价由原ROUND0处理。采购原价已为每包时不再除7。最大价/采购原单位价的精确比必须符合明确单位关系，非整数/缺价/不相容转人工。原采购价、日方价和含税成本不混用。

内部B00账本保存内部计价数量；原日方Qty及原金额继续留在原始来源，转换链保存在审核事实中。B00原事务/A04检查复用，内部N=内部数量/盒数，税金R=(P+Q)×N保留原语义；海关申报数用另一系数。盒当量不强凑整数。现有Excel引擎无法精确表示的循环小数（例如3/7盒）转人工，不四舍五入塞入旧接口。

审核新增AI每盒包数、AJ每包申报件数、AK每盒申报件数、AL内部计价单位、AM包装依据、AN内部数量、AO内部单价。AI/AJ可预填来源参考，AM未明确时不通过；S参考不会自动确认。Q审核表为可选明确盒数，必须与来源单位/层级一致。单位明确后Excel公式供参考，回传由服务端精确重算，客户端缓存不可信。旧一层简单情况继续调用原审核计算函数。

## 本机运行

在本目录使用Python：`python -m packloop --help`，参数沿用business-loop CLI。登记调用 `packloop.register.register(reference_workbook,parent_workflow,database,output)`；新workflow才允许进入本候选。各确认仍必须指定当前预览哈希、explicit_confirmation和来源，不能隐式批准。真实与SYNTHETIC目录/来源角色隔离，新上游版本使旧计算失效，重复提交幂等，两表一起核验交付。

私有回放使用KMT20261101真实19列固定输入；模拟日方更新和全部后续技术确认明确标为SYNTHETIC。生产Skill不安装，真人业务及WorkBuddy原生操作尚未验证。测试：`PACK_REPLAY_DIR=<本地回放根> python -m unittest discover -s tests -v`。真实资产、报告、测试状态和数据库不入Git。
