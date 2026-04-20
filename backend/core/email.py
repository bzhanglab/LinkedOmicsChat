"""
SMTP email delivery helpers.
"""
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import quote
import logging
import smtplib
import ssl

from core.config import settings

logger = logging.getLogger(__name__)


def email_delivery_configured() -> bool:
    """Return True when SMTP settings are sufficient to send emails."""
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def _sender_header() -> str:
    return formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))


def verification_link(token: str) -> str:
    base_url = settings.APP_BASE_URL.rstrip("/")
    return f"{base_url}/verify-email?token={quote(token)}"


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send a single email through the configured SMTP server."""
    if not email_delivery_configured():
        raise RuntimeError("SMTP email delivery is not configured")

    if settings.SMTP_USE_SSL and settings.SMTP_USE_TLS:
        raise RuntimeError("SMTP_USE_SSL and SMTP_USE_TLS cannot both be enabled")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _sender_header()
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    if settings.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as server:
            _login_if_needed(server)
            server.send_message(message)
            return

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        if settings.SMTP_USE_TLS:
            server.starttls(context=context)
        _login_if_needed(server)
        server.send_message(message)


def _login_if_needed(server: smtplib.SMTP) -> None:
    if settings.SMTP_USERNAME:
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)


def send_verification_email(username: str, email: str, token: str) -> None:
    """Send the registration verification email."""
    link = verification_link(token)
    subject = "Confirm your LinkedOmicsChat account"
    text_body = (
        f"Hi {username},\n\n"
        "Thanks for signing up for LinkedOmicsChat.\n"
        "Please confirm your email address by opening this link:\n\n"
        f"{link}\n\n"
        f"This link expires in {settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS} hours.\n\n"
        "If you did not create this account, you can ignore this email."
    )
    html_body = (
        f"<p>Hi {username},</p>"
        "<p>Thanks for signing up for <strong>LinkedOmicsChat</strong>.</p>"
        f"<p>Please confirm your email address by clicking "
        f"<a href=\"{link}\">this verification link</a>.</p>"
        f"<p>This link expires in {settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS} hours.</p>"
        "<p>If you did not create this account, you can ignore this email.</p>"
    )
    send_email(email, subject, text_body, html_body=html_body)
    logger.info("Verification email sent to %s", email)
