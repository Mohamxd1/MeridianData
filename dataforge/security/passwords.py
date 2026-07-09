from __future__ import annotations

from passlib.context import CryptContext


password_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


class PasswordPolicyError(ValueError):
    pass


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise PasswordPolicyError("Password must be at least 12 characters long.")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return password_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_context.verify(password, hashed_password)
