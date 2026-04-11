from services.provider_service import call_agent_chat


class UpdateAgent:
    def run(self, system_prompt: str, user_prompt: str) -> str:
        return call_agent_chat("update_agent", system_prompt, user_prompt)
