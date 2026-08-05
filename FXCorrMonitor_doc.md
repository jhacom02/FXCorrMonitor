# FXCorrMonitor

USDKRW와 주요 시장변수 간 롤링 상관관계 및 시기별 주도변수 변화를 모니터링합니다.

인포맥스에서 수동 추출한 Excel을 SQLite에 적재하고, Streamlit이 SQLite만 조회합니다. LLM·외부 AI API·실시간 시세 API는 사용하지 않습니다.

## 프로젝트 목적

1. 현재 USDKRW 일간 변동과 가장 강하게 동행하는 변수는 무엇인가
2. USDKRW와 각 변수의 상관관계가 시기별로 어떻게 변했는가
3. 20·60·120일 기준으로 주도 변수가 어떻게 달라지는가

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
streamlit run app/app.py --server.port 8502
```
또는:
```bash
python main.py run
```

- 로컬: [http://localhost:8502](http://localhost:8502)
- 사내망: `http://<서버IP>:8502` (`.streamlit/config.toml`에서 `address = "0.0.0.0"`, 포트 8502·방화벽 인바운드 필요)
- 스트림릿 배포: https://fxcorrmonitor.streamlit.app

테스트:
```bash
pytest
```

## 파일 구조

```
FXCorrMonitor/
├─ main.py
├─ app/
│  ├─ app.py
│  └─ styles.css
├─ config/
│  ├─ instruments.py
│  └─ thresholds.py
├─ src/
│  ├─ analytics.py
│  ├─ charts.py
│  ├─ database.py
│  ├─ ingestion.py
│  ├─ theme.py
│  ├─ transformation.py
│  └─ utils.py
├─ scripts/ingest_excel.py
├─ tests/
├─ data/raw/
└─ .streamlit/config.toml
```

## 모듈·화면 구성

| 경로 | 역할 |
|------|------|
| [`app/app.py`](app/app.py) | Streamlit UI |
| [`app/styles.css`](app/styles.css) | 테마·변수 색(`--fx-color-*`) |
| [`config/instruments.py`](config/instruments.py) | 종목 메타·정렬·변환 (색 hex 없음) |
| [`config/thresholds.py`](config/thresholds.py) | 유의선·표시 필터·국면 상수 |
| [`src/transformation.py`](src/transformation.py) | 변환·서울환시 정렬·as-of 컷오프 |
| [`src/analytics.py`](src/analytics.py) | 롤링 상관·주도·국면·랭킹 상태·역사적 충격일 |
| [`src/charts.py`](src/charts.py) | Plotly 차트 |
| [`src/database.py`](src/database.py) / [`src/ingestion.py`](src/ingestion.py) | SQLite·Excel 적재 |
| [`main.py`](main.py) | CLI (`init-db` / `ingest` / `run`) |

## Excel 구조

인포맥스 추출 파일은 여러 시트로 구성됩니다.

- 1행: 메타데이터 (시작/종료/`종목코드`)
- 2행: 종목명
- 3행: 열 이름 → `pandas.read_excel(..., header=2)`
- 4행~: 데이터

시트는 `종목코드`로 우선 매칭하고, 실패·모호 시에만 정규화 시트명(`_\d+` suffix 제거)으로 fallback합니다. `market_data.source_sheet`에는 원본 시트명(suffix 포함)을 기록합니다.

종목·시트·열 매핑은 [`config/instruments.py`](config/instruments.py)에 정의되어 있습니다. 연결선물 월물이 바뀌어 시트명이 변경되면 이 설정을 갱신해야 합니다.

## SQLite 구조

기본 경로: `data/fx_dashboard.db`

| 테이블 | 역할 |
|--------|------|
| `instruments` | 종목 메타 |
| `market_data` | 일별 원자료 (`date`, `instrument_id`, `raw_value`) UPSERT |
| `ingestion_log` | 적재 성공/실패 로그 |

파생 수익률·상관계수는 DB에 저장하지 않고 조회 시 계산합니다.

### 화면 흐름

