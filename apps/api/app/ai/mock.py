import re

from app.models.enums import Urgency
from app.schemas.ai import LeadExtractionResult


class MockAIProvider:
    """Deterministic, industry-neutral provider for local development and tests."""

    category_patterns = (
        (r"\b(?:dental )?cleaning\b", "Dental Cleaning"),
        (r"\b(?:ac|air conditioner).*(?:install|replacement)|\bnew ac\b", "AC Installation"),
        (r"\bfurnace\b|\bno heat\b|\bheating\b", "Heating Repair"),
        (r"\bthermostat\b", "Thermostat Service"),
        (r"\bducts?\b", "Duct Service"),
        (r"\bmaintenance\b|\btune.?up\b", "HVAC Maintenance"),
        (r"\bac\b|air condition|not cooling|stopped cooling", "AC Repair"),
        (r"\bhaircut\b|\bhair appointment\b", "Hair Appointment"),
        (r"\bproperty viewing\b|\bhouse viewing\b", "Property Viewing"),
    )
    product_pattern = re.compile(
        r"\b((?:black|white|red|blue|green|navy|beige|brown)\s+)?"
        r"(dress|shirt|jacket|shoes?|bag|jeans|trousers|skirt|top)\b",
        re.IGNORECASE,
    )

    def extract_lead_information(
        self, message: str, *, business_type: str = "GENERAL"
    ) -> LeadExtractionResult:
        del business_type  # These deterministic rules are shared across every template.
        normalized = " ".join(message.split())
        lowered = normalized.lower()

        category = next(
            (label for pattern, label in self.category_patterns if re.search(pattern, lowered)),
            None,
        )
        product_match = self.product_pattern.search(normalized)
        product_name = product_match.group(0).lower() if product_match else None

        if re.search(r"\bappointment\b|\bbook (?:a|an)\b", lowered):
            intent = "appointment_request"
        elif product_name or re.search(r"\bdo you have\b|\bin stock\b|\bdeliver\b", lowered):
            intent = "purchase_inquiry"
        elif category or re.search(r"\brepair\b|\bservice\b|\bstopped\b|\bbroken\b", lowered):
            intent = "service_request"
        elif re.search(r"\bquote\b|\bestimate\b|\bpricing\b|\bprice\b", lowered):
            intent = "quote_request"
        else:
            intent = "general_inquiry"

        if re.search(r"gas smell|carbon monoxide|smoke|fire|sparks?", lowered):
            urgency = Urgency.EMERGENCY
        elif re.search(r"emergency|urgent|today|extremely hot|no heat|stopped", lowered):
            urgency = Urgency.HIGH
        elif re.search(r"pricing|quote|estimate|planning", lowered):
            urgency = Urgency.LOW
        else:
            urgency = Urgency.NORMAL

        date_text = self._match_phrase(
            lowered,
            r"\b(tomorrow|this weekend|next week|monday|tuesday|wednesday|"
            r"thursday|friday|saturday|sunday)\b",
        ) or self._match_phrase(lowered, r"\b(today)\b")
        time_text = self._match_phrase(
            lowered,
            r"\b(morning|afternoon|evening|after \d{1,2}(?::\d{2})?\s?(?:am|pm)?)\b",
        )
        variant = self._match_phrase(
            lowered,
            r"\b(?:size\s+)?(xxs|xs|small|medium|large|xl|xxl|\d{1,2})\b",
        )
        location = self._extract_location(normalized)
        quantity = self._extract_quantity(lowered)
        summary = normalized if len(normalized) <= 180 else f"{normalized[:177]}..."
        identified = any((category, product_name, location, date_text, time_text, variant))
        return LeadExtractionResult(
            intent=intent,
            category_or_service=category,
            urgency=urgency,
            location=location,
            preferred_date=date_text,
            preferred_time=time_text,
            product_name=product_name,
            product_variant=variant,
            quantity=quantity,
            summary=summary,
            confidence=0.86 if identified else 0.58,
            additional_fields={},
        )

    @staticmethod
    def _match_phrase(value: str, pattern: str) -> str | None:
        match = re.search(pattern, value)
        return match.group(1).capitalize() if match else None

    @staticmethod
    def _extract_location(value: str) -> str | None:
        zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", value)
        if zip_match:
            return zip_match.group(0)
        city_match = re.search(
            r"\b(?:reach|deliver(?:ed)? to|ship(?:ped)? to)\s+"
            r"([A-Z][A-Za-z .'-]{1,50}?)(?=\s+by\b|\s+on\b|[?.!,]|$)",
            value,
        )
        return city_match.group(1).strip() if city_match else None

    @staticmethod
    def _extract_quantity(value: str) -> int | None:
        match = re.search(
            r"\b(?:quantity\s*[:=]?\s*|need\s+|want\s+)?(\d{1,3})\s+"
            r"(?:items?|pieces?|dresses|shirts|units?)\b",
            value,
        )
        return int(match.group(1)) if match else None

    def generate_acknowledgement(
        self, *, customer_name: str, organization_name: str, extraction: LeadExtractionResult
    ) -> str:
        del customer_name
        topic = extraction.product_name or extraction.category_or_service
        if topic:
            return (
                f"Thanks for contacting {organization_name}. "
                f"We received your inquiry about {topic}."
            )
        return f"Thanks for contacting {organization_name}. We received your inquiry."

    def generate_followup_message(
        self, *, customer_name: str, service_type: str | None, preferred_time: str | None
    ) -> str:
        topic = (service_type or "your inquiry").lower()
        timing = f" Would {preferred_time} still work for you?" if preferred_time else ""
        return f"Hi {customer_name}, just following up about {topic}.{timing}"
