# P2-B2 实际回传（0.5.0，本地验收）

业务继续一个主Skill，使用B1总览/问题/明细三页。主要只填问题页两列，完整明细只读。原B1已交付件不改写，B2重新登记一个带导出标识的副本；旧B1文件不能当作未登记上传直接批准。

## 使用顺序

1. `return-export --batch <ID> --material-history <第2步历史表> --file <新审核xlsx> [--recommendations <推荐JSON>] [--official-materials <参考JSON>]`。共同前缀为 `python scripts/run.py --output <已有独立存储>`。复用现有B1生成器，不重建业务核心。原件只读，输出拒绝覆盖。
2. 业务只改必要内容。例如：F列“补充资料”，G列`范围=1；申报材质=本次人工选择；原因=实际改选理由`。采用当前AI推荐则F列“采用候选”，G列说明原因和范围，不必重抄材质。多商品须明确`范围=本组全部`或本表商品序号；不同结论分开范围。
3. `return-preview --batch <ID> --file <回传xlsx> [--operations <明确操作JSON>]`。返回预览ID、确认哈希和详细预览文件。向业务展示原推荐、原新最终选择、事实变更、影响范围和缺项；不把字段缺失视为通过。
4. 取得业务对该预览及操作范围的明确确认，才执行`return-commit --batch <ID> --preview-id <ID> --confirmed-hash <相同哈希> --confirm --reference <确认凭据> --session-token-env <可信环境变量名>`。空白无操作不自动批准。
5. `return-status --batch <ID>`看保存版本、缺项与税金重算；`return-events --batch <ID> --file <新JSON>`提供D1持久事件。`return-lock`只在本票输入、各域审核、数量/金额/箱重全部齐备时形成内部审核锁，不授权外发。

自然语言说明无法无歧义解析时原样保存并标待澄清，不能凭AI猜值批准。复杂归类依据可由Skill从已有、获授权的凭据整理为一次成组结构化提议，再明确预览确认；不要求每条商品在Excel手写完整后台字段。官方参考和未审历史不会自行变成AI推荐。

## 明确操作

operations为列表，每项包含action、row_ids和reference，不含actor/roles等身份字段：

- `confirm_products`：可用`scope: ordinary_products`一次选择本导出的普通候选；混入商品/身份争议整次拒绝。individual仍不能直接覆盖已有确认。
- `edit_decision`：独立列明values和可选per_row_values；用于从专业凭据补充共同事实与逐行版本/规格。公共和逐行字段不能静默覆盖。
- `approve_material`、`approve_classification`：分别校验material/customs角色和凭据。多商品还需reason说明凭据覆盖范围。事实/版本/规格缺失或不匹配、专业争议未决时拒绝；不能靠同一材质词扩大范围。
- 已知专业争议只允许单商品、对应角色逐项处理；resolutions须精确覆盖本域全部争议ID并逐条说明依据，原争议与处理结论进入决策事件。税率争议不无故阻止材质域先审；身份改码、未知争议不得借此解除，混入成组批准拒绝。
- `approve_classification`如需同时核验本批税金，须tax_parameters按行明确tax_unit_price和tax_unit。未知盒规仍不算税金；仅复现既有historical-box-v1，不设默认税率。
- `return_decision`：明确原因及范围，保留旧版本，当前材质/归类转待复核。已审商品按需纠错可在`return-export --reopen-rows <行ID列表JSON>`明确列入问题，不要求全部已审商品重复审核。

四层后台：official_materials / historical_reference_materials / recommendations / versions[].human_final。推荐、来源、旧人工选择不覆盖。修改最终材质/用途构造等事实后，关联材质/税号税率和税金确认失效，原金额、未改盒规、无关商品审核保留；只改税率条件不清掉材质批准。B2决策行的敏感修改禁止从旧API绕过版本化流程。

## 可信身份与保存

可信管理员在独立运行目录的`security/trusted_sessions.json`维护sessions；业务上传目录和Excel不能写此配置。每项由principal、roles、mode、credential_ref、token_sha256和带时区expires_at构成。令牌由可信主机环境交给程序，不放在命令参数、Excel或日志中；角色还必须满足已签首票合同D08。会话过期、权限撤销或配置变化后拒绝执行。本适配不是WorkBuddy登录认证服务，实际主机令牌注入与人员角色配置仍需最终集成。

业务mode是business。技术mode是synthetic_technical_test，且只准用于同样标记的测试批次；事件、批准、Excel均带标记，learning_eligible始终false。不得把合成凭据称作实际D08人员审核。缺原因、事实、有效归类依据或必要审签可存草稿，不能进入正式学习集。

批次、最终选择版本、决策事件、幂等回执在同一不可变修订/CAS保存。快照先写、head原子提交；失败前不批准，提交后丢回执重试返回原结果。旧导出新操作/并发冲突拒绝。重复上传按规范化修改、明确操作和可信操作者/凭据去重，不重复审签。上传/导出文件以同目录临时文件完整落盘后原子独占归档，既有文件不替换。

`decision_event_stream`验证事件哈希链；`deliver_events(store,batch_id,sink)`仅为后续D1接口。sink必须按event_id幂等接收并返回event_id/payload_hash。失败显示待同步，批次和人工选择保留；接收后丢回执仍用同ID重投。本轮未实现生产决策库、跨JAN匹配或规则发布。

D05、尾差算法、D06身份映射、未知盒规税率和正式输出门禁保持；最终业务文件仍只有海关和内部两份。测试以本地回归和真实Excel回传为主，本轮未做WorkBuddy实机验证。
