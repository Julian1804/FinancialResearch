from services.agent_router import AgentRouter


class RetrievalAgent:
    def __init__(self):
        self.router = AgentRouter()
        self.config = self.router.get_agent_config("retrieval_agent")

    def get_runtime_config(self) -> dict:
        return self.config