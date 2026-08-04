"""
대한영양사협회 입법 모니터링 자동화 스크립트
------------------------------------------------
1. 국회 의안정보(공공데이터포털 BillInfoService2) 와
   법제처 정부입법예고(공공데이터포털) 를 조회해서
2. KEYWORDS 에 포함된 단어가 제목/내용에 있으면
3. matched_items.json 에 누적 저장하고
4. docs/index.html 웹페이지를 새로 생성합니다.

비전공자를 위한 안내:
- 이 파일에서 직접 수정해야 하는 곳은 "## 여기를 수정하세요" 라고 써있는 부분뿐입니다.
- 나머지 코드는 그대로 두셔도 됩니다.
"""

import os
import json
import html
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# =========================================================
# ## 여기를 수정하세요 1) 감시할 키워드 목록
# 제목이나 본문에 아래 단어 중 하나라도 포함되면 "감지된 입법"으로 저장됩니다.
# 필요한 만큼 자유롭게 추가/삭제하세요.
# =========================================================
KEYWORDS = [
    "영양사", "영양", "급식", "학교급식", "국민영양관리법",
    "식생활", "영양교육", "영양표시", "식품위생",
]

# =========================================================
# 인증키: GitHub Actions의 Secrets에서 자동으로 불러옵니다.
# (내 컴퓨터에서 테스트할 때는 터미널에서 아래처럼 먼저 설정)
#   export DATA_GO_KR_KEY="발급받은키"
# =========================================================
DATA_GO_KR_KEY = os.environ.get("DATA_GO_KR_KEY", "")

BASE_DIR = Path(__file__).parent
SEEN_FILE = BASE_DIR / "seen_ids.json"
MATCHED_FILE = BASE_DIR / "matched_items.json"
DOCS_DIR = BASE_DIR / "docs"
KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------
def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def contains_keyword(*texts):
    for text in texts:
        if not text:
            continue
        for kw in KEYWORDS:
            if kw in text:
                return kw
    return None


def now_kst_str():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------
# ① 국회 의안정보 (공공데이터포털 - 국회사무처_의안정보 API)
#    https://www.data.go.kr/data/3037286/openapi.do
# ---------------------------------------------------------
def fetch_assembly_bills():
    """
    주의: data.go.kr은 API마다 정확한 응답 필드명이 조금씩 다릅니다.
    최초 1회는 아래 print(json.dumps(...)) 결과를 직접 눈으로 확인해서
    FIELD 이름이 실제와 다르면 아래 FIELD_TITLE 등을 맞게 고쳐주세요.
    (README '문제 해결' 섹션 참고)
    """
    if not DATA_GO_KR_KEY:
        print("[국회 API] 인증키가 없어 건너뜁니다.")
        return []

    url = "https://apis.data.go.kr/9710000/BillInfoService2/getBillInfoList"
    params = {
        "serviceKey": DATA_GO_KR_KEY,
        "numOfRows": 100,
        "pageNo": 1,
        "type": "json",
    }

    try:
        res = requests.get(url, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"[국회 API 오류] {e}")
        return []

    # 응답 구조가 예상과 다를 경우 아래 줄의 주석을 풀어서 실제 구조를 확인하세요.
    # print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

    try:
        items = data["response"]["body"]["items"]
        items = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(items, dict):
            items = [items]
    except (KeyError, TypeError):
        print("[국회 API] 예상과 다른 응답 구조입니다. 위 print 주석을 풀어 확인해보세요.")
        return []

    results = []
    for item in items:
        # ## 여기를 수정하세요 2): 실제 필드명이 다르면 아래 get() 안의 이름을 교체
        title = item.get("billName") or item.get("billNm") or ""
        summary = item.get("summary", "")
        matched_kw = contains_keyword(title, summary)
        if not matched_kw:
            continue

        bill_id = item.get("billId") or item.get("billNo") or title
        results.append({
            "source": "국회 발의 법률안",
            "id": f"assembly-{bill_id}",
            "title": title,
            "org": item.get("proposer") or item.get("rstProposer") or "국회",
            "date": item.get("proposeDt") or item.get("billProposeDt") or "",
            "matched_keyword": matched_kw,
            "link": item.get("detailLink") or item.get("billDetailUrl")
                    or f"https://likms.assembly.go.kr/bill/billDetail.do?billId={bill_id}",
        })
    return results


