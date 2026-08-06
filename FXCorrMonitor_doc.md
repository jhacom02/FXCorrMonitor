# FXCorrMonitor

USDKRW와 주요 시장변수 간 롤링 상관관계 및 시기별 주도변수 변화를 모니터링합니다.

인포맥스에서 수동 추출한 Excel을 SQLite에 적재하고, Streamlit이 SQLite만 조회합니다. LLM·외부 AI API·실시간 시세 API는 사용하지 않습니다. 앱 UI에는 Excel 업로드·DB 적재 버튼이 없으며, 적재는 CLI만 사용합니다.

## 프로젝트 목적

1. 현재 USDKRW 일간 변동과 가장 강하게 동행하는 변수는 무엇인가
2. USDKRW와 각 변수의 상관관계가 시기별로 어떻게 변했는가
3. 20·60·120일 기준으로 주도 변수가 어떻게 달라지는가

## 정적 대시보드 운영 원칙

- 전일 **확정 종가**만 사용합니다. 당일 장중 현재가는 분석에 포함하지 않습니다.
- 분석 기준일(`analysis_as_of_date`)은 DB 내 USDKRW 최신 확정일입니다 (실행일 이전).
- 시차 정렬은 **서울환시 기준**으로 고정합니다.
- 대시보드는 **SQLite만** 조회합니다. 사이드바 **⟲ 새로고침**은 `st.cache_data` 클리어일 뿐 적재가 아닙니다.
- 데이터 갱신: `python scripts/ingest_excel.py --file "..."` 또는 `python main.py ingest --file "..."`
- 동일 DB·동일 as-of·동일 파라미터면 결과가 재현됩니다.

## 설치 및 실행

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python main.py init-db
python scripts/ingest_excel.py --file "data/raw/infomax_raw.xlsx"
streamlit run app/app.py --server.port 8502
```

- 로컬: [http://localhost:8502](http://localhost:8502)
- 사내망: `http://<서버IP>:8502` (`.streamlit/config.toml`의 `address = "0.0.0.0"`)
- 데모(Streamlit Community Cloud): https://fxcorrmonitor.streamlit.app

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
| [`config/thresholds.py`](config/thresholds.py) | 유의선·표시 필터·충격일·국면 상수 |
| [`src/transformation.py`](src/transformation.py) | 변환·서울환시 정렬·as-of 컷오프 |
| [`src/analytics.py`](src/analytics.py) | 롤링 상관·주도·국면·랭킹 상태·역사적 충격일 |
| [`src/charts.py`](src/charts.py) | Plotly 차트·지수화 rebase |
| [`src/database.py`](src/database.py) / [`src/ingestion.py`](src/ingestion.py) | SQLite·Excel 적재 |
| [`main.py`](main.py) | CLI (`init-db` / `ingest` / `run`) |

## Excel·SQLite

인포맥스 추출: 1행 메타(시작/종료/`종목코드`), 2행 종목명, 3행 열이름 → `read_excel(..., header=2)`.

시트 매칭: `종목코드` 우선, 실패·모호 시 정규화 시트명(`_\d+` suffix 제거) fallback. `market_data.source_sheet`에는 원본 시트명 기록.

기본 DB: `data/fx_dashboard.db`

| 테이블 | 역할 |
|--------|------|
| `instruments` | 종목 메타 |
| `market_data` | 일별 원자료 UPSERT |
| `ingestion_log` | 적재 로그 |

파생 수익률·상관계수·robust z는 DB에 저장하지 않고 조회 시 계산합니다.

### 화면 흐름

메타 배너 → KPI → 롤링 상관계수 → 주도변수 랭킹 → 상관계수 히트맵 → 주도변수 타임라인 → 변수별 상세 분석 → **역사적 충격일** → 데이터 품질

**사이드바**

| 항목 | 범위·기본 |
|------|-----------|
| 분석 기간 | `1M`…`10Y` (기본 `1Y`) |
| 전역 임계값 \|ρ\| | 0~1, step 0.05, 기본 `0.30` |
| Robust z-score \|z\| | 3.5~5.0, step 0.5, 기본 `4.0` |
| 변수 선택 | 표시 driver 다중 선택 + 기본값 복원 |

