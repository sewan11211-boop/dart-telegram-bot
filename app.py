1 import os
2 import time
3 import re
4 import html
5 import io
6 import zipfile
7 import requests

from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from bs4 import BeautifulSoup


app = Flask(__name__)

DART_API_KEY = os.environ.get("DART_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

seen = set()

KST = ZoneInfo("Asia/Seoul")


# =========================
# 공시 종류를 쉽게 표시
# =========================
def classify_report(report_name):
    name = report_name.replace(" ", "")

    if "단일판매" in name or "공급계약" in name:
        return "🤝 공급계약"

    if "무상증자" in name:
        return "🎁 무상증자"

    if "유상증자" in name:
        return "⚠️ 유상증자"

    if "전환사채" in name:
        return "⚠️ 전환사채(CB)"

    if "신주인수권부사채" in name:
        return "⚠️ 신주인수권부사채(BW)"

    if "최대주주변경" in name:
        return "👤 최대주주 변경"

    if "자기주식" in name:
        return "💰 자사주"

    if "현금ㆍ현물배당" in name or "배당" in name:
        return "💰 배당"

    if "영업실적" in name or "매출액또는손익구조" in name:
        return "📈 실적"

    if "합병" in name:
        return "🔄 합병"

    if "분할" in name:
        return "🔄 회사분할"

    if "주식등의대량보유" in name:
        return "👤 대량보유 보고"

    return "📄 일반공시"
def judge_impact(report_type, report_name):
    name = report_name.replace(" ", "")

    # 긍정 가능성이 높은 유형
    if "공급계약" in report_type:
        return "🟢 긍정 가능성"

    if "무상증자" in report_type:
        return "🟢 긍정 가능성"

    if "자사주" in report_type:
        if "처분" in name:
            return "🔴 부정 가능성"
        return "🟢 긍정 가능성"

    if "배당" in report_type:
        return "🟢 긍정 가능성"

    # 희석/자금조달 가능성
    if "유상증자" in report_type:
        return "🔴 부정 가능성"

    if "전환사채" in report_type:
        return "🔴 부정 가능성"

    if "신주인수권부사채" in report_type:
        return "🔴 부정 가능성"

    # 내용에 따라 달라지는 공시
    if "실적" in report_type:
        return "⚪ 실적 확인 필요"

    if "최대주주" in report_type:
        return "⚪ 내용 확인 필요"

    if "합병" in report_type or "회사분할" in report_type:
        return "⚪ 내용 확인 필요"

    if "대량보유" in report_type:
        return "⚪ 지분변동 확인"

    return "⚪ 중립"
# =========================
# DART 오늘 공시 전체 조회
# =========================

def get_disclosures():

    today = datetime.now(KST).strftime("%Y%m%d")

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
            timeout=20,
        )

        response.raise_for_status()

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


# =========================
# 공시 원문 가져오기
# =========================

def get_document_text(rcept_no):

    try:

        url = "https://opendart.fss.or.kr/api/document.xml"

        params = {
            "crtfc_key": DART_API_KEY,
            "rcept_no": rcept_no,
        }

        response = requests.get(
            url,
            params=params,
            timeout=25,
        )

        response.raise_for_status()

        # DART 원문은 ZIP 형태
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:

            texts = []

            for filename in z.namelist():

                if filename.lower().endswith(
                    (".xml", ".html", ".htm")
                ):

                    raw = z.read(filename)

                    decoded = None

                    for encoding in [
                        "utf-8",
                        "euc-kr",
                        "cp949",
                    ]:

                        try:
                            decoded = raw.decode(encoding)
                            break
                        except:
                            continue

                    if decoded:

                        soup = BeautifulSoup(
                            decoded,
                            "html.parser"
                        )

                        text = soup.get_text(
                            " ",
                            strip=True
                        )

                        texts.append(text)

            return " ".join(texts)

    except Exception as e:

        print(
            "공시본문 읽기 실패:",
            rcept_no,
            e
        )

        return ""


# =========================
# 긴 문장 정리
# =========================

def clean_text(text):

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================
# 공시에서 핵심 문구 찾기
# =========================

def find_keyword_sentence(text, keywords):

    if not text:
        return None

    text = clean_text(text)

    for keyword in keywords:

        position = text.find(keyword)

        if position != -1:

            start = max(
                0,
                position - 30
            )

            end = min(
                len(text),
                position + 140
            )

            result = text[start:end]

            return result.strip()

    return None


# =========================
# 공시별 핵심내용
# =========================

