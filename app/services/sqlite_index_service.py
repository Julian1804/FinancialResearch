import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Dict, List

from config.settings import SQLITE_DB_PATH


def ensure_sqlite_parent() -> None:
    SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_sqlite_parent()
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_def: str) -> None:
    columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def initialize_sqlite() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS company_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            source_doc_id TEXT NOT NULL,
            source_file TEXT,
            title TEXT,
            source_type TEXT,
            report_type TEXT,
            period_key TEXT,
            document_type TEXT,
            report_date TEXT,
            material_timestamp TEXT,
            material_timestamp_precision TEXT,
            is_primary_financial_report INTEGER DEFAULT 0,
            can_adjust_forecast INTEGER DEFAULT 0,
            json_path TEXT,
            updated_at TEXT,
            UNIQUE(company_name, source_doc_id)
        )
        """
        )

        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS research_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            source_doc_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            title TEXT,
            source_type TEXT,
            report_type TEXT,
            period_key TEXT,
            document_type TEXT,
            chunk_text TEXT NOT NULL,
            meta_json TEXT,
            updated_at TEXT,
            UNIQUE(company_name, chunk_id)
        )
        """
        )

        _ensure_column(conn, "company_documents", "material_timestamp", "TEXT")
        _ensure_column(conn, "company_documents", "material_timestamp_precision", "TEXT")

        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_company_documents_company
        ON company_documents(company_name)
        """
        )

        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_company_documents_period
        ON company_documents(company_name, period_key)
        """
        )

        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_research_chunks_company
        ON research_chunks(company_name)
        """
        )

        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_research_chunks_period
        ON research_chunks(company_name, period_key)
        """
        )

        conn.commit()
    finally:
        conn.close()


