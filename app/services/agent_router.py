from config.settings import load_agent_registry


class AgentRouter:
    def __init__(self):
        self.registry = load_agent_registry()

    def get_agent_config(self, agent_name: str) -> dict:
        if agent_name not in self.registry:
            raise ValueError(f"未找到 Agent 配置：{agent_name}")
        config = self.registry[agent_name]
        if not config.get("enabled", False):
            raise ValueError(f"Agent 已禁用：{agent_name}")
        return config
