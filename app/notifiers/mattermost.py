import requests


def send(cfg: dict, text: str) -> None:
    """Отправка личного сообщения в Mattermost через REST API v4.

    Нужны: base_url, Personal Access Token и получатель (user id или @username).
    Бот/пользователь токена создаёт direct-канал с получателем и пишет туда.
    """
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    target = (cfg.get("user") or "").strip()
    if not base or not token or not target:
        raise ValueError("Mattermost: base_url / token / user not configured")

    headers = {"Authorization": f"Bearer {token}"}

    def api(method: str, path: str, **kw):
        resp = requests.request(method, f"{base}/api/v4{path}",
                                headers=headers, timeout=15, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"Mattermost API {path}: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    me = api("GET", "/users/me")

    if target.startswith("@"):
        target_user = api("GET", f"/users/username/{target[1:]}")
        target_id = target_user["id"]
    else:
        target_id = target

    channel = api("POST", "/channels/direct", json=[me["id"], target_id])
    api("POST", "/posts", json={"channel_id": channel["id"], "message": text})
