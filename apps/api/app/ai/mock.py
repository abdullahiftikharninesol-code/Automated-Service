import re
from typing import Any

from app.models.enums import Urgency
from app.schemas.ai import LeadExtractionResult, QualificationFieldDefinition


class MockAIProvider:
    """Deterministic, industry-neutral provider for local development and tests."""

    category_patterns = (
        (r"\b(?:dental\s+)?cleaning\b", "Dental Cleaning"),
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
        r"(dress|shirt|jacket|shoes?|bag|jeans|trousers|skirt|top|shalwar\s+kameez)\b",
        re.IGNORECASE,
    )

    def extract_lead_information(
        self,
        message: str,
        *,
        business_type: str = "GENERAL",
        qualification_fields: list[QualificationFieldDefinition] | None = None,
        current_qualifications: dict[str, Any] | None = None,
    ) -> LeadExtractionResult:
        del business_type, current_qualifications
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
        elif re.search(r"\brent\b|\bto rent\b", lowered):
            intent = "rent"
        elif re.search(r"\bbuy\b|\bpurchase\b", lowered):
            intent = "buy"
        elif re.search(r"\bsell\b", lowered):
            intent = "sell"
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

        days_pattern = (
            r"\b(tomorrow|this weekend|next week|next tuesday|next monday|next wednesday|"
            r"next thursday|next friday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
        )
        date_text = self._match_phrase(lowered, days_pattern) or self._match_phrase(
            lowered, r"\b(today)\b"
        )

        time_text = self._match_phrase(
            lowered,
            r"\b(morning|afternoon|evening|after \d{1,2}(?::\d{2})?\s?(?:am|pm)?|"
            r"\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        )
        variant = self._match_phrase(
            lowered,
            r"\b(?:size\s+)?(xxs|xs|small|medium|large|xl|xxl|\d{1,2})\b",
        )
        location = self._extract_location(normalized)
        quantity = self._extract_quantity(lowered)

        prop_match = re.search(r"\b(apartment|flat|house|villa|commercial|plot|office)\b", lowered)
        property_type = prop_match.group(1).capitalize() if prop_match else None

        budget = None
        if "budget" in lowered or "crore" in lowered or "lakh" in lowered:
            raw_b = re.search(
                r"\b(?:budget\s*(?:of|is|:)?\s*)?(\d+[\d,kKmM\s/a-zA-Z-]*)\b", message
            )
            if raw_b:
                budget = raw_b.group(0).strip()

        summary = normalized if len(normalized) <= 180 else f"{normalized[:177]}..."
        identified = any(
            (
                category,
                product_name,
                location,
                date_text,
                time_text,
                variant,
                quantity,
                property_type,
                budget,
            )
        )

        extracted_qual: dict[str, Any] = {}
        field_confidences: dict[str, float] = {}

        if qualification_fields:
            for field in qualification_fields:
                key = field.key
                val = None
                if key in ("product", "product_name", "item_name") and product_name:
                    val = product_name
                elif key in ("size", "product_variant") and variant:
                    val = variant
                elif key == "quantity" and quantity is not None:
                    val = quantity
                elif (
                    key in ("delivery_city", "location", "address_or_zip", "shipping_zip")
                    and location
                ):
                    val = location
                elif key in (
                    "customer_need",
                    "service",
                    "service_needed",
                    "treatment",
                    "category_or_service",
                ):
                    if category:
                        val = category
                    elif "consultation" in lowered:
                        val = "Consultation"
                    elif "service" in lowered:
                        val = "Service"
                    elif "repair" in lowered:
                        val = "Repair"
                    elif product_name:
                        val = product_name
                elif key in ("preferred_date", "reservation_date") and date_text:
                    val = date_text
                elif key in ("preferred_time", "reservation_time") and time_text:
                    val = time_text
                elif key == "property_type" and property_type:
                    val = property_type
                elif key == "intent":
                    val = intent
                elif key == "budget" and budget:
                    val = budget
                elif key in ("issue_description", "details"):
                    val = normalized
                elif key == "inquiry_type":
                    val = intent.replace("_", " ")

                if val is not None:
                    extracted_qual[key] = val
                    field_confidences[key] = 0.90
        else:
            # Default auto-fill if no fields specified
            if product_name:
                extracted_qual["product"] = product_name
                field_confidences["product"] = 0.90
            if variant:
                extracted_qual["size"] = variant
                field_confidences["size"] = 0.90
            if quantity is not None:
                extracted_qual["quantity"] = quantity
                field_confidences["quantity"] = 0.90
            if location:
                extracted_qual["delivery_city"] = location
                field_confidences["delivery_city"] = 0.90

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
            confidence=0.88 if identified else 0.58,
            additional_fields={},
            extracted_qualification_fields=extracted_qual,
            field_confidences=field_confidences,
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

        # Explicit delivery/shipping city
        city_match = re.search(
            r"\b(?:reach|deliver(?:ed)? to|ship(?:ped)? to|in|at)\s+"
            r"([A-Z][A-Za-z .'-]{1,50}?)(?=\s+by\b|\s+on\b|[?.!,]|$)",
            value,
        )
        if city_match:
            return city_match.group(1).strip()

        # Standalone known cities in tests/prompts
        cities = (
            "Islamabad",
            "Lahore",
            "Karachi",
            "Rawalpindi",
            "Peshawar",
            "Multan",
            "Faisalabad",
            "Austin",
            "Dallas",
            "Houston",
            "New York",
        )
        for city in cities:
            if re.search(rf"\b{city}\b", value, re.IGNORECASE):
                return city

        return None

    @staticmethod
    def _extract_quantity(value: str) -> int | None:
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        word_match = re.search(
            r"\b(one|two|three|four|five|\d{1,3})\s+(?:pieces?|items?|dresses?|shirts?|units?)\b",
            value,
            re.IGNORECASE,
        )
        if word_match:
            raw = word_match.group(1).lower()
            return words.get(raw, int(raw) if raw.isdigit() else 1)

        match = re.search(
            r"\b(?:quantity\s*[:=]?\s*|need\s+|want\s+)(\d{1,3})\b",
            value,
            re.IGNORECASE,
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
