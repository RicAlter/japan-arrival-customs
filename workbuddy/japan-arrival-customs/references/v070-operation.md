# 0.7.0-rc.2 操作与部署

本版交付核心技术候选，L1以本地回归证据为准；WorkBuddy实测/L2、真实业务/L3、正式生产/L4单独验收。明日保底0.6.0包与分支不被本版替换。

## 安装与依赖

将ZIP中的japan-arrival-customs目录安装为一个WorkBuddy Skill，目录根须可见SKILL.md。保留scripts、references及requirements.txt的相对位置。使用WorkBuddy宿主提供的Python执行scripts/run.py；安装依赖命令为python -m pip install -r requirements.txt。依赖openpyxl==3.1.5，sqlite3/urllib为标准库。要求Python3.11及以上，本地验收Python3.14；其他宿主Python版本仍须实测。

批次目录、交付目录、原始输入目录、D1库各自独立，均在Skill安装目录之外。升级安装仅换源码，保留原运行目录；业务运行不修改代码、结构或规则。trusted_sessions.json、rule_policy.json位于批次目录security下，由宿主管理员保护，不属于附件上传区。不能从Excel、自然语言、OS用户名或本文件创建真实身份。

## 业务操作

业务上传第3步金额Excel、日方原表及箱重表（可同文件不同页）、第2步材质查询历史；历史材料只作候选。无第2步历史时须提供现有模板的空候选表，不得填造材料。生产可在首票测试确认后再优化该依赖。

业务说“处理这批日本到货”，WorkBuddy组装请求：

```json
{"message":"处理这批日本到货","files":["C:/ArrivalInput/stage3.xlsx","C:/ArrivalInput/japanese.xlsx"],"currency":"JPY"}
```

调用统一受控程序：

```text
python scripts/run.py --output C:/ArrivalRuntime/batches workbuddy --request C:/ArrivalRequests/request.json
```

附件通过固定单元格结构识别；同类多文件、多个箱重页或未知文件要求澄清。新输入重建批次，原批审核不覆盖；相同输入恢复已有批次。完整原表和箱重齐全时自动建立未签核合同，仍须真实D07/D08签核。仅第3步文件可预导入，不能冒充审核资料齐备。

“生成这批到货的审核表”：请求增加batch、material_history、file；可提供recommendations/official_materials的现有JSON文件，或source_evidence的已归档官网证据路径列表。只生成总览、问题、明细三页，业务仍改问题页两列。

“这是我修改后的审核表，继续处理”：请求file。受控B2校验可信导出登记、展示新旧差异、行范围、preview_id与confirmation_hash；WorkBuddy必须展示result.changes/operations并取得明确确认。

“确认提交这批审核”：请求必须明确batch、preview_id、confirmed_hash、confirm=true、reference、session_token_env；身份令牌来自该环境变量。可加library。B2先保存，再同步D1；失败显示保存状态、待重试标记，通过d1-sync重试。普通商品确认、材质批准和关务批准仍为不同的明确操作，不能从一句“继续”推导批准。

“查看这批还有哪些问题”：返回商品数、普通批量范围、单独项、金额数量箱重和下一步；阶段从原B2快照、预览和回执派生，没有第二套状态。缺批次时仅在现有批次唯一时恢复。

“生成海关和内部到货表”：只生成带明显受控草稿标识的两份Excel。重复请求重读并复核同版本文件；损坏或数据不符拒绝交付。formal-export保留原正式门禁，D05未批准不能正式外发。

## D2、D3与来源

d2-report/d2-replay要求library、as-of；formal为默认，test必须明确指定。所有日期均显式给出；D1的as_of只查税率日期，D2使用事件及入库时间截断历史。按JAN/商品身份、批准事务及决策版本关联分组，保守去重，跨JAN只按完整条件相同发现候选。一次独立支持仅显示案例。指标含分母，零样本显示无法评估；不把技术夹具当业务准确率。

规则文件固定为原D1目录/rule_registry.json。rule-draft引用当前D2候选ID；rule-publish必须传真实会话环境变量、D08批次、依据和预期版本。管理员rule_policy.json须包含realm、quality_approved、approval_reference、approved_by、credential_ref、publishers/executors、有效期及完整thresholds：min_independent_support、min_validation_decisions、min_covered_decisions、min_joint_accuracy。程序不提供获批默认值。发布者和执行者须同时满足D08现有customs职责及可信会话rule_publisher/rule_executor专用角色，无新增业务Excel字段。

生产自动采用还须production_automatic_enabled=true、business模式、business来源D1、当前有效支持/发布授权及完整严格匹配条件。缺少任意项转人工。rule-apply写回原B2版本和automatic_rule_applied事件；自动审签明确标记authorized_rule_automation，D1不将其作为人工样本。本票税基、盒规、数量、金额、锁版和正式输出继续独立核验。人工纠正/撤销后rule-impact列受影响规则和应用；旧锁版只追溯，不重写。暂停后须重新建立待批版本，撤销不可复活旧版本。

飞书当前实现Bitable只读字段元数据与记录分页接口。商品档案和采购订单必须分别配置真实app_token/table_id、token_env、访问授权依据及经业务确认的字段ID映射；缺映射拒绝猜测。若实际来源是电子表格/其他系统，须另行确认接口适配。网页仅访问明确授权的官方HTTPS域名，拒绝自动跟随重定向，保留完整原响应；完整材料引用与翻译待核实。来源信息通过独立参考层进入B2，保留原人工选择。

接口文档依据：[列出字段](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-field/list)、[列出记录](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/list)。本次仅验证离线契约，未宣称实际飞书或官网连接成功。

## 回滚与持久数据

源码回退用冻结0.6.0安装包；不要覆盖0.7.0运行数据或把自动应用事件喂给未经确认的老客户端。需要明日测试时使用0.6.0原独立运行目录。D1原库格式不变，无运行时迁移。D3规则文件为新增派生授权档案，格式不符拒绝自动迁移。

D1自带backup/restore只覆盖其原权威事件和来源对象，不含D3规则文件。完整0.7备份须停写后同时保存D1原备份、rule_registry.json及批次不可变快照；权限配置另由管理员安全备份。恢复到新独立目录，验证D1、规则链和支持证据，再重新批准发布/启用，避免旧备份恢复已撤销规则。安装包绝不包含上述运行数据或权限配置。