메타 배너 → KPI → 롤링 상관계수 → 주도변수 랭킹 → 상관계수 히트맵 → 주도변수 타임라인 → 변수별 상세 분석 → **역사적 충격일** → 데이터 품질

- **메타 배너**: 분석 기준일, 분석 기간 라벨 `1Y (yyyy.mm.dd ~ yyyy.mm.dd)` (`format_lookback_period`)
- **사이드바**: 분석 기간 키만 (`1M`…`10Y`, 날짜 없음), 전역 `|ρ|`(기본 0.30), 표시 변수
- **역사적 충격일**: 데이터 품질 expander 바깥 위. robust z + 자산별 절대 하한 (아래 절)
- **데이터 품질**: expander 안 변수별 커버리지 표만

상관관계는 인과관계를 의미하지 않습니다. 화면에도 동일 취지의 안내를 둡니다.

## 임계값

정의: [`config/thresholds.py`](config/thresholds.py)

| 상수 | 값 | 의미 |
|------|-----|------|
| `DISPLAY_MIN_ABS_DEFAULT` | 0.30 | 사이드바 전역 `|ρ|` 기본값 |
| `sig_abs(20/60/120)` | 0.44 / 0.25 / 0.18 | 윈도우별 통계 유의선 `τ_W` |
| `display_floor(W, user)` | `max(user, sig_abs(W))` | 롤링 차트 표시 하한 |
| `MIXED_SCORE_GAP` (`δ`) | 0.05 | 타임라인 1·2위 혼합 판정 |
| `STATUS_ABS_DELTA` | 0.10 | 랭킹 강화/약화 `|ρ|` 차이 |
| `MIN_PERIOD_RATIO` | 0.8 | 롤링 `min_periods = ceil(W×0.8)` |
| `CORR_GUIDE_SOFT` / `STRONG` | 0.30 / 0.70 | 롤링 차트 수평 가이드 |
| `MAD_NORMAL_SCALE` | 1.4826 | MAD→σ 정규분포 보정 (`MAD ≈ 0.67449·σ`) |
| `ROBUST_Z_WINDOW` | 252 | 충격일 robust z 선행 유효 관측 수 (고정) |
| `ROBUST_Z_ABS_MIN` | 4.0 | `|robust_z|` 충격 하한 |
| `SHOCK_ABS_FLOOR` | 자산별 | 절대 변동 하한 (log_return 또는 bp) |

### 임계 적용 기준

| 대상 | 적용 임계 |
|------|-----------|
| KPI (항상 20D) | `sig_abs(20)`. `latest_top_driver`로 `|ρ|` 1위만 (혼합 없음). 미만이면 — |
| 롤링 차트 **표시 필터** | `display_floor(W, 사이드바)` 통과 후 Top-N (3/5/7/전체). 현재 주도변수는 Top-N·필터와 무관하게 강제 표시 |
| 롤링 차트 **굵은 선** | 해당 창 `latest_top_driver(..., sig_abs(W))` |
| 히트맵 채도 | 셀별 `|ρ| < sig_abs(W)`이면 desaturate. **사이드바 미사용** |
| 주도변수 랭킹 목록 | 사이드바 미적용. 선택 변수 전체, `|20D ρ|` 내림차순 |
| 랭킹 **국면** 열 | `classify_driver_status` + `sig_abs` / `STATUS_ABS_DELTA` |
| 타임라인 일별 배정·low | `sig_abs(W)`만. **사이드바 미사용** |

## 데이터 변환

| 유형 | 변환 |
|------|------|
| 가격/지수 | `log_return = ln(v_t / v_{t-1})` |
| 금리 | `diff_bp = (y_t - y_{t-1}) × 100` |
| 수급(F_NET) | 일별 원자료 `level` 유지 |

- forward fill 금지, 휴장일 임의 복제 금지
- `±inf` → NaN, 결측을 0으로 대체하지 않음
- 인포맥스 `전일대비` / `KR_MID_Chg` / `MID_Chg` 열은 사용하지 않음
- 시차: `same_day`는 서울 일자 동일, `previous_us_close`는 직전 미국 종가 → 다음 서울 거래일
- 시리즈 색: [`app/styles.css`](app/styles.css)의 `--fx-color-{id}`만 사용 (`instruments.py`에 hex 하드코딩 없음)

