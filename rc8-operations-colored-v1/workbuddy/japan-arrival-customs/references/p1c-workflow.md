# P1-C 成组审核与 Python 输出

业务入口仍为一个主 Skill。WorkBuddy 展示来源及明确范围、收集真实人的确认；Python 校验权限、版本、证据并原子保存。AI不能替人签核。

1. `init-contract` 生成首票合同。收集原表采购单位、第3步单位及例外源行、JPY/KG和文件版本、实际责任人与凭据。允许先完成business角色及合同签核以审核基础资料，专业域缺项继续待定。不得将历史表头或样本填法当批准。
2. `identity-checklist --batch ID` 输出所有未连接行、旧新码/名称/数量/箱号和候选原行；相同原行涉及拆分时列出关联第3步源行。64行清单的填写只收集判断，D06映射合同未批准，不能自动修改身份或解除原表争议。
3. `group-review-package --batch ID --domain identity|material|packaging|tax` 给出分组、完整contexts/成员、候选、eligible_ids和exceptions。材质按相同未审材质候选归组；盒规按候选每盒件数/品类/单位归组；税率按历史关税率/品类归组。此分组仅减少展示和人工提交次数，不能证明同规则适用。历史VAT金额不当作VAT税率，也不从盒装总数推断系数。无身份、同域争议、多候选及身份异常进入例外。identity成组仍限明确同款/版本且没有映射争议，规格由人填写。
4. 业务明确选择普通行后 `apply` action=`approve-group`：请求包含当前state_hash、actor、evidence、原样package、group_id、明确row_ids、common及per_row。公共参数和逐行参数禁止同名覆盖；不选的成员保持原状。mater­ial公共参数必须包含context、完整original/translation、source、completeness_confirmed=true。packaging公共参数含context、source_unit/declaration_unit/internal_unit、declaration_factor、pieces_per_box、source；per_row各行必须明确internal_quantity/internal_boxes。tax公共参数含context、formula_version=historical-box-v1、duty_rate/vat_rate、classification/effective_date/tax_unit/source；per_row各行必须明确tax_unit_price。没有税率/盒规证据时不构造批准请求。
5. 跨商品/版本选择时，必须人工确认证据覆盖完整所选身份范围，显式scope_confirmed=true，并在per_row逐行列明context，公共参数不得含context。否则整次拒绝。单一身份可以在common给context。不能因为材质文本或历史税率相同就代替适用范围核实；分组不建立免审规则或可复用历史审批。`record-exception` 请求包含domain、row_ids、status=pending|rejected_candidate及evidence理由；仅使对应域待审，身份/盒规变动使依赖项失效。争议不能混入普通组；收齐证据后用已有单项approve-domain单独核实，同组剩余普通项仍可处理。旧包、修改包、无权限、重复/未知行或参数失败均整次拒绝，不保存部分结果。组操作只提交一次revision和审计事件。
6. 商品基础资料继续原有review-package/confirm-products流程，F1/F2约束保持。专业确认不代替商品确认，无前台或YD按实际原因补录。
7. `render-drafts --batch ID` 默认用Python/openpyxl新建双表，保存后独立OOXML逐格复核和信息隔离检查。无需--runtime或Node。保留显式--runtime旧Node入口用于兼容，默认不调用。Python不提供PNG渲染；WorkBuddy最终验收需实际打开两份Excel检查显示。

填写清单不是签核接口。业务给出明确记录后，由Skill复述范围，按上述受控JSON协议提交；不自动读取Excel里“确认”文字当授权。材质历史审核范围D03、盒规免审D02、税率口径D04待业务决定。正式输出和自动调价继续关闭。

集中WorkBuddy验收：一次安装最终包，保留原生Skill调用证据；真实输入只读建批、部分签核、无YD普通商品批量确认、D1混批整次拒绝并比较前后持久状态哈希、成组专业审核及单独异常、双表保存重开/显示/金额与隔离校验。未实测项目不得标记通过，不重跑P0已通过的环境探针。
