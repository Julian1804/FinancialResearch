from services.provider_service import call_agent_chat


class AnalysisAgent:
    def run(self, system_prompt: str, user_prompt: str) -> str:
        return call_agent_chat("analysis_agent", system_prompt, user_prompt)
