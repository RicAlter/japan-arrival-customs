# A-03 人工确认与版本保存

独立候选 `0.3.0-a03-candidate`，基于A-02补充 `1fcacf1`。原实现、原件、资料库和正式运行版本不变。本模块只保存A基础资料，不实现拆分合并、B计算、双表或D1批准。

## 最小流程

1. `Service(新专用保存目录).register(context_file)`：验证既有A-01/A-02登记，将原工作副本和登记不可变归档，并在独立B2 Store中建立A零版。重复登记相同批次不会重置已保存数据。
2. `read_current(batch_id)`：读取当前A版本、摘要及基础字段。当前有效值只从此A视图读取；原Excel仅是来源和对照，保存流程不会回写它。
3. `preview_return(batch_id, uploaded, expected_hash=当前摘要, field_proposals=[], box_corrections=[])`：复用A-02实际工作簿比较器，展示修改及待核项，不确认保存。公式格的G/H更正可通过有真实对话出处的后台提案保存，不覆盖Excel公式。
4. `prepare_confirmation(preview_id, selection)`：明确本次保存、确认、黄色采用范围，展示只涉及本次范围的确认摘要。
5. `commit(plan_id, confirmed_hash=已展示范围摘要, explicit_confirmation=True, reference=真实明确确认出处)`：只有明确确认后才保存新A版本。身份追溯复用B2宿主上下文；无可信身份时记为本地未验证，不冒充专业审批。
6. `read_current`重新读取，`history`只沿已提交版本链展示。中断时重试同一个已确认计划，不另建重复提交。

业务通过对话确定范围，宿主负责参数；用户无需填写JSON、哈希、身份或Excel批准栏。不新增业务列、说明页或审核页面。

已有Python/openpyxl环境直接运行，无需安装：

```powershell
python -X utf8 -B -m a_confirm register --root 新专用目录 --request register.json
python -X utf8 -B -m a_confirm read --root 同一专用目录 --request read.json
python -X utf8 -B -m a_confirm preview --root 同一专用目录 --request preview.json
python -X utf8 -B -m a_confirm plan --root 同一专用目录 --request plan.json
python -X utf8 -B -m a_confirm commit --root 同一专用目录 --request commit.json
python -X utf8 -B -m a_confirm history --root 同一专用目录 --request read.json
python -X utf8 -B -m unittest discover -s tests -v
```

CLI请求对应方法的同名参数。`register.json`为`{"context_file":"A02可信上下文.json"}`；`read.json`为`{"batch_id":"登记返回的24位批次ID"}`。上下文沿用A-02的 `a02-trusted-context/1`，包含全部相关已发出登记，不从Excel或文件名推定批次/版本。

## 部分确认与候选

范围结构如下，目标为后台已登记的工作表和格子，不支持`*`等整批通配批准：

```json
{
  "save_changes": ["Sheet1!E3", "Sheet1!Q2"],
  "confirm_fields": ["Sheet1!E3"],
  "adopt_candidates": [],
  "evidence": {}
}
```

该例保存两格，只确认E3；Q2仍待核。未选修改不会写入当前版本。黄色未改仍为候选，只有明确列入 `adopt_candidates` 才采用；不能把黄色夹在普通确认里。材质采用始终是参考，不是最终申报材质或专业批准。YD可以明确清空。名称/品类/材质缺项可仅保存待核，不能确认通过；0/负数/非整数盒规不能确认。

对未改候选的采用与对人工新值的确认不同：人工改了候选值，须选入保存及确认范围，不再伪称原候选证据直接支持新值。原参考来源继续后台保留。

采购价格明确采用需提供本批依据，示例：

```json
{
  "source_ref": "真实采购凭据或明确确认本批采购价的出处",
  "source_kind": "purchase_document",
  "price_basis_hash": "read_current返回的本批价格口径摘要",
  "currency": "JPY"
}
```

`source_kind`仅允许`purchase_document`或`explicit_purchase_price_confirmation`，不允许零售价或历史最终金额；该依据必须来自真实业务/宿主，不可从Excel自动伪造。盒规采用需`{"source_ref":"真实依据","meaning":"pieces_per_box"}`。这些确认只构成A阶段本批参考采用，不批准Qty单位、专业材质、税率或正式输出。

没有依据的价格/盒规可以先保存为 `saved_pending`，不因保存变成验算正常。即使有明确采用，差值超过100日元、缺价、0盒规仍按原A-02规则待核，365行可逐批解决，不能保存一次就整批批准。改码/规格变化仍使旧价格关联待核，不自动泛化。

## 版本、冲突与中断

- 复用原B2 `Store.save(expected_hash=...)`、不可变快照、源行保护、CAS和原子HEAD；确认范围、修改、回执及旧B/C确认失效在同一快照生效。
- A字段只以一个稀疏业务视图覆盖原观察值；核心`rows/source/raw/authority`保持，不能把旧source层产品值当作新A权威。当前业务值从`read_current`取得，不修改原件或另建第二套业务Excel权威。
- 回传按“发出基准/当前A/回传”比较。已保存的同值不重复改，原副本未改的旧值不回滚当前值；同一格出现与当前冲突的新旧修改时拒绝。部分保存后必须刷新预览，才能确认剩余范围；旧确认计划不能覆盖新版本。
- 一个确认计划对应一个事务ID，与重复点击时的备注文字无关。同计划重复确认、在后续版本后重领旧回执，均返回原回执，不新增版本或重复改值。未新增内容/确认范围不创建新版本。
- 原受控H/U规则继续复用A-02，在有效A数据投影上重算价格检查；不使用上传文件丢失或篡改的公式缓存。原工作副本和公式永久保留，后台业务采用值与原公式观察值分开追溯。
- 事务先形成不可变保存意图，再调用B2 CAS。HEAD切换前失败，旧版本仍有效；切换后即使回读异常，也从同事务回执恢复，不误报为未保存。历史只追溯HEAD的提交链，不把未提交快照当新版本。
- 本候选专用目录新增进程级OS互斥，进程死亡后系统释放锁。仅在获得专用互斥后，才能清理本候选遗留的B2空写锁并重试；绝不按时间猜测/删除活跃写锁。不得让其他旧入口直接写本候选Store。
- 任一有效基础变更或明确采用会使旧B/C确认、计算输入指纹失效，保留无关A字段的既有确认。没有实现或运行B计算。

全部状态`can_enter_b=false`、`formal_output=false`、专业批准0。A保存成功不等于全批就绪。原表无嵌入版本ID的边界延续A-02：宿主须保留完整已发出登记；无法唯一定位或存在未登记旧文件来源疑义时不猜归属。

测试采用合成数据及授权历史表的模拟明确确认，记录TEST出处，不冒称真人审批或WorkBuddy原生验证。`tests/process_fault.py`仅供本地故障测试，会故意终止进程，不是业务入口。
