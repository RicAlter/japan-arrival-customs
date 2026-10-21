# P1-B 输入、审核与草稿操作

> P1-C更新：当前默认Python/openpyxl生成Excel，不要求Node配置；成组审核及最终集中WorkBuddy验收按[p1c-workflow.md](p1c-workflow.md)。下述Node命令仅为旧适配器的兼容用法。

一个主Skill，沿用P1-A/F1/F2明细和审核协议。Python负责来源连接、精确计算、状态及门禁；独立Node渲染适配器仅把Python已准备的字段投影写入两个新Excel。不会加载原工作簿作为输出模板。

## D07/D08首票合同

```text
python scripts/run.py --output <原件目录之外的独立目录> init-contract --invoice <日方原表> --authority <第3步表> --weights <箱重文件> --weight-sheet <明确工作表名> --customs-reference <可选第5步历史表> --internal-reference <可选第6步历史表>
```

合同生成时锁定源路径/SHA、模板类型和表名。JPY、KG是当前KMT表头明确的观察单位，不代表本票已签核。数量单位和实际审核人均为null，不能填“默认件”、测试人员、未知/待确认占位词。可由业务逐商品填写row_quantity_units，键为第3步原始行号；authority_quantity_unit仅在业务明确全票同一单位时填写。

实际责任为business（商品）、identity（身份）、amount（金额）、material（材质）、packaging（盒规）、customs（税费）、logistics（物流）、release（最终复核），各填实际人员名单。不要求一个人承担全部职责；本程序不自动分配。职责只是一份本地可信配置，不能冒充登录鉴权。

明确输入版本与至少商品责任人后，由可信管理员配置contract角色并签核：

```text
python scripts/run.py --output <独立目录> sign-contract --contract <已填写合同JSON> --actor <实际签核人> --evidence <真实签核依据> --permissions <可信角色配置JSON>
python scripts/run.py --output <独立目录> import-batch --contract <签核合同或明确待确认的测试合同>
```

签核绑定合同全部内容的哈希；修改文件版本、单位或名单后原签核失效，需重新签核/建版本。未签核合同可以做只读检查和受控草稿，不能作业务审核。已签核而部分专业职责/单位尚缺时，仅已明确责任人的范围可审核，其他范围保持待定；不让税费待定不必要地阻断基础商品审核。金额/盒规单位缺失时对应API仍拒绝确认/计算。

## 来源和物流

唯一同码、同箱号、同日文名对应的源记录挂接到original_purchase，原零售价/卸价与第3步金额分别保存。改码、拆分、多候选不自动连成已批准身份关系。第5/6步只进入historical候选，不能覆盖第3步金额或把盒规/材质/税率变成已审核。

箱重指定KMT箱番、カートン個数、合計重量（KGS)模板。复用P0箱号范围展开，按物理箱集合和组总重核对，缺箱、多箱、重复组、缺/负重量、箱数不匹配均不能算通过。不按单箱重量求和，不自动分配合并组重量。

```text
python scripts/run.py --output <同一目录> reconcile-logistics --batch <批次ID>
python scripts/run.py --output <同一目录> professional-queue --batch <批次ID>
python scripts/run.py --output <同一目录> status --batch <批次ID>
```

商品仍按既有review-package → supplement-group → 新审核包 → confirm-products执行。专业域单独approve-domain，提供本商品/版本/规格证据，正常商品域确认不消除专业争议。F2重复确认拒绝保留。原表身份争议不能用普通version/specification确认绕过，D06单独待业务依据。

## 两份受控草稿

```text
python scripts/run.py --output <同一目录> render-drafts --batch <批次ID> --runtime <本机渲染运行时JSON>
```

runtime JSON显式配置`node_executable`及包含`@oai/artifact-tool`的`module_root`（node_modules绝对目录）。不默认下载/安装，不把Codex的绝对路径写进安装包。Python端依赖仍为openpyxl 3.1.5；Node及artifact-tool是新增的草稿渲染依赖，WorkBuddy中的实际执行尚待验证。本机开发已用Codex打包运行时验证；缺运行时会拒绝导出，不切换未验证引擎。

只生成海关报关单、内部到货单两份带“受控测试草稿、不得外发”的Excel，各自附箱重核对页，不另出日本物流单。未审核商品保留，不静默删行；候选申报名明确未审，申报数量/材质/税费只在对应确认完成后填正式字段，内部候选材质明确列名。金额基准来自第3步，即使本票尚未签核也保留来源值并标示审核状态。

从同一状态哈希生成两表并重开核对行、金额、换算关系、箱重及隐藏内容。海关投影不含内部名、YD、渠道、备注、来源文件路径及历史元数据；与已知内部字段碰撞的候选被抑制并列入内部JSON报告，不能把它当作已通过D05。非终止小数单价保留精确比，不取整、不量化、不调价。

`formal-export`明确拒绝，本版不存在通过参数打开正式外发的开关。D05白名单、相关业务签核、集成证据及独立正式放行授权齐备前，不生成正式件；无外发命令。

## WorkBuddy集成验收

原43＋24基线保留，只补原生Skill触发和D1误批拒绝过程。原生触发必须由WorkBuddy界面/原始Skill调用记录证明，单独运行脚本或声称“已读取SKILL.md”不足。

```text
python scripts/workbuddy_integration.py --output <全新独立测试目录> --operator-session <实际会话标识> --context workbuddy
```

脚本只使用N1/N2/D1合成数据，保存混入D1请求、原始返回码/错误、前后所有状态文件SHA，再确认普通N1/N2并保留D1待定。会话标识与context是操作者声明，本身不证明实机环境；仍需提交WorkBuddy原生触发与脚本工具调用记录。local-rehearsal只能作为本地预演，不能升级为实机通过。新渲染依赖另需在WorkBuddy实测，既有Python/Excel探针不重跑。
