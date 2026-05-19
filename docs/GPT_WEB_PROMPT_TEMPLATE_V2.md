# GPT Web Prompt Template v2

The generated prompt is stored per target as `copy_to_gpt_prompt.md`.

Key requirements enforced by the template:

- Use only packet information.
- Treat `as_of_date` as the information boundary.
- Candidate/staging data cannot be treated as trusted final fact.
- `needs_review_candidate` and `insufficient_evidence` must be visible.
- Output a Markdown report plus a valid `FINAL_REPORT_JSON` block.
- Do not call any API from FR; the user copies the prompt into ChatGPT Web manually.
