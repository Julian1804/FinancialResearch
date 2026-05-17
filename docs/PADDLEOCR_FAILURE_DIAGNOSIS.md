# PaddleOCR Failure Diagnosis

Date: 2026-05-17

Scope: diagnose the existing `parse_lab_paddleocr` environment and current blank-output behavior. No benchmark, no large sample run, no parser logic change, and no production trusted-consumption change were made.

## Environment

- Env: `D:\workspace\envs\parse_lab_paddleocr`.
- Python: 3.10.11.
- `paddleocr==3.5.0`.
- `paddlepaddle==3.2.2`.
- `paddlex==3.5.1`.
- `numpy==2.2.6`.
- `paddleocr` import: ok.
- `paddle` import: ok.
- `paddleocr.ppstructure` import: fails.
- `PPStructure` import from `paddleocr`: fails.
- Paddle CUDA: unavailable; current package is CPU build.

## Available PaddleOCR 3.x API Names

The installed package exposes newer API names:

- `PaddleOCR`
- `PPStructureV3`
- `TableStructureRecognition`
- `TableRecognitionPipelineV2`
- `TableCellsDetection`
- `TableClassification`

The old `PPStructure` / `paddleocr.ppstructure` route is not available in this environment.

## Existing Failure Evidence

Existing fresh pilot diagnosis shows:

- PaddleOCR runs: 12.
- blank output count: 12.
- dependency available count: 12.
- input image ok count: 12.
- structure output exists count: 12.

Existing visual stress summary shows:

- stress pages: 50.
- table detected count: 11.
- non-blank output count: 0.
- blank output count: 11.
- no usable table count: 39.

Sample input page image exists and is non-empty: 1191x1684 PNG.

## Current Call Chain

`parse_lab/backend_api/table_recovery_engines/paddleocr_structure_runner.py` materializes page images, then writes a temporary probe script. The probe tries:

1. `paddleocr.PPStructureV3().predict(input=image_path)`.
2. `paddleocr.TableStructureRecognition().predict(input=image_path)`.

It saves the result with `json.dumps(str(result))`, then `normalize_paddleocr_output()` attempts to convert raw output into table candidates.

Observed raw output contains table structure and bounding boxes, for example:

- `bbox`: present.
- `structure_score`: high.
- `structure`: HTML-like table skeleton.
- cells: mostly empty `<td></td>`.

The current blank output is therefore not primarily caused by missing input images or missing dependencies. The most likely cause is that the current invocation is producing structure-only results without OCR text/cell content, and the downstream normalizer correctly collapses those empty cells to `blank_output`.

## Difference From Earlier Successful Path

The old successful PaddleOCR evidence in `runtime\parse_lab\results\page_level_heavy_benchmark\outputs\paddleocr` used the CLI:

```text
paddleocr ocr -i <page_slice_pdf> --save_path <output_dir> --use_doc_orientation_classify False --use_doc_unwarping False --use_textline_orientation False
```

Those runs had `status: success` and non-zero OCR text length, but `table_count: 0`.

That is materially different from the current table recovery path:

- Old path: OCR text extraction CLI, useful for text rescue.
- Current path: table structure recognition, expected to produce usable table cells.

So the earlier success does not prove the current PP-Structure/table recovery path is healthy. It proves OCR-only extraction can produce text.

Legacy FinancialResearch Streamlit code found in git history used PyMuPDF/pdfplumber/pypdf and an Aliyun multimodal fallback for difficult pages. I did not find a retained Streamlit-local PaddleOCR table recovery call chain in the current history scan.

## Initial Root Cause

Most likely cause:

`blank_output` is caused by a PaddleOCR 3.x call-mode/API mismatch for table recovery. The local environment can run PaddleOCR OCR, and the table recognizer can detect table structure, but the current `TableStructureRecognition` result has empty cells. The normalizer then reports blank output.

Secondary contributors:

- Current env is CPU-only for Paddle, so table models may be slow; however the observed blank output is not a timeout or missing CUDA issue.
- The runner serializes raw results as `str(result)`, which makes robust downstream parsing harder.
- The current table pipeline may need OCR detection/recognition plus table structure/cell matching, not structure recognition alone.

## Suggested Fix Order

Do not install or upgrade large dependencies yet.

1. Keep PaddleOCR diagnostic-only.
2. Run a tiny 2-3 page manual experiment, not a benchmark, comparing:
   - `paddleocr ocr` CLI on the existing page image or page slice PDF.
   - `paddleocr table_recognition_v2`.
   - `paddleocr pp_structurev3`.
3. Inspect raw JSON/result objects before normalizing.
4. If OCR text is present but table cells remain empty, split PaddleOCR into two roles:
   - OCR text rescue.
   - table structure candidate only, not trusted table extraction.
5. Only after call mode is verified, update the normalizer to consume structured result fields instead of `str(result)`.

Optional later step:

- Consider a separate `paddlepaddle-gpu` env only after CPU call mode is validated. GPU is not the blocker for the current blank-output diagnosis.

## Recommendation

Do not prioritize PaddleOCR as the main parser path yet. Use Marker and Docling for the next small local tests. Fix PaddleOCR separately as an OCR/table-structure diagnostic tool, because its prior success was OCR text extraction rather than table cell extraction.

