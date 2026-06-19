import json
import os
import base64
import urllib.request

import requests
from nacl import encoding, public

REPO = os.environ["GITHUB_REPOSITORY"]
GH_PAT = os.environ["GH_PAT"]
KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_CLIENT_SECRET = os.environ["KAKAO_CLIENT_SECRET"]
KAKAO_REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]

ALERTS_FILE = "alerts.json"


def refresh_kakao_token():
    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": KAKAO_REST_API_KEY,
            "client_secret": KAKAO_CLIENT_SECRET,
            "refresh_token": KAKAO_REFRESH_TOKEN,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], data.get("refresh_token")


def update_github_secret(secret_name, secret_value):
    headers = {
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github+json",
    }
    pub_key_resp = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers=headers,
    )
    pub_key_resp.raise_for_status()
    pub_key_data = pub_key_resp.json()

    public_key = public.PublicKey(pub_key_data["key"], encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    put_resp = requests.put(
        f"https://api.github.com/repos/{REPO}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": pub_key_data["key_id"]},
    )
    put_resp.raise_for_status()


def get_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    result = data["chart"]["result"][0]
    return result["meta"]["regularMarketPrice"]


def send_kakao_message(access_token, text):
    template = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": "https://finance.yahoo.com",
            "mobile_web_url": "https://finance.yahoo.com",
        },
    }
    resp = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
    )
    resp.raise_for_status()
    return resp.json()


def main():
    with open(ALERTS_FILE, "r", encoding="utf-8") as f:
        alerts = json.load(f)

    access_token, new_refresh_token = refresh_kakao_token()

    if new_refresh_token and new_refresh_token != KAKAO_REFRESH_TOKEN:
        update_github_secret("KAKAO_REFRESH_TOKEN", new_refresh_token)
        print("refresh_token rotated and saved to GitHub Secrets")

    triggered = []
    changed = False

    for alert in alerts:
        if alert.get("notified"):
            continue
        try:
            price = get_price(alert["symbol"])
        except Exception as e:
            print(f"price fetch failed for {alert['symbol']}: {e}")
            continue

        target = alert["target"]
        direction = alert.get("direction", "below")
        hit = (price <= target) if direction == "below" else (price >= target)

        if hit:
            cond = "이하" if direction == "below" else "이상"
            triggered.append(f"[{alert['name']}] 목표가 도달! 현재가 {price} (목표 {target} {cond})")
            alert["notified"] = True
            changed = True

    if triggered:
        text = "\U0001F4C8 주식 목표가 알림\n\n" + "\n".join(triggered)
        send_kakao_message(access_token, text)
        print("kakao message sent")
    else:
        print("no alerts triggered this run")

    if changed:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
