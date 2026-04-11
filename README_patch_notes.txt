本补丁包覆盖以下文件：
- app/config/settings.py
- app/services/provider_service.py
- app/services/agent_router.py
- app/agents/analysis_agent.py
- app/agents/update_agent.py
- app/services/retrieval_service.py
- app/services/decision_support_service.py
- app/services/sqlite_index_service.py
- app/services/repository_service.py
- app/services/update_service.py
- app/services/actual_metric_service.py

目的：
1. 统一 provider / agent 接口
2. 修复 DEFAULT_CHAT_PROVIDER / DEFAULT_LLM_PROVIDER 不一致
3. 接入你补全的 actual_metric_service
4. repository / sqlite 时间排序统一到 year + report_type + material_timestamp
5. update/history_memory 正式贯穿 material_timestamp
6. 修复 decision_support_service 的导入与结构问题
