from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import AuthResponse, RegisterRequest


class AuthenticationError(ValueError):
    pass


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register(self, payload: RegisterRequest) -> AuthResponse:
        email = payload.email.lower()
        if self.db.scalar(select(User).where(User.email == email)):
            raise ValueError("An account with that email already exists")
        organization = Organization(name=payload.organization_name, timezone=payload.timezone)
        self.db.add(organization)
        self.db.flush()
        user = User(
            organization_id=organization.id,
            name=payload.name,
            email=email,
            password_hash=hash_password(payload.password),
            role=UserRole.OWNER,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return AuthResponse(access_token=create_access_token(str(user.id)), user=user)

    def login(self, email: str, password: str) -> AuthResponse:
        user = self.db.scalar(select(User).where(User.email == email.lower()))
        if not user or not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        return AuthResponse(access_token=create_access_token(str(user.id)), user=user)
