"""가공: 관련도 필터 → 동일사건 통합(중복제거) → 그룹/정렬 → 요약 카운트.

모두 규칙기반(무료). 결과는 docs/data/YYYY-MM-DD.json 에 저장.
"""
from __future__ import annotations

import glob
import json
import os
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


def same_story(a: dict, b: dict, threshold: float) -> bool:
    if a["norm_url"] and a["norm_url"] == b["norm_url"]:
        return True
    ta, tb = a["norm_title"], b["norm_title"]
    if not ta or not tb:
        return False
    if len(ta) >= 10 and len(tb) >= 10 and (ta in tb or tb in ta):
        return True
    return SequenceMatcher(None, ta, tb).ratio() >= threshold


def process(articles: list, meta: dict, cfg: dict) -> dict:
    settings = cfg.get("settings", {})
    gmap = build_group_map(cfg)
    gexcl = cfg.get("global_exclude") or []
    thr = settings.get("min_title_similarity", 0.6)
    maxg = settings.get("max_items_per_group", 40)

    collected = len(articles)
    kept = [a for a in articles
            if a["group"] in gmap and is_relevant(a, gmap[a["group"]], gexcl)]
    kept.sort(key=lambda a: a["ts"], reverse=True)

    # 동일사건 통합
    clusters = []
    for a in kept:
        for c in clusters:
            if same_story(a, c["rep"], thr):
                c["members"].append(a)
                break
        else:
            clusters.append({"rep": a, "members": [a]})

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
