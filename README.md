# 日本到货与海关报单 WorkBuddy Skill

当前开发候选为 **0.8.0-rc.3**：KMT第3＋4步已确认运营Excel自动适配、批次单位与特殊数量换算确认、字段/公式来源追溯，以及受控双表。默认正式输出保持关闭。rc.7冻结功能通过Git历史保留，rc.8开发不覆盖既有安装。

当前进度和验证范围见 [rc.8进度](docs/RC8_PROGRESS.md)，隔离实机测试见 [WorkBuddy验收说明](docs/WORKBUDDY_RC3_UAT.md)。真实输入、逐行差异、生成文件、安装包和人员/本机路径均留在受保护的本地环境，不提交本仓库。

面向日本到货资料整理的 WorkBuddy 主 Skill。它将受控的 Excel 输入导入统一商品明细，支持精简审核表回传和可信身份审批，并只生成两份受控文件：海关报关单草稿与内部到货单草稿。

本仓库是**无业务数据的源码版本**：不包含真实到货 Excel、历史商品资料、业务审核回传、运行记录、归类决策库、令牌或交付文件。请把这些资料放在本机受保护目录，并通过命令行参数显式传入；不得提交到 Git。

## 当前能力与边界

- 0.6.0 包含批次导入、三页精简审核工作簿、回传差异预览/明确确认、版本化最终选择，以及独立 D1 决策库的导入、检索、备份和重建。
- D1 检索只返回带条件与依据的历史案例候选，**不会批准归类或自动采用税号/税率**。
- 0.7.0-rc.2 已实现 D2 条件候选/时间及商品留出回放、D3 可信授权规则生命周期、只读来源适配与统一自然语言操作路由。D3 生产开关保持关闭；飞书/官网尚未实机接通。
- 正式外发始终关闭。输出前仍会检查审核、金额、数量、箱号、重量、材质、税号和税率等业务门禁。

## 安装

需要 Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r workbuddy/japan-arrival-customs/requirements.txt
python workbuddy/japan-arrival-customs/scripts/run.py --help
```

Skill 入口和命令约束见 [SKILL.md](workbuddy/japan-arrival-customs/SKILL.md)。运行状态、真实输入、D1 库与可信会话配置必须位于仓库外或 `local-data/` 等受 Git 忽略的目录。

## 开发校验

仓库提供不依赖业务资料的技术回归与隔离夹具：

```powershell
python -B tools/run_v070_tests.py --output C:/ArrivalTestEvidence/0.7.0-rc.2
```

历史回归和真实 WorkBuddy 验收只能在受保护的本地资料环境完成；其结果不应提交到本仓库。

0.7.0统一业务调用与安装/回滚见[操作说明](workbuddy/japan-arrival-customs/references/v070-operation.md)；模块技术状态见[交付说明](docs/V070_TECHNICAL_DELIVERY.md)。0.6.0明日测试分支和安装包继续独立冻结，0.7.0仅作为技术候选。

## 数据与凭据规则

- 不提交 `.xlsx`、历史资料、客户/商品信息、审核证据、运行输出、SQLite 决策库或压缩交付包。
- 不提交可信会话文件、令牌、令牌哈希、`.env` 或任何生产配置。
- 可提交合成且不可反推业务资料的测试夹具；命名须明确为 synthetic/example。
- 提交前执行 `git status --ignored`，确认忽略规则生效。详见 [仓库卫生规则](docs/REPOSITORY_HYGIENE.md)。

## 仓库结构

```text
workbuddy/japan-arrival-customs/   # Skill、Python 核心与无数据参考说明
docs/REPOSITORY_HYGIENE.md         # 上传前检查与数据隔离规则
tests/test_repository_smoke.py     # 无数据冒烟测试
```
