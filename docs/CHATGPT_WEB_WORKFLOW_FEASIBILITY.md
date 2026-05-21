# ChatGPT Web Workflow Feasibility

Generated: 2026-05-21T10:28:19Z

Dashboard v1 keeps the semi-embedded human-in-the-loop workflow:

1. Generate a statistical report and copy-to-GPT prompt in FR.
2. Open ChatGPT Web manually.
3. Paste the prompt and conduct analysis there.
4. Paste/upload the final Markdown report with `FINAL_REPORT_JSON` back into FR.
5. FR classifies Analysis Zone, Forecast Zone and Evidence Zone locally.

No OpenAI API is called. ChatGPT Web is not embedded in an iframe. GPT report content remains
analysis/forecast/interpretation, not trusted facts.
