"""수집: 네이버 뉴스검색 API(키 있을 때) + 구글뉴스 RSS(키 불필요).

- NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 있으면 네이버를 함께 사용.
- 없으면 구글 RSS만으로 동작(graceful fallback).
- 결과는 .cache/raw-YYYY-MM-DD.json 에 저장.
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import timedelta
from urllib.parse import quote

from util import (http_get, load_config, normalize_title, normalize_url,
                  now_kst, parse_dt, press_name, split_google_title,
                  strip_html, today_str)

# 구(舊) 개발자센터 검색 API는 2026-07-31 종료(404 SE05). 후속은 네이버 클라우드 플랫폼의
# NAVER API HUB — 경로에 확장자가 없고(`/search/v1/news`) 인증 헤더가 다르다.
NAVER_URL_LEGACY = "https://openapi.naver.com/v1/search/news.json"
NAVER_URL_HUB = "https://naverapihub.apigw.ntruss.com/search/v1/news"
GOOGLE_URL = "https://news.google.com/rss/search"


def fetch_naver(query: str, cid: str, csec: str, settings: dict) -> list:
    """NCP_API_KEY_ID/NCP_API_KEY가 있으면 API HUB, 없으면 구 방식."""
    ncp_id = os.environ.get("NCP_API_KEY_ID", "").strip()
    ncp_key = os.environ.get("NCP_API_KEY", "").strip()
    if ncp_id and ncp_key:
        url = NAVER_URL_HUB
        headers = {"X-NCP-APIGW-API-KEY-ID": ncp_id, "X-NCP-APIGW-API-KEY": ncp_key}
    else:
        url = NAVER_URL_LEGACY
        headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}
    params = {"query": query, "display": settings.get("naver_display", 100),
              "start": 1, "sort": "date", "format": "json"}
    r = http_get(url, params=params, headers=headers)
    if not r:
        return []
    try:
        items = r.json().get("items", [])
    except Exception as e:
        print(f"  [naver] JSON 파싱실패 {query}: {e}")
        return []
    out = []
    for it in items:
        title = strip_html(it.get("title", ""))
        link = (it.get("originallink") or it.get("link") or "").strip()
        if not title or not link:
            continue
        out.append({
            "title": title, "url": link,
            "snippet": strip_html(it.get("description", "")),
            "dt": parse_dt(it.get("pubDate")),
            "source": press_name(link), "origin": "naver",
        })
    return out


def fetch_google(query: str, settings: dict) -> list:
    q = quote(f"{query} when:1d")
    url = f"{GOOGLE_URL}?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    r = http_get(url)
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  [google] XML 파싱실패 {query}: {e}")
        return []
    out = []
    for item in root.iter("item"):
        raw_title = item.findtext("title") or ""
        title, src_from_title = split_google_title(raw_title)
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        src_el = item.find("source")
        source = ((src_el.text or "").strip() if src_el is not None else "")
        source = source or src_from_title or press_name(link)
        out.append({
            "title": title, "url": link, "snippet": "",
            "dt": parse_dt(item.findtext("pubDate")),
            "source": source, "origin": "google",
        })
    return out


def collect(cfg: dict):
    settings = cfg.get("settings", {})
    hours = settings.get("hours_window", 30)
    cutoff = now_kst() - timedelta(hours=hours)
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    csec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    ncp_id = os.environ.get("NCP_API_KEY_ID", "").strip()
    ncp_key = os.environ.get("NCP_API_KEY", "").strip()
    # API HUB 키(신) 또는 개발자센터 키(구) 중 하나만 있어도 네이버 사용
    use_naver = bool((ncp_id and ncp_key) or (cid and csec))

    naver_label = "네이버뉴스(API HUB)" if (ncp_id and ncp_key) else "네이버뉴스"
    sources = ([naver_label] if use_naver else []) + ["구글뉴스"]
    print(f"[collect] 소스={'+'.join(sources)} · 최근 {hours}시간 · "
          f"기준시각 {cutoff:%m-%d %H:%M} KST")

    results = []
    for g in cfg.get("groups", []):
        got = 0
        for q in g.get("queries", []):
            items = []
            if use_naver:
                items += fetch_naver(q, cid, csec, settings)
            items += fetch_google(q, settings)
            for it in items:
                if it["dt"] and it["dt"] < cutoff:
                    continue
                results.append({
                    "title": it["title"], "url": it["url"],
                    "norm_url": normalize_url(it["url"]),
                    "norm_title": normalize_title(it["title"]),
                    "snippet": it["snippet"], "source": it["source"],
                    "published": it["dt"].isoformat() if it["dt"] else "",
                    "ts": it["dt"].timestamp() if it["dt"] else 0.0,
                    "origin": it["origin"], "group": g["id"],
                    "group_label": g["label"],
                    "group_priority": g.get("priority", 99), "query": q,
                })
                got += 1
        print(f"  · {g['label']:<16} {got:>4}건")

    meta = {"use_naver": use_naver, "sources": sources,
            "window_hours": hours, "collected_at": now_kst().isoformat()}
    print(f"[collect] 원천 수집(중복포함) 총 {len(results)}건")
    return results, meta


def main():
    cfg = load_config()
    articles, meta = collect(cfg)
    os.makedirs(".cache", exist_ok=True)
    path = os.path.join(".cache", f"raw-{today_str()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "articles": articles}, f,
                  ensure_ascii=False, indent=2)
    print(f"[collect] 저장 → {path}")


if __name__ == "__main__":
    main()
