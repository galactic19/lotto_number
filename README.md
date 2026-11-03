# lotto_number

심심풀이 로또번호 추첨기. 역대 로또 6/45 당첨번호 전체를 분석해 6가지 알고리즘으로 번호를 생성하고, 각 알고리즘을 과거 데이터로 백테스트합니다.

## 실행

`index.html`을 브라우저로 열면 됩니다. 서버가 필요 없어요.

## 최신 회차 반영

```bash
pip install -r requirements.txt
```

```bash
python3 scripts/build.py --update
```

`data/all.json`을 새로 받아 `src/template.html`에 넣고 `index.html`을 다시 만듭니다. 폰트(Pretendard)는 페이지에 쓰인 글자만 서브셋해서 HTML에 내장해요.

## 알고리즘

| 이름 | 방식 |
|---|---|
| 핫넘버 | 최근 50회 출현 빈도에 비례한 가중 추첨 |
| 콜드넘버 | 미출현 기간에 비례한 가중 추첨 |
| 동반출현 | 역대 함께 나온 번호 쌍을 따라가며 조합 |
| 흐름 추적 | 직전 회차 → 다음 회차 전이 빈도 (마르코프) |
| 균형 랜덤 | 랜덤 + 균형 필터 (합계·홀짝·고저·연번) |
| 순수 랜덤 | 대조군 |

모든 설정값은 `src/template.html`의 `CONFIG`에 모여 있습니다. 새 알고리즘은 `Strategy`를 상속해 `weights()` 또는 `sample()`만 구현하면 됩니다.

## 주의

로또는 매 회차 독립 시행입니다. 어떤 알고리즘도 당첨 확률을 바꾸지 못해요. 재미로만 즐겨주세요.

데이터 출처: [smok95/lotto](https://github.com/smok95/lotto)

## 광고 설정

`src/template.html`의 `CONFIG.ads`에 승인받은 값을 넣고 다시 빌드하면 광고가 켜집니다. 값이 비어 있으면 광고 자리는 보이지 않아요.

- 카카오 애드핏: `provider: "adfit"`, 각 슬롯의 `adfitMobile`(320×100)·`adfitDesktop`(728×90)에 `DAN-…` 단위 ID
- 구글 애드센스: `provider: "adsense"`, `adsenseClient`에 `ca-pub-…`, 각 슬롯의 `adsenseSlot`에 슬롯 ID

페이지 주소 끝에 `#ad-preview`를 붙이면 광고 자리 위치를 미리 볼 수 있어요.