상관관계는 인과를 의미하지 않습니다.

---

## 임계값

정의: [`config/thresholds.py`](config/thresholds.py)

| 상수 | 값 | 의미 |
|------|-----|------|
| `DISPLAY_MIN_ABS_DEFAULT` | 0.30 | 사이드바 전역 \|ρ\| 기본 |
| `SIG_ABS_BY_WINDOW` | 20→0.44, 60→0.25, 120→0.18 | 윈도우 유의선 \(\tau_W\) |
| `display_floor(W,u)` | \(\max(u,\tau_W)\) | 롤링 차트 표시 하한 |
| `MIXED_SCORE_GAP` \(\delta\) | 0.05 | 타임라인 1·2위 혼합 |
| `STATUS_ABS_DELTA` | 0.10 | 랭킹 강화/약화 \|ρ\| 차이 |
| `MIN_PERIOD_RATIO` | 0.8 | \(\texttt{min\_periods}=\lceil W\cdot 0.8\rceil\) |
| `CORR_GUIDE_SOFT` / `STRONG` | 0.30 / 0.70 | 롤링 차트 가이드 |
| `MAD_NORMAL_SCALE` | 1.4826 | MAD→σ 정규분포 보정 |
| `ROBUST_Z_WINDOW` | 252 | robust z 선행 유효 관측 수 |
| `ROBUST_Z_ABS_MIN` | 4.0 | \|z\| 기본 하한 (사이드바 기본값) |
| `SHOCK_ABS_FLOOR` | 자산별 | 충격일 절대 변동 하한 |

### 임계 적용

| 대상 | 임계 |
|------|------|
| KPI (항상 20D) | \(\tau_{20}\)만. 혼합 없음. 미만이면 — |
| 롤링 차트 표시 | \(\texttt{display\_floor}(W,u)\) 후 Top-N. 현재 주도변수는 강제 포함 |
| 롤링 굵은 선 | `latest_top_driver(..., τ_W)` |
| 히트맵 채도 | 셀별 \(\lvert\rho\rvert<\tau_W\)이면 desaturate. 사이드바 \(u\) 미사용 |
| 랭킹 목록 | 사이드바 \(u\) 미적용. \(\lvert\rho_{20}\rvert\) 내림차순 |
| 랭킹 국면 | `classify_driver_status` + \(\tau_W\), `STATUS_ABS_DELTA` |
| 타임라인 | \(\tau_W\)만. 사이드바 \(u\) 미사용 |
| 역사적 충격일 | 사이드바 \|z\| + `SHOCK_ABS_FLOOR` |

---

## 데이터 변환·정렬

변수 \(v_t\) (원자료, sanitize 후):

\[
\begin{aligned}
\texttt{log\_return}:\quad & x_t = \ln\frac{v_t}{v_{t-1}} \\
\texttt{diff\_bp}:\quad & x_t = (y_t - y_{t-1})\times 100 \\
\texttt{level}:\quad & x_t = v_t \quad\text{(F\_NET)}
\end{aligned}
\]

- forward fill 금지, 휴장일 임의 복제 금지, \(\pm\infty\to\mathrm{NaN}\)
- 인포맥스 전일대비/`KR_MID_Chg`/`MID_Chg` 열 미사용
- 변환은 **종목 고유 달력**에서 수행 후 서울 일자로 정렬

**서울 인덱스**: as-of 컷 후 USDKRW가 유효한 날짜 집합 \(S\).

| `alignment` | 규칙 |
|-------------|------|
| `same_day` | \(x\)를 \(S\)에 reindex |
| `previous_us_close` | 각 \(s\in S\)에 대해 **엄격히 이전** 미국 관측을 `merge_asof(..., direction="backward", allow_exact_matches=False)`로 연결 |

