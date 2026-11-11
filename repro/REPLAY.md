# 可复现开发候选

1. 检出codex/unified-repro-20261111，读取START_HERE.md并运行tools/check_candidate.py。完整SHA由Git核对；本机权威版本登记在项目根governance/version-registry.json。
2. 用已登记Python依赖（dependencies.json）运行tools/freeze_unified.py，output必须为不存在的新目录。367项旧依赖锁保持不变；封包只还原已知换行符/冻结文本的精确SHA。不要在源码原地执行依赖修复。
3. Node及@oai/artifact-tool通过Codex load_workspace_dependencies取得；需要重新生成审核导出时须让冻结src能解析此包（本机可用node_modules junction），不能将整个node_modules上传GitHub。
4. 真实批次来源见inputs-index.json。本机完整inputs.json逐文件SHA核验后，在新冻结src中执行tools/replay_original_view.py --manifest <inputs.json> --output <新回放目录>。它保留所有原session，只在复制件更新后台交付指针并进行技术自回传。输入SHA不符或来源丢失即停止。
5. 复制件中的session.json包含native_view_binding；实际业务入口仍是冻结src/business-interaction/run.py。native-preview/current/upload均走同一入口。现有用户文件和session继续绑定原版本，不自动切换。
6. 既有273项技术回归：regression_existing.py的units模式复用202项基础、15项提交规则并加入14项原样回归（231）；loop21、pack16分别提供原有只读隔离fixture位置；19项test_price_input仍读取已固定真实价格来源。明确CANDIDATE_SOURCE、CANDIDATE_VERSION、PRIVATE_PROJECT_ROOT、REGRESSION_OUTPUT。所有旧fixture写入以copy-on-write导向新目录，禁止直接在历史session运行可写测试。

仓库包含源码、SOP、锁定文本及脱敏结果索引；真实Excel、数据库、session、网页和税费证据不在GitHub。新机器必须另取得原SHA一致的资料。源码可检出不代表私有业务数据已迁移，离线回放也不代表联网或运营业务批准。

私有来源清单由tools/index_private_inputs.py读取已登记文件及配置中的现存文件引用生成，不扫描全盘；数百MiB的不可变历史JSON只核验SHA，不重新解析全体业务记录。本轮176份依赖清单只保存在本机。保全报告294项不变，包含原session、正式安装和数据库。
