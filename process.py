"""가공: 관련도 필터 → 동일사건 통합(중복제거) → 그룹/정렬 → 요약 카운트.

모두 규칙기반(무료). 결과는 docs/data/YYYY-MM-DD.json 에 저장.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher

from util import load_config, now_kst, press_name, today_str


def build_group_map(cfg: dict) -> dict:
    return {g["id"]: g for g in cfg.get("groups", [])}


def is_relevant(art: dict, group: dict, global_exclude: list,
                lead_window: int = 14) -> bool:
    title = art.get("title", "")
    snip = art.get("snippet", "")
    text = f"{title} {snip}"
    for w in global_exclude:
        if w and w in text:
            return False
    for w in (group.get("exclude") or []):
        if w and w in text:
            return False
    # 내용 게이트(있으면): 제목/요약 어디든 하나
    req = group.get("require_any") or []
    if req and not any(w in text for w in req):
        return False
    # 주제(subject) 게이트: 아래 중 정의된 게 있으면 최소 하나는 충족해야
    #   title_any    : 제목에 하나라도(엔티티 헤드라인)
    #   lead_any     : 기사 도입부(요약 앞 N자)에 하나라도 → 사업명 제목이어도 주체가 그 기관
    #   title_all_of : 제목에 각 하위목록에서 하나씩 모두(예: 경기지역 AND 콘텐츠)
    tany = group.get("title_any") or []
    lany = group.get("lead_any") or []
    tall = group.get("title_all_of") or []
    if tany or lany or tall:
        ok = (any(w in title for w in tany)
              or any(w in snip[:lead_window] for w in lany)
              or (bool(tall) and all(any(w in title for w in sub) for sub in tall)))
        if not ok:
            return False
    return True


# 통합용 토큰: 흔한 단어(고유성 없는)는 제외 — 병합 오작동 방지
_TOK_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
STOP_TOKENS = set(
    "추미애 경기 경기도 지사 도지사 경기지사 경기도지사 기자 종합 인터뷰 민선 "
    "위원장 선출 의원 시장 국힘 민주당 오늘 관련".split())


def title_tokens(title: str) -> set:
    t = _BRACKET_RE.sub("", title or "")
    return {w for w in _TOK_RE.findall(t) if w not in STOP_TOKENS}


def _tok_match(a: str, b: str) -> bool:
    # 조사 차이 흡수(장관/장관에): 접두 일치 허용
    return a == b or (min(len(a), len(b)) >= 2 and (a.startswith(b) or b.startswith(a)))


def same_story(a: dict, b: dict, threshold: float, df: dict) -> bool:
    if a["norm_url"] and a["norm_url"] == b["norm_url"]:
        return True
    ta, tb = a["norm_title"], b["norm_title"]
    if not ta or not tb:
        return False
    if len(ta) >= 10 and len(tb) >= 10 and (ta in tb or tb in ta):
        return True
    if SequenceMatcher(None, ta, tb).ratio() >= threshold:
        return True
    # 단어 겹침 기반(조사 무시 접두 매칭)
    pairs = [(x, y) for x in a["_toks"] for y in b["_toks"] if _tok_match(x, y)]
    shared = len(set(x for x, _ in pairs))
    if shared >= 3:                    # 겹치는 핵심어 3개↑ → 같은 사건(캠페인명 등 다수보도)
        return True
    if shared >= 2 and any(min(df.get(x, 1), df.get(y, 1)) <= 3 for x, y in pairs):
        return True                    # 겹침 2개 + 그중 드문 단어(≤3건) → 같은 사건(소수보도)
    return False


def process(articles: list, meta: dict, cfg: dict) -> dict:
    settings = cfg.get("settings", {})
    gmap = build_group_map(cfg)
    gexcl = cfg.get("global_exclude") or []
    thr = settings.get("min_title_similarity", 0.6)
    maxg = settings.get("max_items_per_group", 40)

    # 선거 표현 필터(경기도지사 그룹 한정): 평상시 옛 선거기사 재발행 차단.
    # ★선거철엔 keywords.yaml에서 filter_old_election_terms=false 로!★
    if settings.get("filter_old_election_terms", True) and "governor" in gmap:
        g = gmap["governor"]
        g["exclude"] = list(g.get("exclude") or []) + list(settings.get("old_election_terms") or [])

    lead_win = settings.get("lead_window", 14)
    collected = len(articles)
    kept = [a for a in articles
            if a["group"] in gmap and is_relevant(a, gmap[a["group"]], gexcl, lead_win)]
    kept.sort(key=lambda a: a["ts"], reverse=True)

    # 토큰·DF 준비(드문단어 기반 통합)
    for a in kept:
        a["_toks"] = title_tokens(a["title"])
    df = Counter()
    for a in kept:
        for w in a["_toks"]:
            df[w] += 1

    # 동일사건 통합(클러스터 내 모든 멤버와 비교 → 표현 다른 같은 사건도 연결)
    clusters = []
    for a in kept:
        for c in clusters:
            if any(same_story(a, m, thr, df) for m in c["members"]):
                c["members"].append(a)
                break
        else:
            clusters.append({"rep": a, "members": [a]})

    # 2차 병합: 대량 재발행 기사가 그리디 순서로 쪼개진 '같은 사건' 덩어리를 재병합
    def _cl_same(ci, cj):
        for m1 in ci["members"][:4]:
            for m2 in cj["members"][:4]:
                if same_story(m1, m2, thr, df):
                    return True
        return False

    i = 0
    while i < len(clusters):
        j = i + 1
        while j < len(clusters):
            if _cl_same(clusters[i], clusters[j]):
                clusters[i]["members"].extend(clusters[j]["members"])
                clusters.pop(j)
            else:
                j += 1
        i += 1

    out_clusters = []
    for c in clusters:
        members = c["members"]
        # 특정 기관 분류(비-catchall)가 광범위 분류(catchall: 경기도·중앙부처)보다 우선
        # 배정: spec(정밀도 등급, 낮을수록 특정기관) 우선, 그다음 표시 priority
        prim = min(members, key=lambda m: (
            gmap.get(m["group"], {}).get("spec", 99), m["group_priority"]))
        prim_members = [m for m in members if m["group"] == prim["group"]]
        seen, sources = set(), []
        for m in sorted(members, key=lambda m: (m["origin"] != "naver", -m["ts"])):
            nm = m["source"] or press_name(m["url"])
            if nm in seen:
                continue
            seen.add(nm)
            sources.append({"name": nm, "url": m["url"], "origin": m["origin"]})
        # 대표 기사는 배정 분류의 멤버 중에서(표시 제목이 섹션과 일치하도록)
        rep = max(prim_members, key=lambda m: (bool(m["snippet"]), m["ts"]))
        out_clusters.append({
            "title": rep["title"], "url": rep["url"], "snippet": rep["snippet"],
            "source": sources[0]["name"] if sources else rep["source"],
            "sources": sources, "source_count": len(sources),
            "published": rep["published"], "ts": rep["ts"],
            "group": prim["group"], "group_label": prim["group_label"],
        })

    groups_out = []
    for g in sorted(cfg.get("groups", []), key=lambda x: x.get("priority", 99)):
        items = [c for c in out_clusters if c["group"] == g["id"]]
        items.sort(key=lambda c: (c["source_count"], c["ts"]), reverse=True)
        if items:
            groups_out.append({"id": g["id"], "label": g["label"],
                               "priority": g.get("priority", 99),
                               "page": g.get("page", "main"),
                               "preview": g.get("preview_items"),
                               "count": len(items), "items": items[:maxg]})

    multi = sum(1 for c in out_clusters if c["source_count"] > 1)
    result = {
        "date": today_str(),
        "generated_at": now_kst().isoformat(),
        "window_hours": meta.get("window_hours", settings.get("hours_window", 30)),
        "sources": meta.get("sources", []),
        "use_naver": meta.get("use_naver", False),
        "preview_items": settings.get("preview_items", 5),
        "counts": {"collected": collected, "kept": len(kept),
                   "excluded": collected - len(kept),
                   "consolidated": len(out_clusters), "multi": multi},
        "groups": groups_out,
    }
    print(f"[process] 수집 {collected} → 관련 {len(kept)} → 통합 {len(out_clusters)}개 "
          f"(제외 {collected - len(kept)}, 복수보도 {multi})")
    return result


def _latest_raw() -> str:
    files = sorted(glob.glob(os.path.join(".cache", "raw-*.json")))
    return files[-1] if files else ""


def main():
    cfg = load_config()
    path = _latest_raw()
    if not path:
        print("[process] .cache/raw-*.json 없음 — 먼저 collect.py 실행")
        return
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    result = process(blob.get("articles", []), blob.get("meta", {}), cfg)
    os.makedirs(os.path.join("docs", "data"), exist_ok=True)
    out = os.path.join("docs", "data", f"{result['date']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[process] 저장 → {out}")


if __name__ == "__main__":
    main()
