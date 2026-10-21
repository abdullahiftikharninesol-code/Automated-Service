import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import QualificationFieldType, QualificationStatus
from app.models.qualification import QualificationField
from app.schemas.ai import QualificationFieldDefinition
from app.schemas.qualification import (
    QualificationFieldCreate,
    QualificationFieldUpdate,
)
from app.services.qualification_templates import QUALIFICATION_TEMPLATES

logger = logging.getLogger("missed_lead_rescue.qualification")


class QualificationService:
    def __init__(self, db: Session, min_confidence: float = 0.65):
        self.db = db
        self.min_confidence = min_confidence

    def get_enabled_fields(self, organization_id: uuid.UUID) -> list[QualificationField]:
        return list(
            self.db.scalars(
                select(QualificationField)
                .where(
                    QualificationField.organization_id == organization_id,
                    QualificationField.enabled.is_(True),
                )
                .order_by(QualificationField.sort_order.asc(), QualificationField.created_at.asc())
            )
        )

    def get_field_definitions(
        self, organization_id: uuid.UUID
    ) -> list[QualificationFieldDefinition]:
        fields = self.get_enabled_fields(organization_id)
        return [
            QualificationFieldDefinition(
                key=f.key,
                label=f.label,
                field_type=f.field_type.value,
                required=f.required,
                description=f.description,
                options=f.options,
                example_values=f.example_values,
            )
            for f in fields
        ]

    def merge_qualifications(
        self,
        current: dict[str, Any],
        extracted: dict[str, Any],
        confidences: dict[str, float] | None = None,
        allowed_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Merge newly extracted fields into current qualifications safely.

        Rules:
        - Only merge keys defined in allowed_keys (if provided).
        - A new non-empty value overrides old value if confidence >= min_confidence.
        - None or empty string from extraction never erases an existing confirmed value.
        - Preserves clean dictionary data without arbitrary DB mutation.
        """
        merged = dict(current or {})
        conf_map = confidences or {}

        for key, new_val in extracted.items():
            if allowed_keys is not None and key not in allowed_keys:
                continue

            if new_val is None or (isinstance(new_val, str) and not new_val.strip()):
                continue

            conf = conf_map.get(key, 1.0)
            if conf < self.min_confidence:
                logger.debug(
                    "[QUALIFICATION] Skipping field '%s' due to low confidence (%.2f < %.2f)",
                    key,
                    conf,
                    self.min_confidence,
                )
                continue

            # Clean and store value
            if isinstance(new_val, str):
                cleaned_val = new_val.strip()
            else:
                cleaned_val = new_val

            merged[key] = cleaned_val

        return merged

    def get_missing_required_fields(
        self, organization_id: uuid.UUID, qualifications: dict[str, Any]
    ) -> list[QualificationField]:
        enabled_fields = self.get_enabled_fields(organization_id)
        missing: list[QualificationField] = []

        for field in enabled_fields:
            if not field.required:
                continue
            val = qualifications.get(field.key)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(field)

        return missing

    def evaluate_qualification_status(
        self, organization_id: uuid.UUID, qualifications: dict[str, Any]
    ) -> tuple[QualificationStatus, list[QualificationField]]:
        enabled_fields = self.get_enabled_fields(organization_id)
        if not enabled_fields:
            return QualificationStatus.NOT_STARTED, []

        required_fields = [f for f in enabled_fields if f.required]
        if not required_fields:
            # If no fields are required, qualification is trivially complete
            return QualificationStatus.COMPLETE, []

        missing = self.get_missing_required_fields(organization_id, qualifications)
        if not missing:
            return QualificationStatus.COMPLETE, []

        # If any required field has been collected, or missing fields exist
        has_any_data = any(qualifications.get(f.key) is not None for f in enabled_fields)
        if has_any_data:
            return QualificationStatus.IN_PROGRESS, missing
        return QualificationStatus.IN_PROGRESS, missing

    # CRUD operations
    def list_fields(
        self, organization_id: uuid.UUID, enabled_only: bool = False
    ) -> list[QualificationField]:
        stmt = select(QualificationField).where(
            QualificationField.organization_id == organization_id
        )
        if enabled_only:
            stmt = stmt.where(QualificationField.enabled.is_(True))
        stmt = stmt.order_by(
            QualificationField.sort_order.asc(), QualificationField.created_at.asc()
        )
        return list(self.db.scalars(stmt))

    def get_field(
        self, organization_id: uuid.UUID, field_id: uuid.UUID
    ) -> QualificationField | None:
        return self.db.scalar(
            select(QualificationField).where(
                QualificationField.id == field_id,
                QualificationField.organization_id == organization_id,
            )
        )

    def create_field(
        self, organization_id: uuid.UUID, payload: QualificationFieldCreate
    ) -> QualificationField:
        existing = self.db.scalar(
            select(QualificationField).where(
                QualificationField.organization_id == organization_id,
                QualificationField.key == payload.key,
            )
        )
        if existing:
            raise ValueError(f"Field with key '{payload.key}' already exists for this organization")

        field = QualificationField(
            organization_id=organization_id,
            key=payload.key,
            label=payload.label,
            description=payload.description,
            field_type=payload.field_type,
            required=payload.required,
            enabled=payload.enabled,
            sort_order=payload.sort_order,
            question_text=payload.question_text,
            options=payload.options,
            example_values=payload.example_values,
        )
        self.db.add(field)
        self.db.commit()
        self.db.refresh(field)
        return field

    def update_field(
        self, organization_id: uuid.UUID, field_id: uuid.UUID, payload: QualificationFieldUpdate
    ) -> QualificationField | None:
        field = self.get_field(organization_id, field_id)
        if not field:
            return None

        for attr, val in payload.model_dump(exclude_unset=True).items():
            setattr(field, attr, val)

        self.db.commit()
        self.db.refresh(field)
        return field

    def delete_field(self, organization_id: uuid.UUID, field_id: uuid.UUID) -> bool:
        field = self.get_field(organization_id, field_id)
        if not field:
            return False
        self.db.delete(field)
        self.db.commit()
        return True

    def apply_template(
        self, organization_id: uuid.UUID, template_name: str, replace_existing: bool = False
    ) -> list[QualificationField]:
        template_upper = template_name.strip().upper()
        specs = QUALIFICATION_TEMPLATES.get(template_upper)
        if not specs:
            valid_templates = ", ".join(QUALIFICATION_TEMPLATES.keys())
            raise ValueError(
                f"Unknown template '{template_name}'. Available templates: {valid_templates}"
            )

        if replace_existing:
            existing = self.list_fields(organization_id)
            for f in existing:
                self.db.delete(f)
            self.db.flush()

        created_fields: list[QualificationField] = []
        for spec in specs:
            existing = self.db.scalar(
                select(QualificationField).where(
                    QualificationField.organization_id == organization_id,
                    QualificationField.key == spec.key,
                )
            )
            if existing:
                existing.label = spec.label
                existing.field_type = spec.field_type
                existing.required = spec.required
                existing.sort_order = spec.sort_order
                existing.question_text = spec.question_text
                existing.description = spec.description
                existing.options = spec.options
                existing.example_values = spec.example_values
                existing.enabled = True
                created_fields.append(existing)
            else:
                field = QualificationField(
                    organization_id=organization_id,
                    key=spec.key,
                    label=spec.label,
                    description=spec.description,
                    field_type=spec.field_type,
                    required=spec.required,
                    enabled=True,
                    sort_order=spec.sort_order,
                    question_text=spec.question_text,
                    options=spec.options,
                    example_values=spec.example_values,
                )
                self.db.add(field)
                created_fields.append(field)

        self.db.commit()
        for f in created_fields:
            self.db.refresh(f)
        return created_fields


class QualificationQuestionService:
    """Generates customer clarification questions deterministically from field definitions."""

    @staticmethod
    def generate_clarification_question(
        missing_fields: list[QualificationField], max_fields: int = 2
    ) -> tuple[str, list[str]]:
        """Returns (question_message, list_of_field_keys_asked)."""
        if not missing_fields:
            return "", []

        fields_to_ask = missing_fields[:max_fields]
        keys_asked = [f.key for f in fields_to_ask]

        if len(fields_to_ask) == 1:
            f = fields_to_ask[0]
            if f.question_text and f.question_text.strip():
                return f.question_text.strip(), keys_asked
            return QualificationQuestionService._fallback_question(f), keys_asked

        # Two fields to ask together
        f1, f2 = fields_to_ask[0], fields_to_ask[1]
        q1 = (
            f1.question_text.strip().rstrip("?")
            if f1.question_text
            else QualificationQuestionService._fallback_prompt(f1)
        )
        q2 = (
            f2.question_text.strip().rstrip("?")
            if f2.question_text
            else QualificationQuestionService._fallback_prompt(f2)
        )

        second_part = (
            q2.lower()
            if not q2.startswith("Which") and not q2.startswith("Where")
            else q2
        )
        combined = f"Sure! {q1}, and {second_part}?"
        return combined, keys_asked

    @staticmethod
    def _fallback_question(field: QualificationField) -> str:
        prompt = QualificationQuestionService._fallback_prompt(field)
        return f"{prompt}?"

    @staticmethod
    def _fallback_prompt(field: QualificationField) -> str:
        label = field.label.strip()
        ft = field.field_type

        if ft == QualificationFieldType.CHOICE and field.options:
            opts = ", ".join(str(o) for o in field.options)
            return f"Which {label.lower()} would you prefer ({opts})"
        elif ft in (QualificationFieldType.DATE, QualificationFieldType.DATETIME):
            return f"What date works best for your {label.lower()}"
        elif ft == QualificationFieldType.LOCATION:
            return f"Which city or address should we use for your {label.lower()}"
        elif ft == QualificationFieldType.NUMBER:
            return f"How many {label.lower()} would you like"
        else:
            return f"What {label.lower()} would you prefer"
