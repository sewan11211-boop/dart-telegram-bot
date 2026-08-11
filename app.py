import os
import time
import requests
from datetime import datetime
from flask import Flask

app = Flask(__name__)

DART_API_KEY = os.environ.get("DART_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

seen = set()


def get_disclosures():
    today = datetime.now().strftime("%Y%m%d")
    all_items = []
    page = 1

    while True:
        params = {
            "crtfc_key": DART_API_KEY,
            "bgn_de": today,
            "end_de": today,
            "page_no": page,
            "page_count": 100,
        }

        response = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params=params,
            timeout=15,
        )

        data = response.json()

        if data.get("status") == "013":
            return []

        if data.get("status") != "000":
            print("DART 오류:", data)
            return []

        items = data.get("list", [])
        all_items.extend(items)

        total_page = int(data.get("total_page", 1))

        if page >= total_page:
            break

        page += 1

    return all_items


def send_telegram(item):
    rcept_no = item["rcept_no"]
    corp_name = item.get("corp_name", "")
    report_nm = item.get("report_nm", "")
    rcept_dt = item.get("rcept_dt", "")

    link = (
        "https://dart.fss.or.kr/dsaf001/main.do"
        f"?rcpNo={rcept_no}"
    )

    message = (
        "📢 DART 신규공시\n\n"
        f"🏢 {corp_name}\n"
        f"📄 {report_nm}\n"
        f"📅 {rcept_dt}\n\n"
        f"🔗 {link}"
    )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )

    response.raise_for_status()


def check_dart():
    global seen

    items = get_disclosures()

    # 처음 시작할 때 기존 공시는 전송하지 않음
    if not seen:
        seen = {item["rcept_no"] for item in items}
        print(f"초기화 완료: {len(seen)}건")
        return

    # 오래된 공시부터 전송
    for item in reversed(items):
        rcept_no = item["rcept_no"]

        if rcept_no not in seen:
            send_telegram(item)
            seen.add(rcept_no)

            print(
                "신규공시 전송:",
                item.get("corp_name"),
                item.get("report_nm"),
            )

            time.sleep(0.5)


@app.route("/")
def home():
    check_dart()
    return "DART Telegram Bot OK"


@app.route("/check")
def check():
    check_dart()
    return "Checked"
