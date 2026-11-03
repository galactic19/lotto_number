# lotto_number

로또 6/45 데이터 사이트. 역대 당첨번호 전체를 분석하는 번호 생성기와 회차별 당첨번호, 실수령액 계산기, 내 번호 역대 당첨 확인, 연금복권720+ 생성기를 제공합니다.

사이트: https://galactic19.github.io/lotto_number/

## 페이지

| 경로 | 내용 |
|---|---|
| `/` | 6가지 알고리즘 번호 생성기, 번호별 출현 차트, 백테스트 |
| `/draws/` | 1회부터 전체 회차 목록 |
| `/draws/{회차}/` | 회차별 당첨번호, 등수별 당첨금, 실수령액, 번호 분석 |
| `/patterns/` | 패턴 20가지를 과거 구간에서 찾고 이후 200회로 검증한 분석 (`scripts/analysis.py`) |
| `/calculator/` | 당첨금 실수령액 계산기 |
| `/check/` | 내 번호로 1회부터 샀다면 몇 등에 몇 번 당첨됐는지 |
| `/pension/` | 연금복권720+ 번호 생성기와 등수별 당첨금 |

## 구조

```
src/base.css         모든 페이지 공통 스타일 (색·폰트 토큰)
src/js/common.js     공통 설정(SITE), 공 렌더링, 롤링 효과, 테마, 광고, 세금 계산
src/js/<page>.js     페이지별 스크립트
src/rules.json       세금 구간·등수 규칙·연금복권 당첨금 (Python과 JS가 함께 사용)
src/templates/       Jinja2 템플릿 (layout.html이 공통 헤더·메뉴·SEO 메타)
scripts/build.py     _site/ 생성 (페이지, 서브셋 폰트, og.png, sitemap.xml)
data/all.json        역대 당첨번호
```

## 빌드

```bash
pip install -r requirements.txt
```

```bash
python3 scripts/build.py --update
```

```bash
python3 -m http.server -d _site
```

`main`에 푸시하면 GitHub Actions가 빌드해서 Pages에 배포하고, 매주 일요일 오전 9시 17분(KST)에 새 회차를 받아 `data/`를 커밋한 뒤 다시 배포합니다. GitHub Pages 설정의 Source는 **GitHub Actions**여야 합니다.

## 광고 설정

`src/js/common.js`의 `SITE.ads`에서 설정합니다. 값이 비어 있으면 광고 자리는 보이지 않아요.

- 쿠팡 파트너스: `provider: "coupang"`, `coupang.trackingCode`에 `AF…`, `slots.default.coupangId`에 다이나믹 배너 ID. 법정 고지 문구가 배너 아래에 자동으로 붙어요
- 구글 애드센스: `provider: "adsense"`, `adsenseClient`에 `ca-pub-…`, 슬롯의 `adsenseSlot`에 슬롯 ID

페이지 주소 끝에 `#ad-preview`를 붙이면 광고 자리 위치를 미리 볼 수 있어요.

## 주의

로또는 매 회차 독립 시행입니다. 어떤 알고리즘도 당첨 확률을 바꾸지 못해요. 재미로만 즐겨주세요.

데이터 출처: [smok95/lotto](https://github.com/smok95/lotto)
