import os
import smtplib
import ssl
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from email.message import EmailMessage


class EmailDeliveryError(RuntimeError):
    pass


class SMTPCodeSender:
    """Send short-lived login codes without tying the server to one mail provider."""

    def __init__(self):
        self.host = os.environ.get("OFFLINECHAT_SMTP_HOST", "").strip()
        self.port = int(os.environ.get("OFFLINECHAT_SMTP_PORT", "587"))
        self.username = os.environ.get("OFFLINECHAT_SMTP_USERNAME", "").strip()
        self.password = os.environ.get("OFFLINECHAT_SMTP_PASSWORD", "")
        self.sender = os.environ.get("OFFLINECHAT_SMTP_FROM", self.username).strip()
        self.use_ssl = os.environ.get("OFFLINECHAT_SMTP_SSL", "").lower() in ("1", "true", "yes")

    @property
    def configured(self):
        return bool(self.host and self.sender)

    def send_code(self, address, code, purpose):
        if not self.configured:
            raise EmailDeliveryError("email delivery is not configured on the server")
        message = EmailMessage()
        message["Subject"] = "Код входа в Связь"
        message["From"] = self.sender
        message["To"] = address
        action = "регистрации" if purpose == "register" else "входа"
        message.set_content(
            "Код для %s: %s\n\nКод действует 10 минут. "
            "Если вы не запрашивали его, просто удалите это письмо." % (action, code)
        )
        try:
            if self.use_ssl:
                connection = smtplib.SMTP_SSL(self.host, self.port, timeout=12,
                                               context=ssl.create_default_context())
            else:
                connection = smtplib.SMTP(self.host, self.port, timeout=12)
            with connection:
                if not self.use_ssl:
                    connection.starttls(context=ssl.create_default_context())
                if self.username:
                    connection.login(self.username, self.password)
                connection.send_message(message)
        except Exception as error:
            raise EmailDeliveryError("could not send verification email") from error


class MemoryCodeSender:
    """Test sender. Codes never enter an HTTP response."""

    def __init__(self):
        self.messages = []

    def send_code(self, address, code, purpose):
        self.messages.append({"address": address, "code": code, "purpose": purpose})


class BrevoCodeSender:
    """HTTPS delivery works on PythonAnywhere free accounts through its proxy."""

    def __init__(self):
        self.api_key = os.environ.get("OFFLINECHAT_BREVO_API_KEY", "").strip()
        self.sender = os.environ.get("OFFLINECHAT_EMAIL_FROM", "").strip()
        self.sender_name = os.environ.get("OFFLINECHAT_EMAIL_FROM_NAME", "Связь").strip() or "Связь"

    @property
    def configured(self):
        return bool(self.api_key and self.sender)

    def send_code(self, address, code, purpose):
        if not self.configured:
            raise EmailDeliveryError("email delivery is not configured on the server")
        action = "регистрации" if purpose == "register" else "входа"
        payload = json.dumps({
            "sender": {"email": self.sender, "name": self.sender_name},
            "to": [{"email": address}],
            "subject": "Код входа в Связь",
            "textContent": "Код для %s: %s\n\nКод действует 10 минут. "
                           "Если вы не запрашивали его, просто удалите это письмо." % (action, code),
        }, ensure_ascii=False).encode("utf-8")
        request = Request("https://api.brevo.com/v3/smtp/email", data=payload, method="POST", headers={
            "api-key": self.api_key,
            "accept": "application/json",
            "content-type": "application/json",
        })
        try:
            with urlopen(request, timeout=12) as response:
                if response.status not in (200, 201, 202):
                    raise EmailDeliveryError("could not send verification email")
        except (HTTPError, URLError, TimeoutError) as error:
            raise EmailDeliveryError("could not send verification email") from error


def configured_code_sender():
    brevo = BrevoCodeSender()
    return brevo if brevo.configured else SMTPCodeSender()
