# FR Dashboard v1 Acceptance Checklist

Generated: 2026-05-20T07:20:21Z

| Step | Expected result |
| --- | --- |
| Start new UI | Run the action server command and open http://127.0.0.1:5188/. |
| Confirm not Streamlit | Page title shows FR Dashboard v1 and legacy_streamlit_used=false. |
| Open Overview | Data status, missing publish date and future exclusion counts are visible. |
| Open Research Workspace | Research Object Type, Time Mode and as_of_check_enabled controls are visible. |
| Select research_object_type = company | Company is available in the dropdown. |
| Select symbol = 600519 | 600519 can be generated through the local action request. |
| Set time_mode = publish_date | publish_date remains the default as-of-safe axis. |
| Set window_start / window_end | Window fields are visible and action smoke uses 2026-04-01 to 2026-05-19. |
| Generate statistical report | Action creates snapshot_manifest.json and statistical_report files. |
| View output paths | Generated result panel shows paths for snapshot, report, prompt and evidence boundary. |
| Use download buttons | Markdown, JSON, GPT prompt and evidence boundary download buttons point to generated files. |
| Copy copy_to_gpt prompt | Prompt textarea is available and Copy Prompt button is visible. |
| Open Report Upload | Report Upload page contains markdown paste area. |
| Paste/upload markdown report | Classify Report parses FINAL_REPORT_JSON without OpenAI API. |
| Validate zones | Analysis Zone, Forecast Zone and Evidence Zone display structured content. |
| Open Research Workspace | Load Research Workspace calls local action layer. |
| Review workspace objects | Packets, reports, forecasts, backtests and revision candidates are visible when runtime index exists. |

Boundaries: no Streamlit, no OpenAI API, no formal trusted consumption changes.
