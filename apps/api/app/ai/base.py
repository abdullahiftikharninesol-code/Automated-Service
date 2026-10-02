from typing import Protocol

from app.schemas.ai import LeadExtractionResult


class AIProvider(Protocol):
    def extract_lead_information(
        self, message: str, *, business_type: str = "GENERAL"
    ) -> LeadExtractionResult: ...

    def generate_acknowledgement(
        self, *, customer_name: str, organization_name: str, extraction: LeadExtractionResult
    ) -> str: ...

    def generate_followup_message(
        self, *, customer_name: str, service_type: str | None, preferred_time: str | None
    ) -> str: ...
