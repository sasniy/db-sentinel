import smtplib
from email.mime.text import MIMEText


def send(cfg: dict, text: str, subject: str = "DB Sentinel") -> None:
    """Отправка письма через SMTP. Бросает исключение при ошибке."""
    host = (cfg.get("smtp_host") or "").strip()
    if not host:
        raise ValueError("Email: smtp_host not configured")
    port = int(cfg.get("smtp_port") or 587)
    to_addrs = [a.strip() for a in str(cfg.get("to") or "").split(",") if a.strip()]
    if not to_addrs:
        raise ValueError("Email: recipient list is empty")
    from_addr = (cfg.get("from") or cfg.get("username") or "db-sentinel@localhost").strip()

    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    with smtplib.SMTP(host, port, timeout=20) as server:
        if cfg.get("use_tls", True):
            server.starttls()
        username = (cfg.get("username") or "").strip()
        if username:
            server.login(username, cfg.get("password") or "")
        server.sendmail(from_addr, to_addrs, msg.as_string())
