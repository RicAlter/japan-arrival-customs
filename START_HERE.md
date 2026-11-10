# 唯一开发入口

先读 CURRENT_STATUS.md、BUSINESS_RULES.md、SOP_INDEX.md，再读 governance/ 下的版本、来源、测试和归档索引。

唯一开发分支：codex/unified-development-20261110。源码工作树为本目录；确切提交及可运行封包位置见项目根目录 outputs/统一开发候选_当前.json。历史业务 session 继续使用各自绑定 runtime，不自动迁移。

统一执行入口 business-interaction/run.py；封包入口 skill/scripts/operate.py 校验源码 SHA 后调用绑定源码。基础表→回传预览→一次明确确认→保存；阶段二仍须实际价格/单位/盒规及业务确认。不得把本次治理当基础资料批准。