## 롤링 상관계수

- 대상: USDKRW 변환열 vs 선택 drivers의 **Pearson** 롤링 상관
- 윈도우: UI·분석 공통 **20 / 60 / 120** (`ANALYSIS_WINDOWS`)
- `min_periods = ceil(window × 0.8)` (20→16, 60→48, 120→96)
- 두 변수 모두 값이 있는 날짜만 사용, 부호를 임의로 뒤집지 않음
- 차트 가이드선: 0, ±0.30, ±0.70

## 랭킹 국면 (`classify_driver_status`)

입력: 당일 `ρ_20`, `ρ_60`, `ρ_120`. `a_W = |ρ_W|`, `τ_W = sig_abs(W)`.

우선순위:

1. `a_20 < τ_20` (또는 `ρ_20` 결측) → **—**
2. `a_60 < τ_60` 이고 `a_120 < τ_120` → **신규**
3. `sign(ρ_20) ≠ sign(ρ_60)` 이고 `a_60 ≥ τ_60` → **전환**
4. `sign(ρ_20)=sign(ρ_60)≠sign(ρ_120)` 이고 `a_60≥τ_60`, `a_120≥τ_120` → **전환**
5. `sign(ρ_20)=sign(ρ_60)` 이고 (`sign(ρ_120)=sign(ρ_20)` 또는 `a_120 < τ_120`):
   - `a_20 - a_60 ≥ 0.10` → **강화**
   - `a_60 - a_20 ≥ 0.10` → **약화**
   - `|a_20 - a_60| < 0.10` → **지속**
6. 그 외 → **—**

## 주도변수 타임라인

윈도우별로 독립 계산. 사이드바 `|ρ|`는 쓰지 않습니다.

### 파이프라인

`calculate_rolling_correlations` → `assign_daily_drivers(min_score=τ_W)` → `_absorb_single_day_regimes` → `compress_driver_regimes` / `_finalize_regime` → `driver_timeline_chart`

### 일별 주도 `D_t`

날짜 `t`에서 `|ρ|` 내림차순 1·2위 `a_{(1)}`, `a_{(2)}`:

| 조건 | `D_t` | 저장 `a_t`, `ρ_t` |
|------|-------|-------------------|
| `a_{(1)} < τ_W` | `NONE` | NaN |
| `a_{(1)} - a_{(2)} < δ` (0.05) | `MIXED` | NaN (두 변수 상관을 평균하지 않음) |
| 그 외 | 1위 변수 id | 1위의 `ρ`, `|ρ|` |

### 1일 흡수

연속 동일 `driver_id` run 길이가 1이면 **id·name만** 변경 (`a_t`/`ρ_t` 유지).

- 인덱스 `i > 0`: `D_i ← D_{i-1}` (직전 거래일 라벨)
- 선두 `i = 0`: `D_0 ← D_1` (다음 거래일 라벨)

### 국면 압축·평균

같은 `driver_id`가 이어지는 구간 `[t_s, t_e]`에 대해:

- `trading_days` `N` = 구간 거래일 수 (NaN과 무관)
- `average_abs_correlation` `ā` = `nanmean(a_t)` — 유한한 `a_t`만 산술평균; 전부 NaN이면 NaN
- `average_signed_correlation`도 동일하게 `nanmean(ρ_t)`

순수 `NONE`/`MIXED` 구간은 일별 값이 NaN이므로 `ā`도 NaN입니다.

### 색

`low_confidence = (ā.fillna(0) < τ_W)`. 우선순위:

1. `MIXED` → 앰버 (`--fx-color-MIXED`)
2. `NONE` 또는 `low_confidence` → 회색 (`--fx-color-NONE`)
3. 그 외 단일 주도 → `--fx-color-{id}`

## 변수별 상세 분석

