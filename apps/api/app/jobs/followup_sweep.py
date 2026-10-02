import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.services.followups import FollowUpService


class FollowUpSweepJob:
    def __init__(self, db: Session, organization_id: uuid.UUID, now: datetime | None = None):
        self.db = db
        self.organization_id = organization_id
        self.now = now

    def run(self) -> int:
        processed = FollowUpService(self.db).process_due(self.organization_id, self.now)
        self.db.commit()
        return processed