def make_summary(report_type, document_text):
    if not document_text:
        return "공시 세부내용은 DART 원문에서 확인할 수 있습니다."

    # 공시 종류별 핵심 항목
    keyword_map = {
        "공급계약": [
            "계약금액",
            "최근매출액",
            "매출액대비",
            "계약상대",
            "계약기간",
        ],

        "무상증자": [
            "신주배정",
            "신주의 수",
            "1주당",
            "배정기준일",
        ],

        "유상증자": [
            "신주의 수",
            "자금조달",
            "발행가액",
            "증자방식",
        ],

        "전환사채(CB)": [
            "사채의 권면",
            "전환가액",
            "전환청구",
            "발행대상",
        ],

        "신주인수권부사채(BW)": [
            "사채의 권면",
            "행사가액",
            "행사기간",
            "발행대상",
        ],

        "최대주주 변경": [
            "변경후 최대주주",
            "소유비율",
            "변경사유",
            "변경일자",
        ],

        "자사주": [
            "취득예정주식",
            "취득예정금액",
            "취득목적",
            "취득기간",
        ],

        "배당": [
            "주당배당금",
            "배당금총액",
            "시가배당율",
            "배당기준일",
        ],

        "실적": [
            "매출액",
            "영업이익",
            "당기순이익",
            "전년동기",
        ],

        "합병": [
            "합병비율",
            "합병목적",
            "합병기일",
            "합병상대회사",
        ],

        "회사분할": [
            "분할방법",
            "분할목적",
            "분할기일",
            "신설회사",
        ],

        "대량보유 보고": [
            "보유주식등의 수",
            "보유비율",
            "변동주식수",
            "변동사유",
        ],
    }

    keywords = keyword_map.get(report_type, [])

    # 중요 투자공시가 아닌 경우
    if not keywords:
        return (
            "투자 핵심 공시로 분류되지 않은 일반 공시입니다.\n"
            "세부내용은 DART 원문에서 확인할 수 있습니다."
        )

    # 공시 원문을 줄 단위로 정리
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in document_text.splitlines()
        if line.strip()
    ]

    found = []
    used = set()

    for keyword in keywords:
        for line in lines:
            clean_line = line.replace(" ", "")

            if keyword.replace(" ", "") in clean_line:
                # 너무 긴 HTML/본문 문장 제외
                if len(line) > 180:
                    continue

                if line not in used:
                    found.append(line)
                    used.add(line)

                break

        # 텔레그램이 너무 길어지는 것 방지
        if len(found) >= 4:
            break

    if not found:
        return (
            f"{report_type} 관련 공시입니다.\n"
            "핵심 수치는 DART 원문에서 확인해 주세요."
        )

    summary = "\n".join(
        f"• {line}" for line in found
    )

    return summary[:1200]

# =========================
# 텔레그램 전송
# =========================

def send_telegram(item):
    rcept_no = item["rcept_no"]

    corp_name = item.get(
        "corp_name",
        "기업명 확인 필요"
    )

    report_name = item.get(
        "report_nm",
        "공시"
    )

    stock_code = item.get(
        "stock_code",
        ""
    )

    report_type = classify_report(
        report_name
    )

    impact = judge_impact(
        report_type,
        report_name
    )

    document_text = get_document_text(
        rcept_no
    )

    # 이모티콘을 제거한 공시종류로 요약 함수에 전달
    plain_type = (
        report_type
        .replace("🤝 ", "")
        .replace("🎁 ", "")
        .replace("⚠️ ", "")
        .replace("👤 ", "")
        .replace("💰 ", "")
        .replace("📈 ", "")
        .replace("🔄 ", "")
        .replace("📄 ", "")
    )

    summary = make_summary(
        plain_type,
        document_text
    )

    dart_link = (
        "https://dart.fss.or.kr/"
        "dsaf001/main.do"
        f"?rcpNo={rcept_no}"
    )

    if stock_code:
        company_link = (
            "https://finance.naver.com/"
            f"item/main.nhn?code={stock_code}"
        )
    else:
        company_link = ""
corp_name = html.escape(corp_name)
report_name = html.escape(report_name)
summary = html.escape(summary)
impact = html.escape(impact)
    message = (
        f"<b>{report_type}</b>\n\n"
        f"<b>{corp_name}</b>\n"
        f"{report_name}\n\n"
        f"<b>핵심내용</b>\n"
        f"{summary}\n\n"
        f"<b>판단 : {impact}</b>\n\n"
        f"📌 공시 내용을 간단히 정리한 참고 정보입니다.\n\n"
        f"<b>공시링크</b>\n"
        f"{dart_link}\n"
    )

    if company_link:
        message += (
            f"\n<b>회사정보</b>\n"
            f"{company_link}"
        )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    response.raise_for_status()

# =========================
# 신규 공시 확인
# =========================

def check_dart():

    global seen

    items = get_disclosures()

    if not seen:

        seen = {
            item["rcept_no"]
            for item in items
        }

        print(
            f"초기화 완료: {len(seen)}건"
        )

        return

    for item in reversed(items):

        rcept_no = item["rcept_no"]

        if rcept_no in seen:
            continue

        try:

            send_telegram(item)

            seen.add(rcept_no)

            print(
                "전송완료:",
                item.get("corp_name"),
                item.get("report_nm"),
            )

            time.sleep(0.5)

        except Exception as e:

            print(
                "전송 실패:",
                rcept_no,
                e
            )


# =========================
# Render
# =========================

@app.route("/")
def home():

    return "DART Telegram Bot OK"


@app.route("/check")
def check():

    check_dart()

    return "Checked"
