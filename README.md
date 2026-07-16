# 경기콘텐츠진흥원(GCA) 일일 언론 모니터링

경기도·경기도의회·경기콘텐츠진흥원·부천시·부천시의회·경기도지사·콘텐츠산업·중앙부처 콘텐츠정책 관련 기사를
**매일 자동 수집 → 중복제거·관련도 필터·키워드 그룹핑 → 웹페이지 발행**하는 0원 파이프라인.

- **공개 페이지:** https://kwannnnnnnnnn.github.io/gca-daily-news/
- **실행:** GitHub Actions cron (매일 **09·13·15·17시 KST**, 하루 4회). PC가 꺼져 있어도 클라우드에서 자동 실행.
- **소스:** 네이버 뉴스검색 API(정확도 주력) + 구글뉴스 RSS(보완). 네이버 키가 없으면 구글만으로 동작.

## 구성
| 파일 | 역할 |
|---|---|
| `keywords.yaml` | 키워드 그룹·필터 규칙(**여기만 고치면 수집대상 변경**) |
| `collect.py` | 네이버 API + 구글 RSS 수집(최근 N시간) |
| `process.py` | 중복제거·관련도 필터·그룹핑 |
| `render.py` | `docs/` 에 HTML/아카이브 발행 |
| `main.py` | 수집→가공→발행 파이프라인 |
| `.github/workflows/daily.yml` | 매일 자동 실행 + 결과 커밋 |
| `docs/` | 발행물(GitHub Pages 서빙 루트) |

## 로컬 실행
```bash
pip install -r requirements.txt
python main.py            # docs/index.html 생성
# 미리보기
python -m http.server -d docs 8765   # → http://127.0.0.1:8765
```

## ★ 네이버 뉴스 API 키(선택, 정확도↑) — 사용자 1회 설정
키가 없어도 구글 RSS로 동작하지만, 한국 언론 정확도를 위해 권장합니다.
1. https://developers.naver.com → 로그인 → **Application 등록** → 사용 API **"검색"** 선택 → **Client ID / Client Secret** 발급.
2. 이 저장소에 Actions Secret 2개 등록(값은 브라우저/CLI에서 직접 입력, **채팅·커밋에 붙여넣지 말 것**):
   - GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**
     - `NAVER_CLIENT_ID`
     - `NAVER_CLIENT_SECRET`
   - 또는 터미널:
     ```bash
     gh secret set NAVER_CLIENT_ID
     gh secret set NAVER_CLIENT_SECRET
     ```
3. 다음 자동 실행부터 네이버 소스가 켜집니다(Actions 탭에서 **Run workflow**로 즉시 확인 가능).

## 키워드/필터 조정
`keywords.yaml`의 `groups`에서 그룹별 `queries`(검색어), `require_any`(제목·요약에 하나라도 있어야 인정),
`exclude`(제외어)를 편집. `global_exclude`는 전 그룹 공통 노이즈 차단. 커밋하면 다음 실행부터 반영.

## 참고
- 저작권상 **제목·짧은 요약·원문 링크**만 저장/표시합니다. 기사 전문은 각 언론사에서 확인하세요.
- GitHub Actions cron은 UTC·best-effort(수 분 지연 가능).
