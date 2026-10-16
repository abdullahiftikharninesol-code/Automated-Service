from __future__ import annotations

import logging

import phonenumbers

logger = logging.getLogger("missed_lead_rescue.phone")


def normalize_phone_number(
    raw_phone: str | None, default_region: str | None = None
) -> str | None:
    """Normalize phone number to E.164 format (+15125550100).

    Behavior:
    - If the number contains an international prefix ('+'), parse and normalize directly.
    - If no '+' prefix, parse using the organization's default_region (e.g. 'US', 'PK', 'GB').
    - If no reliable region is provided and there is no '+' prefix, return None rather
      than guessing.
    - If parsing fails or the number is invalid, return None.
    """
    if not raw_phone or not raw_phone.strip():
        return None

    cleaned = raw_phone.strip()
    region = default_region.strip().upper() if default_region and default_region.strip() else None

    # If no '+' and no default_region, we cannot reliably determine the country.
    if not cleaned.startswith("+") and not region:
        return None

    try:
        parsed = phonenumbers.parse(cleaned, region)
        if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        logger.debug("Failed to parse phone number: %s (region: %s)", cleaned, region)
    except Exception as exc:  # Safety boundary
        logger.warning("Unexpected error during phone normalization: %s", exc)

    return None
