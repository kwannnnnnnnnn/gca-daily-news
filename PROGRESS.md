# PROGRESS — GCA 일일 언론 모니터링 자동화

- **작업 지시:** 2026-07-16 (목) 앱 세션에서 계획 승인. 사용자가 "이따 20:00부터 수행" 명시 → 오프아워 엔진이 오늘 밤 20:00 창부터 수행.
- **승인 계획서:** `C:\Users\GCA\.claude\plans\polymorphic-jumping-mountain.md` (먼저 전체 Read)
- **대기열:** `C:\Users\GCA\.claude\auto-resume\gca-news-monitoring.md` (priority 0)

## 한 일
- (아직 없음 — 코드 구현 시작 전)
- 계획 확정 / 대기열·체크포인트 등록만 완료.

## 남은 일 (구현순서)
1. [ ] 이 폴더에서 git init + `keywords.yaml` 기본값 작성
2. [ ] `collect.py` — 구글 RSS로 오늘자 수집 동작 확인(키 불필요)
3. [ ] `process.py` / `render.py` — 로컬 HTML 미리보기로 중복제거·관련도 튜닝
4. [ ] `gh repo create` 공개 repo + Pages(docs/) 활성화 + push
5. [ ] `.github/workflows/daily.yml` + `workflow_dispatch` 클라우드 1회 실행 검증
6. [ ] (사용자 네이버 키 등록 후) 네이버 소스 on 재실행 — 키 없으면 README 안내만
7. [ ] cron 확정 → 익일 자동 갱신 확인

## 막힌 곳 / 대기
- **네이버 API 키(사용자 몫):** developers.naver.com에서 "검색" 앱 발급 → 저장소 Secret `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` 등록. 키 없어도 구글 RSS로 end-to-end 완성 가능하므로 **블로킹 아님**.

## 메모
- 이 폴더는 E:\ 상위 git repo의 `.gitignore`(클로드백업 제외)에 의해 미추적 → 독립 repo로 관리.
- 시점민감: 경기도지사=추미애, 부천시장=조용익 (2026-07 기준).
- 코드에 키 하드코딩 금지 / 저작권상 전문 복제 금지(제목+스니펫+링크만).
