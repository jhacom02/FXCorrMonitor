# FXCorrMonitor

USDKRW와 주요 금융시장 변수의 **롤링 상관계수** 및 **주도 변수** 변화를 모니터링하는 정적 대시보드입니다.

인포맥스에서 수동 추출한 Excel을 SQLite에 적재하고, Streamlit이 SQLite만 조회합니다. LLM·외부 AI API·실시간 시세 API는 사용하지 않습니다.

## 프로젝트 목적

1. 현재 USDKRW 일간 변동과 가장 강하게 동행하는 변수는 무엇인가
2. USDKRW와 각 변수의 상관관계가 시기별로 어떻게 변했는가
3. 20·60·120일 기준으로 주도 변수가 어떻게 달라지는가
4. 달러·위안·국내주식·위험회피·금리·원자재 중 어떤 요인이 현재 USDKRW를 주도하는가

> **주도 변수**는 인과관계가 아닙니다. 선택한 기간의 **절대 롤링 상관계수**가 가장 높은 변수로 정의합니다.

## 정적 대시보드 운영 원칙

- 전일 **확정 종가**만 사용합니다. 당일 장중 현재가는 분석에 포함하지 않습니다.
- 분석 기준일(`analysis_as_of_date`)은 DB 내 USDKRW 최신 확정일입니다.
- 시차 정렬은 **서울환시 기준**으로 고정합니다. `previous_us_close` 변수는 **직전 미국 종가 → 다음 서울환시 거래일**로 연결하고, `same_day` 변수는 동일 일자로 맞춥니다.
- 대시보드는 인포맥스 Excel 실행 여부와 무관하게 **SQLite만** 조회합니다.
- Excel 파일 감시·실시간 셀 연동은 구현하지 않습니다. 데이터 갱신은 적재 스크립트 또는 UI의 **SQLite 업데이트** 버튼 시에만 수행됩니다.
- 동일 DB 상태·동일 분석 기준일·동일 파라미터면 결과가 재현됩니다.

## 설치 및 실행

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

Excel 적재:

```bash
python scripts/ingest_excel.py --file "data/raw/infomax_raw.xlsx"
```

또는:

```bash
python main.py ingest --file "data/raw/infomax_raw.xlsx"
```

대시보드:

```bash
streamlit run app/app.py
```

접속: [http://localhost:8502](http://localhost:8502) (`.streamlit/config.toml`에서 포트·다크 테마 고정)

또는:

```bash
python main.py run
```

테스트:

```bash
pytest
```

## Excel 구조

인포맥스 추출 파일은 여러 시트로 구성됩니다.

- 1행: 메타데이터
- 2행: 종목명
- 3행: 열 이름 → `pandas.read_excel(..., header=2)`
- 4행~: 데이터

날짜는 datetime 또는 Excel serial(`origin=1899-12-30`)을 모두 지원합니다. 동일 날짜는 마지막 값을 사용합니다.

종목·시트·열 매핑은 [`config/instruments.py`](config/instruments.py)에 정의되어 있습니다. 연결선물 월물이 바뀌어 시트명이 변경되면 이 설정을 갱신해야 합니다.

## SQLite 구조

기본 경로: `data/fx_dashboard.db`

| 테이블 | 역할 |
|--------|------|
| `instruments` | 종목 메타 |
| `market_data` | 일별 원자료 (`date`, `instrument_id`, `raw_value`) UPSERT |
| `ingestion_log` | 적재 성공/실패 로그 |

파생 수익률·상관계수는 DB에 저장하지 않고 조회 시 계산합니다.

## Streamlit 구조

- 진입점: [`app/app.py`](app/app.py)
- 스타일: [`app/styles.css`](app/styles.css)
- 오케스트레이션: [`main.py`](main.py)

화면: 상단 상태 배너(분석 기준일·확정 종가·최종 적재) → KPI → 롤링 상관 차트 → 랭킹 → 히트맵 → 주도 변수 타임라인 → 변수 상세 → 데이터 품질

기본 화면은 최신 절대 롤링 상관계수 상위 5개와 |ρ| ≥ 0.30인 변수만 표시하며, 해당 기준은 분석 계산이 아닌 화면 표시 필터로만 적용된다.

## 테스트 구조

| 파일 | 범위 |
|------|------|
| `tests/test_ingestion.py` | 날짜 변환, UPSERT, USDKRW 필수 |
| `tests/test_transformation.py` | 로그수익·bp·level·ffill 금지·시차 정렬 |
| `tests/test_analytics.py` | 롤링 상관·주도 변수·국면 압축 |

## 데이터 변환 원칙

| 유형 | 변환 |
|------|------|
| 가격/지수 | `log_return = ln(v_t / v_{t-1})` |
| 금리 | `diff_bp = (y_t - y_{t-1}) * 100` |
| 수급(외국인순매수) | 일별 원자료 level 유지 |

- forward fill 금지
- 휴장일 임의 복제 금지
- `±inf` → NaN, 결측을 0으로 대체하지 않음
- 인포맥스 `전일대비` / `KR_MID_Chg` / `MID_Chg` 열은 사용하지 않음

## 롤링 상관계수 계산 원칙

- 기준: USDKRW 로그수익률
- Pearson rolling correlation
- 기본 윈도우: 20 / 60 / 120 (사용자 10–252)
- `min_periods = ceil(window * 0.8)` (20→16, 60→48, 120→96)
- 두 변수 모두 값이 있는 날짜만 사용
- 부호를 임의로 뒤집지 않음 (EURUSD 포함)

## 주도 변수 표시 원칙

1. `driver_score` = 최근 5거래일 `abs(corr)` 중앙값
2. 1위 점수 &lt; 0.30 → 뚜렷한 주도 변수 없음
3. 1·2위 격차 &lt; 0.05 → 혼합 국면
4. 그 외 1위 변수
5. 1거래일짜리 구간은 가능하면 인접 국면에 흡수

화면에는 항상 “상관관계는 인과관계를 의미하지 않는다”는 주석을 표시합니다.

## 디렉터리

```
FXCorrMonitor/
├─ main.py
├─ app/app.py
├─ app/styles.css
├─ config/instruments.py
├─ data/raw/
├─ scripts/ingest_excel.py
├─ src/
└─ tests/
```
