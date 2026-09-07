"""공용 헬퍼 — 시간/설정/텍스트정리/URL정규화/언론사판별/HTTP."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests
import yaml

KST = timezone(timedelta(hours=9))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_str(dt: "datetime | None" = None) -> str:
    return (dt or now_kst()).strftime("%Y-%m-%d")


def load_config(path: str = "keywords.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^0-9a-z가-힣]+")
# 구글뉴스가 제목 끝에 붙이는 " - 언론사" 꼬리
_PRESS_SUFFIX_RE = re.compile(r"\s*[-|—·]\s*[^-|—·]{1,25}$")


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    return _WS_RE.sub(" ", s).strip()


def split_google_title(title: str):
    """'제목 - 언론사' -> (제목, 언론사). 못 나누면 (원본, '')."""
    t = strip_html(title)
    if " - " in t:
        head, tail = t.rsplit(" - ", 1)
        if 0 < len(tail) <= 25 and len(head) >= 4:
            return head.strip(), tail.strip()
    return t, ""


def normalize_title(t: str) -> str:
    """중복판정용 제목 정규화: 소문자화 + 언론사꼬리 제거 + 기호제거."""
    t = strip_html(t).lower()
    t2 = _PRESS_SUFFIX_RE.sub("", t)
    if len(t2) >= 6:
        t = t2
    return _NONWORD_RE.sub("", t)


def normalize_url(u: str) -> str:
    if not u:
        return ""
    try:
        p = urlsplit(u.strip())
        host = (p.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path.rstrip("/")
        return urlunsplit(((p.scheme or "https"), host, path, "", ""))
    except Exception:
        return u.strip()


def domain_of(u: str) -> str:
    try:
        host = (urlparse(u).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


PRESS_BY_DOMAIN = {
    "yna.co.kr": "연합뉴스", "yonhapnewstv.co.kr": "연합뉴스TV",
    "newsis.com": "뉴시스", "news1.kr": "뉴스1", "newspim.com": "뉴스핌",
    "chosun.com": "조선일보", "biz.chosun.com": "조선비즈",
    "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문",
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제",
    "sedaily.com": "서울경제", "asiae.co.kr": "아시아경제",
    "edaily.co.kr": "이데일리", "fnnews.com": "파이낸셜뉴스",
    "mt.co.kr": "머니투데이", "moneys.co.kr": "머니S",
    "etnews.com": "전자신문", "zdnet.co.kr": "지디넷코리아",
    "inews24.com": "아이뉴스24", "dt.co.kr": "디지털타임스",
    "kmib.co.kr": "국민일보", "seoul.co.kr": "서울신문",
    "munhwa.com": "문화일보", "segye.com": "세계일보",
    "hankookilbo.com": "한국일보", "kukinews.com": "쿠키뉴스",
    "ohmynews.com": "오마이뉴스", "pressian.com": "프레시안",
    "nocutnews.co.kr": "노컷뉴스", "ytn.co.kr": "YTN",
    "imbc.com": "MBC", "kbs.co.kr": "KBS", "news.sbs.co.kr": "SBS",
    "sbs.co.kr": "SBS", "jtbc.co.kr": "JTBC", "tvchosun.com": "TV조선",
    "heraldcorp.com": "헤럴드경제", "ajunews.com": "아주경제",
    "wowtv.co.kr": "한국경제TV", "thebell.co.kr": "더벨",
    "kyeonggi.com": "경기일보", "kihoilbo.co.kr": "기호일보",
    "joongboo.com": "중부일보", "kgnews.co.kr": "경기신문",
    "incheonilbo.com": "인천일보", "kgdm.co.kr": "경기도민일보",
    "gukjenews.com": "국제뉴스", "newscj.com": "천지일보",
    "consumernews.co.kr": "소비자가만드는신문", "news2day.co.kr": "뉴스투데이",
    "kpinews.kr": "KPI뉴스", "tf.co.kr": "더팩트", "sidae.com": "시대일보",
    "newstnt.com": "뉴스티앤티", "newstomato.com": "뉴스토마토",
    "epnc.co.kr": "테크월드", "ccdailynews.com": "충청일보", "ccdn.co.kr": "충청일보",
    "wooriilbo.com": "우리일보", "news.nate.com": "네이트", "nate.com": "네이트",
    "sisajournal.com": "시사저널", "kyeongin.com": "경인일보",
    "ekgib.com": "경기일보",
    "thisisgame.com": "디스이즈게임", "inven.co.kr": "인벤",
    "gamemeca.com": "게임메카", "ruliweb.com": "루리웹",
    "aitimes.com": "AI타임스", "bloter.net": "블로터",
    "veritas-a.com": "베리타스알파", "goodkyung.com": "굿모닝경기",
}


def press_name(u: str, fallback: str = "") -> str:
    d = domain_of(u)
    if not d:
        return fallback
    if d in PRESS_BY_DOMAIN:
        return PRESS_BY_DOMAIN[d]
    for dom, name in PRESS_BY_DOMAIN.items():
        if d == dom or d.endswith("." + dom):
            return name
    return fallback or d


_SPACE_RE = re.compile(r"[\s·ㆍ,'\"“”‘’()\[\]]+")
_AGG_HOSTS = ("news.google.com", "news.naver.com", "n.news.naver.com")


def press_key(name: str, url: str = "") -> str:
    """매체 동일성 판정 키.

    같은 매체가 경로마다 다른 이름으로 들어온다(네이버=원문 도메인 → 'consumernews.co.kr',
    구글=표시명 → '소비자가 만드는 신문'). 도메인 매핑을 먼저 태우고 공백/기호를 지워
    한 매체가 두 번 세어지지 않게 한다.
    """
    d = domain_of(url)
    if d and not any(d == h or d.endswith("." + h) for h in _AGG_HOSTS):
        name = press_name(url, fallback=name)
    return _SPACE_RE.sub("", (name or "")).lower()


def parse_dt(s: str):
    """RFC822(네이버 pubDate·RSS pubDate) -> KST aware datetime 또는 None."""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST)
    except Exception:
        return None


def http_get(url: str, params: dict = None, headers: dict = None, timeout: int = 15):
    h = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}
    if headers:
        h.update(headers)
    try:
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  [http_get] 실패 {url} :: {e}")
        return None


def humanize_ago(dt, ref=None) -> str:
    if not dt:
        return ""
    ref = ref or now_kst()
    sec = (ref - dt).total_seconds()
    if sec < 0:
        return "방금"
    if sec < 3600:
        return f"{int(sec // 60)}분 전"
    if sec < 86400:
        return f"{int(sec // 3600)}시간 전"
    return f"{int(sec // 86400)}일 전"
