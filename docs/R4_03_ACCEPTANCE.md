<!-- CNY-DOWNSTREAM-VERSIONS-20261116 -->
2026-11-16最新：已保存的人民币成本reviewed_source已由统一入口生成2861行R3-01/02/03和R4-02新版本。整批技术验收通过，63个H修订及原数据/人工值/公式缓存/图片保全，8次current/resume一致；旧任务绑定保留。缺项继续待核，新文件WPS显示未执行，R3/R4整体与运营/专业批准仍未完成。运行仍绑定冻结4b48d0d，本次仅同步进度文档，不改程序、正式安装/main或数据库。详见[新版本说明](CNY_DOWNSTREAM_VERSIONS.md)。以下旧阶段状态保留历史时点。
<!-- /CNY-DOWNSTREAM-VERSIONS-20261116 -->

# R4-03 只读验收与真实整批范围

开发验收工具 `tools/verify_pair_acceptance.py` 只读取已经保存的 `arrival-dual-projection/1` pair_source，不运行业务 prepare、不补资料、不重算或修改旧任务。报告写到新目录，不创建、覆盖或重存业务 Excel。正式安装、main 和已采纳基线保持。

```text
python tools/verify_pair_acceptance.py --request request.json --output 新证据目录
```

request 提供 pair_source 完整引用和 expected_batch：kind=real_batch/technical_sample、batch_id、source.path/sha256、sheet。预计整批必须绑定真实文件、SHA、实际表和全部出荷行，不能手填行数、按 JAN 去重或把抽样标成全量。原始行身份比较 source_sha256、sheet、source_row 和完整顺序；R1 显式行映射缺失时不靠同码猜连。technical/sample 批次永远不能获得 whole_batch_covered。

工具通过 R4-02 的 read_pair_source 核对已保存 job、联合回执、文件及 R2/R3 相互引用和原始来源 SHA。另独立检查：

- R3→R4 内部文件全字节相同；R2→内部逐格值、类型、公式及缓存保全，仅允许原空白 I/U/V/W/X 的既有 R3 补缺，原有人工值和公式不视为空白。
- 非目标 ZIP 部件、图片/绘图字节、原重量页和合并保全；当前内部24列表头。
- 海关逐格实际值、文本编码、许可公式及缓存与契约一致，数量和价额单独回核 R3；G×F=P、合计及唯一实物箱数/去重重量。未知项不变成0，超范围格和额外商品行不静默放过。
- 原来源、任务、SQLite 和业务文件 SHA 前后相同。只写 acceptance.json、issues.csv、coverage-missing.csv、evidence-manifest.json。

状态区分 technical_checks_passed、whole_batch_technical_passed、data_ready。技术文件检查通过仍可能是 coverage_incomplete；有缺项保留 technical_with_gaps，不能冒充运营或专业认可。CLI 返回0仅表示声明范围技术检查成功；整批覆盖不足返回2，结构/值/保全检查失败返回1，配置或引用漂移抛错。所有输出始终 operator_approved=false、professional_approved=false、formal_output=false、R4_complete=false；正式验收不能由本工具自批。

WPS 显示独立登记，不由 ZIP、缓存或 Artifact 预览推断。使用业务文件字节相同的只读副本，记录实际应用版本、文件 SHA、观察范围及本机截图，核验后不保存；能显示图片不等于商品图片对应正确，技术夹具不能冒充真人业务样本。WPS截图及业务证据只留本机，不上传 GitHub。

当前发现：登记的新版 pair_source 仅有9行历史坐标技术样本；本机73个相关 job 盘点未找到新版整批 R2→R3→pair 链。1967行旧整批文件属于历史流程，内部21列/海关19列，且1967行海关品名等于内部日文名，不能替代当前24/33列规则或新版验收。另一2861行批次仅有早期匹配/补充成果，不混批。完整记录以本机治理证据为准。

实际 WPS 12.1.0.24034 已验证海关样本完整编码、P2公式及金额显示、缺项颜色；既有 PNG 技术保全夹具的图片可见，关闭不保存后重开仍可见，原件和副本 SHA 不变。该图是保全测试夹具，题材与行商品不对应，不能登记商品图正确或整批通过。原有 Artifact 导入/渲染限制仍保留原证据，不能改写为历史 WPS 成功。

下一步仍是 R4-03：取得同批次、全行身份明确的新 R2 保存及 R3 版本化结果和 pair_source，再运行整批覆盖与本机显示核验；海关字段来源、尺寸展示和运营/专业认可分别待办。本轮交付只读验收工具和当前资料核验记录，不宣布真实整批验收完成。遵照用户反馈，日常表格数据、公式及保全优先用代码核验，Computer Use 仅用于明确要求的最少量原生显示抽查，不反复操作界面。
