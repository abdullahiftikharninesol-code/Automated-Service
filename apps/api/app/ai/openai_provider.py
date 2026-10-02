from openai import OpenAI

from app.schemas.ai import LeadExtractionResult


class OpenAIProvider:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def extract_lead_information(
        self, message: str, *, business_type: str = "GENERAL"
    ) -> LeadExtractionResult:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extract structured facts from a customer inquiry for a business. "
                        "Use null for every missing value and never invent details. "
                        "Classify intent, category or service, product details, quantity, "
                        "location, "
                        "preferred timing, urgency, and a concise factual summary. "
                        "Flag immediate safety hazards as EMERGENCY without giving instructions. "
                        f"The organization's optional business template is {business_type}."
                    ),
                },
                {"role": "user", "content": message},
            ],
            text_format=LeadExtractionResult,
        )
        if response.output_parsed is None:
            raise ValueError("AI provider returned no structured extraction")
        return response.output_parsed

    def generate_acknowledgement(
        self, *, customer_name: str, organization_name: str, extraction: LeadExtractionResult
    ) -> str:
        response = self.client.responses.create(
            model=self.model,
            input=(
                "Write one brief, professional acknowledgement for any type of business. "
                "Do not promise availability, delivery, or an appointment. "
                f"Customer: {customer_name}. Company: {organization_name}. "
                f"Request: {extraction.summary}"
            ),
        )
        return response.output_text.strip()

    def generate_followup_message(
        self, *, customer_name: str, service_type: str | None, preferred_time: str | None
    ) -> str:
        response = self.client.responses.create(
            model=self.model,
            input=(
                "Write one concise, friendly customer-inquiry follow-up for owner review. "
                f"Customer: {customer_name}. Topic: {service_type or 'their inquiry'}. "
                f"Preferred time: {preferred_time or 'not provided'}. Do not invent details."
            ),
        )
        return response.output_text.strip()
