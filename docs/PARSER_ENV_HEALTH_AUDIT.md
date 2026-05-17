# Parser Environment Health Audit

Date: 2026-05-17

Scope: local feasibility and environment health only. No benchmark, no large sample run, no parser routing changes, and no production trusted-consumption changes were made.

## Machine Summary

- OS: Windows 10 Pro 64-bit, build 26200.
- Default Python: 3.10.11 at `C:\Users\exsJ\AppData\Local\Programs\Python\Python310\python.exe`.
- Node: v24.15.0.
- CPU: Intel Core i7-9700K, 8 cores / 8 logical processors.
- RAM: 63.93 GB.
- GPU: NVIDIA GeForce GTX 1070, 8 GB visible through `nvidia-smi`; driver 560.94, CUDA driver 12.6.
- CUDA toolkit: `nvcc` not found.
- Disk free: C: 98.51 GB, D: 873.32 GB, E: 1792.72 GB.
- Conda: not found in PATH.

## Environment Status

| Tool | Env | Current status | Ready judgment |
| --- | --- | --- | --- |
| Docling | `D:\workspace\envs\parse_lab_docling` | healthy | ready_to_test |
| Marker | `D:\workspace\envs\parse_lab_marker` | healthy | ready_to_test |
| MinerU | `D:\workspace\envs\parse_lab_mineru` | partially_broken | repair before test |
| PaddleOCR | `D:\workspace\envs\parse_lab_paddleocr` | partially_broken | OCR-only smoke possible; table recovery not ready |
| Surya | `D:\workspace\envs\parse_lab_surya` | partially_broken | base import ok; direct API needs verification |

## Findings

Docling is installed and imports successfully. `docling==2.92.0`, `docling-core==2.74.1`, `torch==2.11.0`, and `transformers==5.7.0` are present. `DocumentConverter` imports successfully and `pip check` reports no broken requirements. This environment can move to a small local smoke test.

Marker is installed and imports successfully. `marker-pdf==1.10.2`, `surya-ocr==0.17.1`, `torch==2.7.1+cu118`, `transformers==4.57.6`, `pdftext==0.6.3`, and `pypdfium2==4.30.0` are present. Torch sees CUDA on the GTX 1070. `PdfConverter` imports successfully and `pip check` reports no broken requirements. This is the strongest candidate for the next small test.

MinerU has `mineru==3.1.6` installed, but the legacy `magic_pdf` import path is absent. `torch==2.8.0+cpu` imports, but CUDA is not available in this env. `pip check` reports no broken requirements, so this is not a broken pip install; it is an API/package expectation mismatch. Existing code or scripts that expect `magic_pdf` will fail until the call chain is updated or a compatible legacy package is installed.

PaddleOCR has `paddleocr==3.5.0`, `paddlepaddle==3.2.2`, and `paddlex==3.5.1`. `paddleocr` and `paddle` import successfully, but `paddleocr.ppstructure` and `PPStructure` do not exist in this 3.x API. The env exposes newer names such as `PPStructureV3`, `TableStructureRecognition`, `TableRecognitionPipelineV2`, `TableCellsDetection`, and `TableClassification`. Paddle is CPU-only in this env: `paddle.is_compiled_with_cuda() == false`.

Surya has `surya-ocr==0.17.1`, `torch==2.7.1+cu118`, `transformers==4.57.3`, and `pypdfium2==4.30.0`. Base `surya` import works and torch sees CUDA. `surya.ocr` does not import, which likely means the direct API path changed. This is usable through Marker and may be usable via CLI, but a direct adapter should verify the current Surya API before test.

## Can Enter Small-Sample Testing

- First: Marker. It has a healthy env and CUDA is available.
- Second: Docling. It has a healthy env and can run a CPU-oriented smoke test.
- Optional narrow smoke: PaddleOCR OCR-only CLI, not table recovery.

## Needs Repair Before Testing

- MinerU: update the call chain for `mineru==3.1.6` or install/pin a compatible legacy `magic_pdf` package in the isolated env.
- PaddleOCR table recovery: update the invocation and normalizer expectations for PaddleOCR 3.x table APIs.
- Surya direct adapter: verify the correct API entrypoint or use CLI before any adapter test.

## Installation Or Upgrade Suggestions

No large install or upgrade was performed.

Suggested commands only:

- MinerU legacy route, only if the project decides to keep old `magic_pdf` code path: install a compatible legacy package in `parse_lab_mineru`, then rerun import smoke.
- MinerU modern route: keep `mineru==3.1.6` and update the adapter/call chain to the current package API.
- PaddleOCR GPU route, optional and not urgent: create a separate GPU env or install a matching `paddlepaddle-gpu` wheel for the local driver/CUDA target. Do not replace the current CPU env until CPU behavior is understood.
- PaddleOCR table route: first test `paddleocr table_recognition_v2` or `pp_structurev3` on 2-3 existing page images and inspect raw JSON before changing parser logic.

## Recommended Next Step

Proceed with a very small Marker smoke test first, then Docling. In parallel, diagnose PaddleOCR as a call-mode/postprocess issue rather than a missing dependency issue. Do not make PaddleOCR a trusted visual fallback until it can produce non-empty cells or usable OCR-to-cell alignment on a few known pages.

