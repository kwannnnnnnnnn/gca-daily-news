"""파이프라인 엔트리: 수집 → 가공 → 발행 → 오래된 아카이브 정리 (CI/로컬 공용).

    python main.py

산출물: docs/index.html, docs/archive/<날짜>.html, docs/data/<날짜>.json
retention_days(설정) 지난 아카이브는 자동 삭제.
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import timedelta

import collect
import process
import render
from util import (load_config, normalize_title, normalize_url, now_kst,
                  today_str)

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def previous_articles(cfg: dict, cutoff_ts: float) -> list:
    """이전 발행분(docs/data/*.json)에서 아직 시간창 안에 있는 기사를 되살린다.

    네이버·구글은 매번 '최신 N건'만 돌려주므로, 새로 수집만 하면 몇 시간 전 기사가
    소스 응답에서 밀려나 화면에서 사라진다. 이전 발행분을 합쳐 누적(스택)을 유지한다.
    클러스터는 매체별 기사로 되펼쳐, 재통합 시 매체 수가 보존되게 한다.
    """
    gmap = {g["id"]: g for g in cfg.get("groups", [])}
    future_limit = (now_kst() + timedelta(hours=2)).timestamp()
    out = []
    for p in sorted(glob.glob(os.path.join("docs", "data", "*.json")))[-3:]:
        if not _DATE_RE.match(os.path.basename(p)):   # search-index 등 제외
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        for g in d.get("groups", []):
            gid = g.get("id")
            if gid not in gmap:
                continue
            for it in g.get("items", []):
                ts = it.get("ts") or 0
                # 시간창 밖이면 자연 소멸. 잘못된 미래 시각은 영구 잔류를 막기 위해 제외
                if ts < cutoff_ts or ts > future_limit:
                    continue
                srcs = it.get("sources") or [{"name": it.get("source", ""),
                                              "url": it.get("url", "")}]
                for s in srcs:
                    url = s.get("url") or it.get("url", "")
                    if not url:
                        continue
                    out.append({
                        "title": it.get("title", ""), "url": url,
                        "norm_url": normalize_url(url),
                        "norm_title": normalize_title(it.get("title", "")),
                        "snippet": it.get("snippet", ""),
                        "source": s.get("name", ""),
                        "published": it.get("published", ""), "ts": ts,
                        "origin": s.get("origin", "prev"), "group": gid,
                        "group_label": g.get("label", ""),
                        "group_priority": gmap[gid].get("priority", 99),
                        "query": "",
                    })
    return out


def merge_articles(fresh: list, prev: list) -> list:
    """URL 기준 합치기(새 수집분 우선 — 요약·매체명이 더 정확)."""
    seen, out = set(), []
    for a in list(fresh) + list(prev):
        k = a.get("norm_url") or a.get("url")
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(a)
    return out


def prune_old(days) -> int:
    """retention_days 지난 archive/*.html·data/*.json 삭제(파일명 날짜 기준). 0/None=무제한."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    cutoff = (now_kst() - timedelta(days=days)).strftime("%Y-%m-%d")
    removed = 0
    targets = (glob.glob(os.path.join("docs", "data", "*.json"))
               + glob.glob(os.path.join("docs", "archive", "*.html")))
    for p in targets:
        m = _DATE_RE.match(os.path.basename(p))   # archive/index.html 등은 매칭 안 됨
        if m and m.group(1) < cutoff:
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"[prune] {cutoff} 이전 아카이브 {removed}개 삭제")
    return removed


def main():
    cfg = load_config()

    articles, meta = collect.collect(cfg)

    # ── 누적(스택): 이전 발행분 중 시간창 안의 기사를 되살려 합친다 ──
    hours = cfg.get("settings", {}).get("hours_window", 30)
    cutoff_ts = (now_kst() - timedelta(hours=hours)).timestamp()
    prev = previous_articles(cfg, cutoff_ts)
    before = len(articles)
    articles = merge_articles(articles, prev)
    print(f"[stack] 신규 {before} + 이전창 {len(prev)} → 합계 {len(articles)}건 "
          f"(최근 {hours}시간 누적)")

    # 원자료 캐시(비공개, .gitignore) — 재현/디버깅용
    os.makedirs(".cache", exist_ok=True)
    with open(os.path.join(".cache", f"raw-{today_str()}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"meta": meta, "articles": articles}, f,
                  ensure_ascii=False, indent=2)

    result = process.process(articles, meta, cfg)

    # 처리결과 JSON(공개 docs/data) — 아카이브 목록·재렌더의 원천
    os.makedirs(os.path.join("docs", "data"), exist_ok=True)
    with open(os.path.join("docs", "data", f"{result['date']}.json"), "w",
              encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    render.write_outputs(result)
    prune_old(cfg.get("settings", {}).get("retention_days", 0))
    render.build_archive_index()   # 정리 후 남은 것으로 목록 재생성
    render.build_search_index(cfg.get("settings", {}).get("search_index_days", 180))  # 지난 기록 검색 인덱스도 갱신
    print("[main] 완료")


if __name__ == "__main__":
    main()
