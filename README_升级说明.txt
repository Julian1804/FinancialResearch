这是一份可直接覆盖原项目的优化版代码。

本次主要更新：
1. 保留原有 parse / extract / analyze / update / forecast_check 流程。
2. 新增本地化问答检索页面：app/pages/qa.py。
3. 新增公司索引与时间轴索引：index.json / timeline_index.json。
4. 新增本地混合检索：关键词 + TF-IDF 向量检索。
5. 优化 provider 抽象层，方便后续从千问切换到 DeepSeek。
6. 优化 analyze / update / forecast_check 的提示逻辑，强调量化证据与偏差归因。
7. 保留 BSTS 作为正式主模型方向，并新增 requirements-forecast.txt 作为后续独立安装入口。

本次建议直接覆盖的重点文件：
- requirements.txt
- requirements-forecast.txt
- app/config/settings.py
- app/config/agent_registry.json
- app/main.py
- app/utils/file_utils.py
- app/services/provider_service.py
- app/services/research_utils.py
- app/services/repository_service.py
- app/services/retrieval_service.py
- app/services/analysis_service.py
- app/services/update_service.py
- app/services/forecast_service.py
- app/pages/upload.py
- app/pages/parse.py
- app/pages/extract.py
- app/pages/analyze.py
- app/pages/update.py
- app/pages/forecast_check.py
- app/pages/qa.py

当前版本说明：
- 现在可以继续在“不上 SQL、不迁 QNAP”的前提下跑通。
- QNAP 迁移时，优先改 .env 中的 FIN_RESEARCH_DATA_DIR 或 QNAP_DATA_DIR。
- 正式 BSTS 预测可在下一阶段接入独立页面；当前先把回测、更新、检索、索引底座打稳。