`same_day`: USDKRW, DXY, USDJPY, USDCNH, EURUSD, KOSPI, F_NET, KTB3Y, KTB10Y  
`previous_us_close`: SPX, NDX, VIX, WTI, GOLD, UST2Y, UST10Y

시리즈 색: [`app/styles.css`](app/styles.css) `--fx-color-{id}`만 사용.

### 결측률 (데이터 품질)

as-of 컷 후 raw wide 인덱스 길이 \(T=\lvert\texttt{clipped.index}\rvert\), 변수별 raw 유효 관측 \(N\):

\[
\text{missing\_rate} = 1 - \frac{N}{T}
\]

분모는 **연속 달력이 아니라** pivot 합집합입니다. 모든 변수가 빠진 날은 인덱스에 없어 결측으로 잡히지 않습니다. UI 표시 `{:.2%}`.

---

## 롤링 상관계수

분석 기간 lookback으로 자른 `transformed`에서 USDKRW 변환열과 driver \(x\)의 **Pearson** 롤링 상관:

\[
\rho_t^{(W)}
= \mathrm{Corr}\big(x^{\mathrm{USD}}_{t-W+1:t},\; x^{\mathrm{drv}}_{t-W+1:t}\big)
\]

- \(W\in\{20,60,120\}\), \(\texttt{min\_periods}=\lceil 0.8W\rceil\) (16 / 48 / 96)
- 한쪽만 있으면 해당일 쌍에서 제외 (pandas rolling corr)
- \(\rho\notin[-1,1]\)이면 clip
- 부호 임의 반전 없음
- 차트 가이드: \(0,\ \pm 0.30,\ \pm 0.70\)

표시 필터: \(\lvert\rho\rvert \ge \max(u,\tau_W)\). Top-N ∈ {3,5,7,전체}.

**참고**: 상관·KPI·랭킹·타임라인·상세는 lookback 슬라이스 기준. **역사적 충격일만** 전체 `transformed_wide`로 z를 계산합니다.

---

## KPI

항상 \(W=20\). `latest_top_driver(corr_20, τ_20)`:

\[
D = \arg\max_i \lvert\rho_{20,i}\rvert
\quad\text{단}\quad \lvert\rho_{20,D}\rvert \ge \tau_{20}
\]

미만·결측이면 주도변수 — . 혼합(MIXED) 판정 없음.  
카드: 오늘자 주도변수 / 롤링 상관계수 / USDKRW / USDKRW (Chg) (원자료 레벨 차분).

---

## 랭킹 국면 (`classify_driver_status`)

입력 \(\rho_{20},\rho_{60},\rho_{120}\). \(a_W=\lvert\rho_W\rvert\), \(\tau_W=\texttt{sig\_abs}(W)\), \(\Delta=0.10\).  
\(\mathrm{sign}(0)=\texttt{None}\) (코드 `_corr_sign`).

1. \(\rho_{20}\) 결측 또는 \(a_{20}<\tau_{20}\) → **—**
2. \(a_{60}<\tau_{60}\) 이고 \(a_{120}<\tau_{120}\) → **신규**
3. \(\mathrm{sign}(\rho_{20})\neq\mathrm{sign}(\rho_{60})\) 이고 \(a_{60}\ge\tau_{60}\) → **전환**
4. \(\mathrm{sign}(\rho_{20})=\mathrm{sign}(\rho_{60})\neq\mathrm{sign}(\rho_{120})\), \(a_{60}\ge\tau_{60}\), \(a_{120}\ge\tau_{120}\) → **전환**
5. \(\mathrm{sign}(\rho_{20})=\mathrm{sign}(\rho_{60})\) 일 때:
   - \(\texttt{same\_or\_weak\_120} := \big(\mathrm{sign}(\rho_{120})=\mathrm{sign}(\rho_{20})\big) \lor (a_{120}<\tau_{120})\)
   - \(a_{20}-a_{60}\ge\Delta\) 이고 `same_or_weak_120` → **강화**
   - \(a_{60}-a_{20}\ge\Delta\) 이고 `same_or_weak_120` → **약화**
   - \(\lvert a_{20}-a_{60}\rvert < \Delta\) → **지속** (`same_or_weak_120` 조건 **불필요**)