- **원본값 비교**: `dual_raw_level_chart` (이중축)
- **지수화 비교**: `indexed_level_chart` (단일축). 분석 구간 내 두 시계열의 **첫 공통 유효일 = 100** (`rebase_base_date` / `rebase_series_to_100`)
- 범례는 차트 안 inset; y축 상단 headroom으로 선과 겹침을 줄임. 지수화 차트는 원본과 plot 너비 정렬을 위해 투명 우측축을 둠

## 역사적 충격일

시기별 변동성 체제를 반영하기 위해 **고정 절대 임계만** 쓰지 않고, 직전 252거래일(유효 관측) 기준 robust z-score와 자산별 절대 하한을 **동시에** 적용합니다. 등급·분위수 라벨은 없습니다.

### 분석기간 vs 계산기간

- 화면 분석기간(`1M`…`10Y`)은 **표시 필터**만 담당합니다.
- robust z는 `build_analysis_frame`의 **전체** `transformed_wide`에서 변수별 유효 관측으로 계산합니다.
- lookback이 짧아도 median/MAD를 선택 구간 안에서 다시 산출하지 않습니다.

### 일간 변화량

기존 변환과 동일: 가격·지수·환율·원자재·VIX → `log_return`, 금리 → `diff_bp`. `SHOCK_ABS_FLOOR`에 없는 종목(USDKRW, F_NET 등)은 탐지 대상이 아닙니다.

### Robust z (look-ahead 금지)

시점 `t`의 변화량 `x_t`는 통계 창에서 제외합니다.

```
rolling_median_t = median(x[t-252 : t-1])   # 유효 관측 252개
rolling_mad_t    = median(|x[t-252 : t-1] - rolling_median_t|)
robust_sigma_t   = MAD_NORMAL_SCALE * rolling_mad_t   # 1.4826
robust_z_t       = (x_t - rolling_median_t) / robust_sigma_t
```

`MAD_NORMAL_SCALE = 1.4826`은 정규분포에서 `MAD ≈ 0.67449·σ`이므로 `σ ≈ MAD/0.67449 ≈ 1.4826·MAD`가 되는 보정계수입니다. 금융 수익률은 두꺼운 꼬리를 가지므로 `|z|=4`가 정규분포 확률을 그대로 의미하지는 않으며, 시기별 변동성 대비 충격 강도 비교용 표준화 지표입니다. 선행 유효관측 &lt; 252이거나 `robust_sigma=0`이면 해당일 z는 NaN → 후보 제외.

구현: [`src/analytics.py`](src/analytics.py) `detect_historical_shocks` (`shift(1)` + rolling 252).

### 충격 조건

`abs(robust_z) >= 4` **AND** `abs(x_t) >= SHOCK_ABS_FLOOR[instrument]`

| 자산 | 절대 하한 |
|------|-----------|
| DXY, USDJPY, USDCNH, EURUSD | `\|log_return\| ≥ 0.02` |
| KOSPI, SPX, NDX | `≥ 0.05` |
| VIX | `≥ 0.30` |
| WTI | `≥ 0.15` |
| GOLD | `≥ 0.03` |
| UST2Y, UST10Y, KTB3Y, KTB10Y | `\|bp\| ≥ 25` |

### UI

- 표: 날짜(최신순) / 시장변수 / 일간변화 / robust z-score / 절대임계값 / 단위
- 일간변화: log_return은 퍼센트(`0.1135` → `11.35%`), 금리는 `bp`
- z·절대임계값: 소수 둘째 자리

## 테스트

| 파일 | 범위 |
|------|------|
| `tests/test_ingestion.py` | 날짜 변환, UPSERT, USDKRW 필수 |
| `tests/test_transformation.py` | 로그수익·bp·level·ffill 금지·시차 정렬 |
| `tests/test_analytics.py` | 롤링 상관·주도·국면 흡수·랭킹 국면·역사적 충격일(robust z) |
| `tests/test_charts_display.py` | Top-N 필터·히트맵·지수화 rebase |

