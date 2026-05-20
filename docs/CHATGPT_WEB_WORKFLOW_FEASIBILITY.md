# ChatGPT Web Workflow Feasibility

Generated: 2026-05-20T04:59:09Z

Dashboard v1 uses a semi-embedded human-in-the-loop workflow:

1. FR generates a statistical report and `copy_to_gpt_research_prompt.md`.
2. User copies the prompt to ChatGPT Web.
3. User discusses and asks ChatGPT Web to emit a `FINAL_REPORT_JSON` block.
4. User pastes/uploads the final report back to FR.
5. FR parses, classifies and stores report artifacts.

No OpenAI API is called. ChatGPT Web is opened as a separate page, not embedded in an iframe.

An iframe-based ChatGPT Web embed is not the v1 direction because it is less reliable, may violate
browser/security constraints, and is not needed for the manual workflow.