6. 그 외 → **—**

목록: 선택 변수 전체, \(\lvert\rho_{20}\rvert\) 내림차순. 사이드바 \(u\) 미적용.

---

## 주도변수 타임라인

윈도우별 독립. 사이드바 \(u\) 미사용. \(\tau_W=\texttt{sig\_abs}(W)\), \(\delta=0.05\).

### 파이프라인

`calculate_rolling_correlations` → `assign_daily_drivers(min_score=τ_W)` → `_absorb_single_day_regimes` → `compress_driver_regimes` → `driver_timeline_chart`

### 일별 \(D_t\)

날짜 \(t\)에서 \(\lvert\rho\rvert\) 내림차순 1·2위 \(a_{(1)}, a_{(2)}\) (및 대응 \(\rho_{(1)},\rho_{(2)}\)):

| 조건 | \(D_t\) | 저장 |
|------|---------|------|
| \(a_{(1)}<\tau_W\) | `NONE` | \(\rho_t,a_t=\mathrm{NaN}\) |
| \(a_{(1)}-a_{(2)}<\delta\) | `MIXED` | \(\rho_t,a_t=\mathrm{NaN}\); `mix_*`에 1·2위 각각 저장. **두 ρ를 평균해 대표 ρ로 쓰지 않음** |
| 그 외 | 1위 id | \(\rho_t=\rho_{(1)},\ a_t=a_{(1)}\) |

MIXED 표시명: `혼합(name1, name2)`.

### 1일 흡수

연속 동일 `driver_id` run 길이 1이면 **id·name만** 이전(또는 선두면 다음) 라벨로 교체. \(\rho_t,a_t\) 및 mix_*는 유지.

### 국면 압축

동일 `driver_id` 구간 \([t_s,t_e]\):

\[
\begin{aligned}
N &= \text{구간 거래일 수} \\
\bar a &= \mathrm{nanmean}(a_t),\quad
\bar\rho = \mathrm{nanmean}(\rho_t)
\end{aligned}
\]

MIXED 구간 호버용: \(\mathrm{nanmean}(\texttt{mix\_abs\_1}),\ \mathrm{nanmean}(\texttt{mix\_signed\_1})\) 등 (다리별).

### 색

\(\texttt{low\_confidence}=(\bar a.\texttt{fillna}(0)<\tau_W)\):

1. `MIXED` → 앰버 `--fx-color-MIXED`
2. `NONE` 또는 low → 회색 `--fx-color-NONE`
3. 그 외 → `--fx-color-{id}`

오늘자 국면 캡션: `[20D] …, [60D] …, [120D] …` (`regime_label_on_date`; NONE은 —).

---

## 상관계수 히트맵

as-of 스냅샷의 \(\rho_{20},\rho_{60},\rho_{120}\). 행 정렬 \(\lvert\rho_{20}\rvert\) 내림차순.

표시 채도용 \(z\) (부호 있는 ρ를 색 스케일에 넣기 전):

\[
z^{\mathrm{disp}}_{i,W}
=
\begin{cases}
0.6\,z_{i,W} & \lvert\rho_{i,W}\rvert < \tau_W \\
z_{i,W} & \text{otherwise}
\end{cases}
\]

셀 텍스트는 실제 \(\rho\). 사이드바 \(u\) 미사용. `desaturate_factor=0.6`.

---

## 변수별 상세 분석

- **원본**: `dual_raw_level_chart` (이중축)
- **지수화**: `indexed_level_chart` (단일축)

기준일 \(t_0\): 분석 시작일 이후, 비교 두 시계열에 **공통으로 값이 있는 첫날** (`rebase_base_date`).

\[
I_t = 100 \times \frac{P_t}{P_{t_0}}
\quad (P_{t_0}\neq 0)
\]

계산은 full `raw_aligned`에서 rebase 후 lookback으로 표시 슬라이스. 제목: `지수화 비교 (YYYY-MM-DD = 100)`.