def upsert_company_document(doc: Dict) -> None:
    initialize_sqlite()
    conn = get_connection()
    try:
        conn.execute(
            """
        INSERT INTO company_documents (
            company_name, source_doc_id, source_file, title, source_type,
            report_type, period_key, document_type, report_date,
            material_timestamp, material_timestamp_precision,
            is_primary_financial_report, can_adjust_forecast, json_path, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_name, source_doc_id) DO UPDATE SET
            source_file=excluded.source_file,
            title=excluded.title,
            source_type=excluded.source_type,
            report_type=excluded.report_type,
            period_key=excluded.period_key,
            document_type=excluded.document_type,
            report_date=excluded.report_date,
            material_timestamp=excluded.material_timestamp,
            material_timestamp_precision=excluded.material_timestamp_precision,
            is_primary_financial_report=excluded.is_primary_financial_report,
            can_adjust_forecast=excluded.can_adjust_forecast,
            json_path=excluded.json_path,
            updated_at=excluded.updated_at
        """,
            (
                doc.get("company_name", ""),
                doc.get("source_doc_id", ""),
                doc.get("source_file", ""),
                doc.get("title", ""),
                doc.get("source_type", ""),
                doc.get("report_type", ""),
                doc.get("period_key", ""),
                doc.get("document_type", ""),
                doc.get("report_date", ""),
                doc.get("material_timestamp", ""),
                doc.get("material_timestamp_precision", ""),
                1 if doc.get("is_primary_financial_report") else 0,
                1 if doc.get("can_adjust_forecast") else 0,
                doc.get("json_path", ""),
                doc.get("updated_at", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def replace_company_chunks(company_name: str, chunks: List[Dict]) -> None:
    initialize_sqlite()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM research_chunks WHERE company_name = ?", (company_name,))
        for chunk in chunks:
            conn.execute(
                """
            INSERT INTO research_chunks (
                company_name, source_doc_id, chunk_id, title, source_type,
                report_type, period_key, document_type, chunk_text,
                meta_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    company_name,
                    chunk.get("source_doc_id", ""),
                    chunk.get("chunk_id", ""),
                    chunk.get("title", ""),
                    chunk.get("source_type", ""),
                    chunk.get("report_type", ""),
                    chunk.get("period_key", ""),
                    chunk.get("document_type", ""),
                    chunk.get("chunk_text", ""),
                    json.dumps(chunk.get("meta", {}), ensure_ascii=False),
                    chunk.get("updated_at", ""),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def fetch_company_documents(company_name: str) -> List[Dict]:
    initialize_sqlite()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
        SELECT *
        FROM company_documents
        WHERE company_name = ?
        ORDER BY
            CASE
                WHEN period_key GLOB '[12][09][0-9][0-9]*' THEN CAST(substr(period_key, 1, 4) AS INTEGER)
                ELSE 9999
            END,
            CASE WHEN period_key GLOB '[12][09][0-9][0-9]Q1' THEN 1
                 WHEN period_key GLOB '[12][09][0-9][0-9]H1' THEN 2
                 WHEN period_key GLOB '[12][09][0-9][0-9]Q3' THEN 3
                 WHEN period_key GLOB '[12][09][0-9][0-9]FY' THEN 4
                 WHEN period_key GLOB '[12][09][0-9][0-9]AUX' THEN 5
                 ELSE 99 END,
            COALESCE(material_timestamp, ''),
            CASE source_type
                 WHEN 'extracted' THEN 1
                 WHEN 'report' THEN 2
                 WHEN 'forecast_snapshot' THEN 3
                 WHEN 'forecast_check' THEN 4
                 WHEN 'parsed' THEN 5
                 ELSE 9 END,
            source_file
        """,
            (company_name,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_company_chunks(company_name: str) -> List[Dict]:
    initialize_sqlite()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
        SELECT *
        FROM research_chunks
        WHERE company_name = ?
        """,
            (company_name,),
        ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            try:
                item["meta_json"] = json.loads(item.get("meta_json") or "{}")
            except Exception:
                item["meta_json"] = {}
            results.append(item)
        return results
    finally:
        conn.close()


def tokenize_text(text: str) -> List[str]:
    text = (text or "").lower().strip()
    if not text:
        return []

    english_parts = re.findall(r"[a-z0-9_]+", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)

    bigrams = []
    pure_cn = "".join(chinese_chars)
    if len(pure_cn) >= 2:
        for i in range(len(pure_cn) - 1):
            bigrams.append(pure_cn[i:i + 2])

    tokens = english_parts + chinese_chars + bigrams
    return [t for t in tokens if t.strip()]


def _term_freq(tokens: List[str]) -> Dict[str, float]:
    freq: Dict[str, float] = {}
    if not tokens:
        return freq
    for token in tokens:
        freq[token] = freq.get(token, 0.0) + 1.0
    total = float(len(tokens))
    for key in list(freq.keys()):
        freq[key] = freq[key] / total
    return freq


def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0

    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_company_chunks(company_name: str, query: str, top_k: int = 8) -> List[Dict]:
    all_chunks = fetch_company_chunks(company_name)
    if not all_chunks:
        return []

    query_tokens = tokenize_text(query)
    query_tf = _term_freq(query_tokens)

    scored = []
    for chunk in all_chunks:
        text = chunk.get("chunk_text", "") or ""
        title = chunk.get("title", "") or ""
        combined = f"{title}\n{text}"

        doc_tokens = tokenize_text(combined)
        doc_tf = _term_freq(doc_tokens)

        cosine = _cosine_similarity(query_tf, doc_tf)
        overlap_count = len(set(query_tokens) & set(doc_tokens))
        overlap_score = overlap_count / max(1, len(set(query_tokens)))

        exact_bonus = 0.0
        if query.strip() and query.strip().lower() in combined.lower():
            exact_bonus = 0.2

        period_bonus = 0.03 if chunk.get("period_key") else 0.0
        timestamp_bonus = 0.02 if chunk.get("meta_json", {}).get("material_timestamp") else 0.0
        final_score = cosine * 0.63 + overlap_score * 0.30 + exact_bonus + period_bonus + timestamp_bonus

        item = {
            "chunk_id": chunk.get("chunk_id", ""),
            "source_doc_id": chunk.get("source_doc_id", ""),
            "title": chunk.get("title", ""),
            "source_type": chunk.get("source_type", ""),
            "report_type": chunk.get("report_type", ""),
            "period_key": chunk.get("period_key", ""),
            "document_type": chunk.get("document_type", ""),
            "chunk_text": text,
            "meta": chunk.get("meta_json", {}),
            "score": round(final_score, 6),
        }
        scored.append(item)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
