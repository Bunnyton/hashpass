"""
The student's pool account without a terminal: log in, register, log out (spec 2026-10-16).

The TUI's login and sign-up forms call these; every failure is an `AuthError` whose text is
shown in the form as is. A failed login never turns into a sign-up -- that is its own button.
"""
from __future__ import annotations

import urllib.error
from http import HTTPStatus
from typing import TYPE_CHECKING

from hashpass.registry.creds import CredentialCache
from hashpass.registry.passwords import (
    BadLoginError,
    WeakPasswordError,
    validate_login,
    validate_password,
)
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.token import token_user

if TYPE_CHECKING:
    from hashpass.cli import Home


class AuthError(Exception):
    """A login / sign-up failure, worded for the student."""


def _client(env: Home, url: str) -> RemoteRegistry:
    return RemoteRegistry(url, cache=CredentialCache(env.creds))


def _reason(exc: urllib.error.HTTPError) -> str:
    from hashpass.cli import _http_error_reason  # noqa: PLC0415  (cli imports this module)
    return _http_error_reason(exc)


def current(env: Home) -> tuple[str, str, str]:
    """Return (pool url, user, token) from the saved pool and a live cached token; '' if none."""
    from hashpass.cli import _pool_token, _pool_url  # noqa: PLC0415
    url = _pool_url(env) or ""
    token = (_pool_token(env, url) or "") if url else ""
    user = (token_user(token) or "") if token else ""
    return url, user, token if user else ""


def _need(value: str, what: str) -> str:
    value = value.strip()
    if not value:
        msg = what
        raise AuthError(msg)
    return value


def login(env: Home, url: str, user: str, password: str) -> str:
    """Log in; cache the token, remember the pool + login; return the token."""
    from hashpass.cli import save_pool  # noqa: PLC0415
    url = _need(url, "Укажите адрес пула")
    user = _need(user, "Введите логин")
    if not password:
        msg = "Введите пароль"
        raise AuthError(msg)
    try:
        token = _client(env, url).login(user, password)
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.UNAUTHORIZED:
            msg = "Неверный логин или пароль"
            raise AuthError(msg) from exc
        msg = _reason(exc) or f"Пул ответил ошибкой {exc.code}"
        raise AuthError(msg) from exc
    except (urllib.error.URLError, RuntimeError, OSError) as exc:
        msg = f"Пул недоступен: {exc}"
        raise AuthError(msg) from exc
    save_pool(env, url, user)
    return token


def register(env: Home, url: str, user: str, password: str, password2: str,  # noqa: PLR0913, PLR0917
             group: str = "", comment: str = "") -> str:
    """Create a student account (checked here first, then by the pool); return its token."""
    from hashpass.cli import save_pool  # noqa: PLC0415
    url = _need(url, "Укажите адрес пула")
    user = _need(user, "Введите логин")
    try:
        validate_login(user)
    except BadLoginError as exc:
        msg = str(exc)
        raise AuthError(msg) from exc
    if password != password2:
        msg = "Пароли не совпадают"
        raise AuthError(msg)
    try:
        validate_password(password)
    except WeakPasswordError as exc:
        msg = str(exc)
        raise AuthError(msg) from exc
    try:
        token = _client(env, url).register(user, password, group.strip(), comment.strip())
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.CONFLICT:
            msg = f"Логин «{user}» уже занят — выберите другой"
            raise AuthError(msg) from exc
        if exc.code == HTTPStatus.FORBIDDEN:
            msg = "Регистрация на пуле закрыта — обратитесь к преподавателю"
            raise AuthError(msg) from exc
        msg = _reason(exc) or f"Пул ответил ошибкой {exc.code}"
        raise AuthError(msg) from exc
    except (urllib.error.URLError, RuntimeError, OSError) as exc:
        msg = f"Пул недоступен: {exc}"
        raise AuthError(msg) from exc
    save_pool(env, url, user)
    return token


def logout(env: Home, url: str) -> None:
    """Forget the token under every spelling of the pool URL; keep the URL, drop the login."""
    from hashpass.cli import _url_variants, save_pool  # noqa: PLC0415
    CredentialCache(env.creds).forget_variants(_url_variants(url))
    save_pool(env, url, "")
