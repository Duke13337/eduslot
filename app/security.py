"""AuthController: хеширование паролей, сессии, проверка прав доступа."""

import hashlib
import hmac
import os
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from .config import SECRET_KEY, SESSION_MAX_AGE
from .database import get_session
from .models import User

PBKDF2_ITERATIONS = 200_000


# --- Пароли ----------------------------------------------------------------

def hash_password(password: str) -> str:
    """PBKDF2-SHA256 со случайной солью. Формат: pbkdf2$iters$salt$hash."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


class AuthController:
    """Модуль безопасности: аутентификация, сессия и разграничение прав."""

    def __init__(
        self,
        secret_key: str = SECRET_KEY,
        token_expire: int = SESSION_MAX_AGE,
        algorithm: str = "HS256",
    ):
        self.secret_key = secret_key
        self.token_expire = token_expire
        self.algorithm = algorithm

    def authenticate(self, session: Session, username: str, password: str) -> Optional[User]:
        """Проверить логин/пароль и вернуть пользователя."""
        user = session.exec(select(User).where(User.username == username.strip())).first()
        if not user or not user.login(password):
            return None
        return user

    def start_session(self, request: Request, user: User) -> None:
        """Открыть сессию пользователя после успешного входа."""
        request.session.clear()
        request.session["uid"] = user.id

    def end_session(self, request: Request) -> None:
        """Завершить сессию пользователя."""
        request.session.clear()

    def current_user(self, request: Request, session: Session) -> Optional[User]:
        """Пользователь из cookie-сессии или None."""
        user_id = request.session.get("uid")
        if not user_id:
            return None
        return session.get(User, int(user_id))


auth_controller = AuthController()


def authenticate(session: Session, username: str, password: str) -> Optional[User]:
    return auth_controller.authenticate(session, username, password)


# --- Сессия и текущий пользователь ----------------------------------------

class LoginRequired(Exception):
    """Пользователь не авторизован — нужно перенаправить на /login."""

    def __init__(self, next_url: str = "/schedule"):
        self.next_url = next_url


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional[User]:
    return auth_controller.current_user(request, session)


def require_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    user = get_current_user(request, session)
    if not user:
        raise LoginRequired(next_url=request.url.path)
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для администратора",
        )
    return user


# --- Всплывающие сообщения --------------------------------------------------

def flash(request: Request, message: str, category: str = "success") -> None:
    messages = request.session.get("flash", [])
    messages.append({"message": message, "category": category})
    request.session["flash"] = messages


def pop_flash(request: Request) -> list[dict]:
    return request.session.pop("flash", [])


def login_url(next_url: str | None = None) -> str:
    if next_url and next_url not in ("/", "/login"):
        return f"/login?next={quote(next_url)}"
    return "/login"
