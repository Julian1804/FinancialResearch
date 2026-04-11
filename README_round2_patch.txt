第二轮补丁目标：
1. 把模型调用统一收口到 llm_gateway_service.py
2. Agent 只负责路由，不直接耦合供应商 API
3. 用 llm_profiles.json 管理“API Key / Base URL / 模型名”三元组
4. 保留旧 provider 字段兼容，便于渐进迁移
5. 路径层支持本地 -> QNAP 平滑迁移

建议同步修改 agent_registry.json：
- 未来逐步给 analysis_agent / update_agent / qa_agent 增加 profile_name 字段
例如：
  "analysis_agent": {
    "enabled": true,
    "mode": "cloud",
    "profile_name": "aliyun_test",
    "provider": "aliyun_qwen_compatible",
    "model": "qwen-max-latest",
    "timeout": 300,
    "temperature": 0.2
  }

重要说明：
- 当前补丁已兼容旧配置，即使 agent_registry.json 里还没有 profile_name，也能运行。
- 以后你换模型，优先改 llm_profiles.json + .env，不建议再改 analysis/update/retrieval 等业务层代码。
