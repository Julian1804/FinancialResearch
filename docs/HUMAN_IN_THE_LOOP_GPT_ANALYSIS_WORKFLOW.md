# Human-in-the-loop GPT Analysis Workflow

## Phase 1 Objective

FinancialResearch does not run a background ChatGPT/OpenAI analysis agent. The local system builds a structured analysis packet, the user copies it to ChatGPT Web, discusses and revises manually, then pastes the final report back into FR for structured storage and future backtest.

## Workflow

1. Build a data snapshot from consumption-grade trusted facts only.
2. Add candidate facts as clearly labeled context, never as final facts.
3. Generate a markdown analysis packet and a copy-to-GPT prompt.
4. User pastes the packet into ChatGPT Web.
5. GPT Web returns a markdown report plus a `FINAL_REPORT_JSON` block.
6. User pastes the final report back into FR.
7. FR stores raw report text, parsed JSON, assumptions, forecasts, risks, watchlist signals, confidence, and backtest fields.

## Guardrails

- Do not call OpenAI API from FR backend.
- Use only information available on or before `as_of_date`.
- Candidate facts cannot become trusted facts inside the report.
- If evidence is missing, the report must output `insufficient_evidence`.
- Forecasts are stored as reviewable hypotheses, not as decisions.

## Sample Outputs

- sample packet id: `analysis_packet_f205eedf8d394ce8`
- sample ingested report id: `gpt_web_report_11e26fd3527c5ce7`
- sample directory: `D:\workspace\FinancialResearch\runtime\financial_report\data_foundation_phase1\sample`