# ---------------------------------------------------------
# ② 법제처 정부입법예고 (공공데이터포털)
#    https://www.data.go.kr/data/15058407/openapi.do
# ---------------------------------------------------------
def fetch_gov_notices():
    if not DATA_GO_KR_KEY:
        print("[입법예고 API] 인증키가 없어 건너뜁니다.")
        return []

    # ## 여기를 수정하세요 3): 공공데이터포털에서 '법제처_정부입법예고' 활용신청 후
    # 상세페이지의 '요청 URL(Request URL)'을 그대로 복사해서 아래 url에 붙여넣으세요.
    # (신청 페이지: https://www.data.go.kr/data/15058407/openapi.do)
    url = "https://apis.data.go.kr/1170000/law/lawmakLegPrps"
    params = {
        "serviceKey": DATA_GO_KR_KEY,
        "numOfRows": 100,
        "pageNo": 1,
        "type": "json",
    }

    try:
        res = requests.get(url, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"[입법예고 API 오류] {e}")
        return []

    # print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

    try:
        items = data["response"]["body"]["items"]
        items = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(items, dict):
            items = [items]
    except (KeyError, TypeError):
        print("[입법예고 API] 예상과 다른 응답 구조입니다. 위 print 주석을 풀어 확인해보세요.")
        return []

    results = []
    for item in items:
        title = item.get("lmPpsnTitle") or item.get("title") or ""
        summary = item.get("lmPpsnCn", "")
        matched_kw = contains_keyword(title, summary)
        if not matched_kw:
            continue

        notice_id = item.get("lmPpsnId") or title
        results.append({
            "source": "정부 입법예고",
            "id": f"govnotice-{notice_id}",
            "title": title,
            "org": item.get("chrgDeptNm") or item.get("ministry") or "",
            "date": item.get("lmPpsnBgnde") or item.get("regDt") or "",
            "matched_keyword": matched_kw,
            "link": item.get("lmPpsnLink") or "https://opinion.lawmaking.go.kr/",
        })
    return results


# ---------------------------------------------------------
# HTML 생성
# ---------------------------------------------------------
def build_html(matched_items, new_ids):
    matched_items = sorted(matched_items, key=lambda x: x.get("date", ""), reverse=True)

    rows = []
    for it in matched_items:
        is_new = it["id"] in new_ids
        badge = '<span class="badge">NEW</span>' if is_new else ""
        rows.append(f"""
        <tr class="{'new-row' if is_new else ''}">
          <td>{badge}{html.escape(it['source'])}</td>
          <td><a href="{html.escape(it['link'])}" target="_blank" rel="noopener">{html.escape(it['title'])}</a></td>
          <td>{html.escape(it.get('org') or '')}</td>
          <td>{html.escape(it.get('date') or '')}</td>
          <td>{html.escape(it.get('matched_keyword') or '')}</td>
        </tr>""")

    updated = now_kst_str()
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>대한영양사협회 입법 모니터링</title>
<style>
  body {{ font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
          background:#f6f7f9; margin:0; padding:24px; color:#222; }}
  .wrap {{ max-width: 1000px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .updated {{ color:#666; font-size: 13px; margin-bottom: 20px; }}
  table {{ width:100%; border-collapse: collapse; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid #eee; font-size: 14px; text-align:left; vertical-align:top; }}
  th {{ background:#2f6b4f; color:#fff; position: sticky; top:0; }}
  tr.new-row {{ background:#fff7e6; }}
  .badge {{ background:#e94b3c; color:#fff; font-size:11px; padding:2px 6px; border-radius:4px; margin-right:6px; }}
  a {{ color:#2f6b4f; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .empty {{ padding:40px; text-align:center; color:#888; background:#fff; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>🥗 대한영양사협회 입법 모니터링</h1>
  <div class="updated">마지막 업데이트: {updated} (KST) · 감시 키워드: {', '.join(KEYWORDS)}</div>
  {"<table><thead><tr><th>구분</th><th>제목</th><th>소관</th><th>날짜</th><th>일치 키워드</th></tr></thead><tbody>" + ''.join(rows) + "</tbody></table>" if matched_items else '<div class="empty">아직 감지된 입법이 없습니다.</div>'}
</div>
</body>
</html>"""


# ---------------------------------------------------------
# 메인 실행
# ---------------------------------------------------------
def main():
    seen_ids = set(load_json(SEEN_FILE, []))
    matched_items = load_json(MATCHED_FILE, [])
    existing_ids = {it["id"] for it in matched_items}

    fresh = fetch_assembly_bills() + fetch_gov_notices()

    new_ids = []
    for item in fresh:
        if item["id"] in existing_ids:
            continue
        matched_items.append(item)
        existing_ids.add(item["id"])
        new_ids.append(item["id"])
        seen_ids.add(item["id"])

    save_json(MATCHED_FILE, matched_items)
    save_json(SEEN_FILE, list(seen_ids))

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(build_html(matched_items, new_ids), encoding="utf-8")
    save_json(DOCS_DIR / "data.json", matched_items)

    print(f"완료: 전체 {len(matched_items)}건 / 이번에 새로 발견 {len(new_ids)}건")


if __name__ == "__main__":
    main()