상세 패널 상단: `[USDKRW vs {선택변수}]`, 이어서 20/60/120D ρ, 평균 \|ρ\|·ρ, 최소·최대 ρ(날짜).

---

## 역사적 충격일

저·고변동성기를 구분하기 위해 **직전 252 유효 관측** robust z와 **자산별 절대 하한**을 동시에 적용합니다. 등급·분위수 라벨 없음.

### 분석기간 vs 계산기간

```text
full transformed_wide
  → 변수별 dropna 유효관측
  → prior-252 median/MAD → z_t
  → |z|≥z_min AND |x|≥floor
  → 날짜만 lookback [start,end] 필터
  → 표 + "극단값 감지: N개"
```

lookback이 짧아도 median/MAD를 선택 구간 안에서 다시 만들지 않습니다.

### 일간 변화

변환열 \(x_t\) 그대로. `SHOCK_ABS_FLOOR`에 없는 종목(USDKRW, F_NET 등) 및 `level`은 스킵.

### Robust z (look-ahead 금지)

유효 관측 시계열에서 `shift(1)` 후 길이 252, `min_periods=252`:

\[
\begin{aligned}
m_t &= \mathrm{median}(x_{t-252},\ldots,x_{t-1}) \\
\mathrm{MAD}_t &= \mathrm{median}\big(\lvert x_i - m_t\rvert\big)_{i=t-252}^{t-1} \\
\sigma_t &= 1.4826 \times \mathrm{MAD}_t \\
z_t &= \frac{x_t - m_t}{\sigma_t}
\end{aligned}
\]

\(1.4826 = 1/0.67449\ldots\): 정규분포에서 \(\mathrm{MAD}\approx 0.67449\,\sigma\).  
선행 유효관측 \(<252\) 또는 \(\sigma_t=0\) → \(z_t=\mathrm{NaN}\) → 제외.

사이드바 \(z_{\min}\in\{3.5,4.0,4.5,5.0\}\) (기본 4.0). 인자 생략 시 `ROBUST_Z_ABS_MIN`.

### 충격 조건

\[
\lvert z_t\rvert \ge z_{\min}
\quad\land\quad
\lvert x_t\rvert \ge \texttt{SHOCK\_ABS\_FLOOR}[\mathrm{id}]
\]

| 자산 | 절대 하한 (계산 스케일) |
|------|-------------------------|
| DXY, USDJPY, USDCNH, EURUSD | \(\lvert x\rvert\ge 0.02\) (log_return) |
| KOSPI, SPX, NDX | \(\ge 0.05\) |
| VIX | \(\ge 0.30\) |
| WTI | \(\ge 0.15\) |
| GOLD | \(\ge 0.03\) |
| UST2Y, UST10Y, KTB3Y, KTB10Y | \(\lvert x\rvert\ge 20\) (diff_bp) |

### UI

- 캡션1: 252거래일 robust z + 절대하한 설명  
- 캡션2: `극단값 감지: N개` (\(N=\) 필터 후 행 수)  
- 표: 날짜(최신순) / 시장변수 / 일간변화 / robust z-score / 절대하한 / 단위  
- 일간변화·절대하한: log_return은 `×100` 후 `xx.xx%`, 금리는 `xx.xxbp` (문자열 + 우측 정렬)  
- z: 숫자 `%.2f`  
- 단위 열: `log_return` / `diff_bp`  
- 랭킹 표와 동일 `TABLE_HEIGHT`

구현: [`src/analytics.py`](src/analytics.py) `detect_historical_shocks`.

---

## 테스트

| 파일 | 범위 |
|------|------|
| `tests/test_ingestion.py` | 날짜 변환, UPSERT, USDKRW 필수 |
| `tests/test_transformation.py` | 로그수익·bp·level·ffill 금지·시차 정렬 |
| `tests/test_analytics.py` | 롤링 상관·주도·국면·랭킹 국면·충격일(z·하한·`z_abs_min`) |
| `tests/test_charts_display.py` | Top-N 필터·히트맵·지수화 rebase |
