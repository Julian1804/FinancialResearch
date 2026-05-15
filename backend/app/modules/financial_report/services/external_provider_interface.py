from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExternalProviderFact:
    canonical_field: str
    value: float
    unit: str
    currency: str
    period: str
    fiscal_year: int
    fiscal_period_type: str
    source_pdf: str
    provider_name: str
    provider_type: str
    retrieved_at: datetime
    source_url_or_reference: str
    is_simulated: bool
    confidence: float


class ExternalFinancialDataProvider(ABC):
    provider_name: str
    provider_type: str
    is_simulated: bool

    @abstractmethod
    def fetch_canonical_facts(self, source_pdfs: list[str]) -> list[ExternalProviderFact]:
        raise NotImplementedError


class SimulatedExternalFinancialDataProvider(ExternalFinancialDataProvider):
    provider_name = "simulated_authoritative_external_provider"
    provider_type = "mock_external_provider"
    is_simulated = True

    def fetch_canonical_facts(self, source_pdfs: list[str]) -> list[ExternalProviderFact]:
        retrieved_at = datetime.utcnow()
        values: dict[str, dict[str, float]] = {
            "泡泡玛特2025年中报.pdf": {
                "revenue": 13876000000,
                "gross_profit": 9742000000,
                "operating_profit": 4733000000,
                "net_profit_attributable_to_parent": 4681700000,
                "total_assets": 28650000000,
                "total_liabilities": 8020000000,
                "total_equity": 20630000000,
                "cash_and_cash_equivalents": 10680000000,
                "cost": 4134000000,
            },
            "华钰矿业2025年半年报.pdf": {
                "revenue": 588000000,
                "net_profit": 124000000,
                "total_assets": 514042225.98,
                "total_liabilities": 369971038.66,
                "total_equity": 144071187.32,
                "operating_cash_flow": 77000000,
                "cash_and_cash_equivalents": 98000000,
                "cost": 355000000,
                "expense": 46000000,
            },
        }
        facts: list[ExternalProviderFact] = []
        for source_pdf in source_pdfs:
            period, fiscal_year, fiscal_period_type = _period_from_pdf_name(source_pdf)
            for canonical_field, value in values.get(source_pdf, {}).items():
                facts.append(
                    ExternalProviderFact(
                        canonical_field=canonical_field,
                        value=value,
                        unit="yuan",
                        currency="CNY",
                        period=period,
                        fiscal_year=fiscal_year or 0,
                        fiscal_period_type=fiscal_period_type,
                        source_pdf=source_pdf,
                        provider_name=self.provider_name,
                        provider_type=self.provider_type,
                        retrieved_at=retrieved_at,
                        source_url_or_reference=f"mock://parse_lab_round3/{source_pdf}/{canonical_field}",
                        is_simulated=True,
                        confidence=0.9,
                    )
                )
        return facts


class RealExternalFinancialDataProvider(ExternalFinancialDataProvider):
    provider_name = "unconfigured_real_external_provider"
    provider_type = "real_external_provider"
    is_simulated = False

    def fetch_canonical_facts(self, source_pdfs: list[str]) -> list[ExternalProviderFact]:
        return []


def _period_from_pdf_name(source_pdf: str) -> tuple[str, int | None, str]:
    import re

    match = re.search(r"20\d{2}", source_pdf)
    if not match:
        return "", None, ""
    fiscal_year = int(match.group(0))
    if "中报" in source_pdf or "半年" in source_pdf or "interim" in source_pdf.lower():
        return f"FY{fiscal_year}_H1", fiscal_year, "interim_h1"
    if "年报" in source_pdf or "annual" in source_pdf.lower():
        return f"FY{fiscal_year}", fiscal_year, "annual"
    return "", fiscal_year, ""
