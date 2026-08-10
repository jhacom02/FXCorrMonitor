# FXCorrMonitor

USDKRW와 주요 시장변수 간 롤링 상관관계 및 시기별 주도변수 변화를 모니터링합니다.

인포맥스에서 수동 추출한 Excel을 SQLite에 적재하고, Streamlit이 SQLite만 조회합니다. LLM·외부 AI API·실시간 시세 API는 사용하지 않습니다. 앱 UI에는 Excel 업로드·DB 적재 버튼이 없으며, 적재는 CLI만 사용합니다.

## 프로젝트 목적

1. 현재 USDKRW 일간 변동과 가장 강하게 동행하는 변수는 무엇인가
2. USDKRW와 각 변수의 상관관계가 시기별로 어떻게 변했는가
3. 5·20·60·120일 창에서 주도 변수 해석이 어떻게 달라지는가

## 정적 대시보드 운영 원칙

- 장중 현재가는 분석에 넣지 않습니다. 입력은 인포맥스 **확정 종가** 시계열입니다.
- **분석 기준일**은 사이드바에서 선택합니다. 기본값은 DB USDKRW **최신 거래일**입니다.
- 시차 정렬은 **서울환시 기준**으로 고정합니다.
- 대시보드는 **SQLite만** 조회합니다. 사이드바 **⟲ 새로고침**은 `st.cache_data` 클리어일 뿐 적재가 아닙니다.
- 데이터 갱신: `python scripts/ingest_excel.py --file "..."` 또는 `python main.py ingest --file "..."`
- 동일 DB·동일 기준일·동일 파라미터면 결과가 재현됩니다.

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
| [`src/utils.py`](src/utils.py) | lookback·세션 스냅·포맷 |
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

`get_db_status`는 USDKRW `MIN(date)` / `MAX(date)`를 `usdkrw_earliest_date` / `usdkrw_latest_date`로 제공합니다. 앱은 DB `mtime`으로 `st.cache_data`를 무효화합니다.

### 화면 흐름

메타 배너 → KPI → 롤링 상관계수 → 주도변수 랭킹 → 상관계수 히트맵 → 주도변수 타임라인 → 변수별 상세 분석 → **역사적 충격일** → 데이터 품질

**사이드바** (위→아래)

| 항목 | 범위·기본 |
|------|-----------|
| ⟲ 새로고침 | 캐시 클리어 후 rerun |
| **기준일** | USDKRW DB 최초~최신 거래일만 선택. 기본=최신일. 비거래일 → 직전 세션으로 스냅 |
| 분석 기간 | `1M`…`10Y` (기본 `1Y`). **기준일로부터** 달력 오프셋 lookback |
| 전역 임계값 \|ρ\| | 0~1, step 0.05, 기본 `0.30` |
| Robust z-score \|z\| | 3.5~5.0, step 0.5, 기본 `4.0` |
| 변수 선택 | 표시 driver 다중 선택 + 기본값 복원 |

상관관계는 인과를 의미하지 않습니다. 「분석 기준 보기」 expander에 임계·섹션 요약이 있습니다.

---

## 기준일·분석 기간

### 기준일 \(T\) (as-of)

1. 달력 `min`/`max` = USDKRW 거래일 집합의 최초·최신.
2. 사용자가 고른 날짜 \(d\)에 대해

\[
T = \max\{\,s\in\mathrm{Sessions}_{\mathrm{USDKRW}} : s \le d\,\}
\]

(`snap_to_prior_session`). \(T\neq d\)이면 사이드바에 `거래일로 조정: T` 표시.

3. `build_analysis_frame(..., as_of_date=T)` → `apply_as_of_cutoff`:

\[
\begin{aligned}
&\text{명시적 }T:\quad
\mathrm{as\_of}=\max\{\,u\in\mathrm{USDKRW}: u\le T\,\} \\
&\text{(CLI 등) }T=\texttt{None}:\quad
\mathrm{as\_of}=\max\{\,u\in\mathrm{USDKRW}: u < \mathrm{run\_date}\,\}
\end{aligned}
\]

이후 `raw_wide.index <= as_of`만 사용. 선택 기준일 **이후** 관측은 분석·충격일 z 계산에 들어가지 않습니다.

### 분석 기간 lookback

기간 키 → `pandas.DateOffset` (달력 기준, 거래일 개수 아님):

\[
\mathrm{end}=T,\qquad
\mathrm{start}=\mathrm{normalize}(T - \mathrm{Offset}(\mathrm{period}))
\]

예: `1Y` → `DateOffset(years=1)`. 상관·KPI·랭킹·타임라인·상세·충격일 **표시 필터**는 \([\mathrm{start},\mathrm{end}]\)로 자릅니다.

메타 배너: 기준일 \(T\)와 `format_lookback_period` 라벨 `1Y (yyyy-mm-dd ~ yyyy-mm-dd)`.

---

## 임계값

정의: [`config/thresholds.py`](config/thresholds.py)

| 상수 | 값 | 의미 |
|------|-----|------|
| `ANALYSIS_WINDOWS` | `(5, 20, 60, 120)` | 공통 분석 창 |
| `DISPLAY_MIN_ABS_DEFAULT` | 0.30 | 사이드바 전역 \|ρ\| 기본 |
| `SIG_ABS_BY_WINDOW` \(\tau_W\) | 5→0.88, 20→0.44, 60→0.25, 120→0.18 | 윈도우 유의선 |
| `display_floor(W,u)` | \(\max(u,\tau_W)\) | 롤링 차트 표시 하한 |
| `MIXED_SCORE_GAP` \(\delta\) | 0.05 | 타임라인 1·2위 혼합 |
| `STATUS_ABS_DELTA` \(\Delta\) | 0.10 | 랭킹 강화/약화 \|ρ\| 차이 |
| `MIN_PERIOD_RATIO` | 0.8 | \(\texttt{min\_periods}=\lceil W\cdot 0.8\rceil\) |
| `CORR_GUIDE_SOFT` / `STRONG` | 0.30 / 0.70 | 롤링 차트 가이드 |
| `MAD_NORMAL_SCALE` | 1.4826 | MAD→σ 정규분포 보정 |
| `ROBUST_Z_WINDOW` | 252 | robust z 선행 유효 관측 수 |
| `ROBUST_Z_ABS_MIN` | 4.0 | \|z\| 기본 하한 |
| `SHOCK_ABS_FLOOR` | 자산별 99th pct | 충격일 절대 변동 하한 (2015-01-01~2026-08-07, ~2,758세션) |

### 유의선 \(\tau_W\) (t-test, 양측 \(p=0.05\))

표본 크기 \(W\), 자유도 \(\nu=W-2\), \(t^*=t_{1-\alpha/2,\nu}\):

\[
\tau_W
= \frac{t^*}{\sqrt{(t^*)^2+\nu}}
\]

코드에 고정된 값: \(\tau_5=0.88\), \(\tau_{20}=0.44\), \(\tau_{60}=0.25\), \(\tau_{120}=0.18\).

`min_periods`: \(W=5\to4\), \(20\to16\), \(60\to48\), \(120\to96\).

### 임계 적용

| 대상 | 임계 |
|------|------|
| KPI | 항상 **20D**, \(\tau_{20}\). 혼합 없음 |
| 롤링 차트 표시 | \(\texttt{display\_floor}(W,u)\). 현재 창 주도변수 강제 포함. 첫 조회 창 기본 **20D** |
| 롤링 굵은 선 | `latest_top_driver(..., τ_W)` |
| 히트맵 채도 | 셀별 \(\lvert\rho\rvert<\tau_W\)이면 desaturate. 사이드바 \(u\) 미사용 |
| 랭킹 목록·정렬 | \(\lvert\rho_{20}\rvert\) 내림차순. 5D ρ는 **표시만** |
| 랭킹 **상태** | `classify_driver_status(ρ20,ρ60,ρ120)`만. **5D 미사용** |
| 타임라인 | 창마다 \(\tau_W\) (5/20/60/120 각각). 사이드바 \(u\) 미사용 |
| 역사적 충격일 | 사이드바 \(z_{\min}\) + `SHOCK_ABS_FLOOR` |

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

**서울 인덱스** \(S\): as-of 컷 후 USDKRW가 유효한 날짜 집합.

| `alignment` | 규칙 |
|-------------|------|
| `same_day` | \(x\)를 \(S\)에 reindex |
| `previous_us_close` | 각 \(s\in S\)에 **엄격히 이전** 미국 관측을 `merge_asof(..., direction="backward", allow_exact_matches=False)` |

`same_day`: USDKRW, DXY, USDJPY, USDCNH, EURUSD, KOSPI, F_NET, KTB3Y, KTB10Y  
`previous_us_close`: SPX, NDX, VIX, WTI, GOLD, UST2Y, UST10Y

시리즈 색: [`app/styles.css`](app/styles.css) `--fx-color-{id}`만 사용.

### 결측률 (데이터 품질)

as-of 컷 후 raw wide 인덱스 길이 \(T=\lvert\texttt{clipped.index}\rvert\), 변수별 raw 유효 관측 \(N\):

\[
\text{missing\_rate} = 1 - \frac{N}{T}
\]

분모는 **연속 달력이 아니라** pivot 합집합입니다. UI: expander「데이터 품질」, `{:.2%}`.

---

## 롤링 상관계수

lookback으로 자른 `transformed`에서 USDKRW 변환열과 driver의 **Pearson** 롤링 상관:

\[
\rho_t^{(W)}
= \mathrm{Corr}\!\left(
  \{x^{\mathrm{USD}}_s\}_{s\in[t-W+1,t]},\;
  \{x^{\mathrm{drv}}_s\}_{s\in[t-W+1,t]}
\right)
\]

구현: `target.rolling(W, min_periods=m).corr(driver)`. 쌍 중 한쪽만 있으면 해당일 제외. \(\rho\notin[-1,1]\)이면 clip.

- \(W\in\{5,20,60,120\}\)
- 롤링 셀렉트: `5D/20D/60D/120D`, 세션 기본 **`20D`**
- 표시 모드 기본: Top 3 (UI). 필터 \(\lvert\rho\rvert\ge\max(u,\tau_W)\) 후 Top-N ∈ {3,5,7,전체}
- 차트 가이드: \(0,\ \pm0.30,\ \pm0.70\)
- lookback 거래일 수 \(< W\)이면 경고 후 차트 생략

**데이터 범위**: 상관·KPI·랭킹·타임라인·상세는 lookback 슬라이스. **충격일 z**는 as-of 컷 **전체**에서 계산(환율·DXY 등은 `raw_aligned` 일간차분, 그 외는 `transformed_wide`) 후 날짜만 lookback 필터.

---

## KPI

항상 \(W=20\). `latest_top_driver(corr_20, \tau_{20})`:

\[
D = \arg\max_i \lvert\rho_{20,i}\rvert
\quad\text{단}\quad \lvert\rho_{20,D}\rvert \ge \tau_{20}
\]

미만·결측 → 주도변수 — . **MIXED 없음**.  
카드: 오늘자 주도변수 / 롤링 상관계수 / USDKRW / USDKRW (Chg) (원자료 레벨 차분 \(\Delta P\)).

---

## 랭킹 국면 (`classify_driver_status`)

입력은 **\(\rho_{20},\rho_{60},\rho_{120}\)만** (5D 무시).  
\(a_W=\lvert\rho_W\rvert\), \(\tau_W=\texttt{sig\_abs}(W)\), \(\Delta=0.10\).  
\(\rho\) 결측 시 \(a=0\), \(\mathrm{sign}(\rho)=\texttt{None}\). \(\mathrm{sign}(0)=\texttt{None}\).

1. \(\rho_{20}\) 결측 또는 \(a_{20}<\tau_{20}\) → **—**
2. \(a_{60}<\tau_{60}\) 이고 \(a_{120}<\tau_{120}\) → **신규**
3. \(\mathrm{sign}(\rho_{20})\neq\mathrm{sign}(\rho_{60})\) 이고 \(a_{60}\ge\tau_{60}\) → **전환**
4. \(\mathrm{sign}(\rho_{20})=\mathrm{sign}(\rho_{60})\neq\mathrm{sign}(\rho_{120})\), \(a_{60}\ge\tau_{60}\), \(a_{120}\ge\tau_{120}\) → **전환**
5. \(\mathrm{sign}(\rho_{20})=\mathrm{sign}(\rho_{60})\) 일 때:
   - \(\texttt{same\_or\_weak\_120} := \big(\mathrm{sign}(\rho_{120})=\mathrm{sign}(\rho_{20})\big) \lor (a_{120}<\tau_{120})\)
   - \(a_{20}-a_{60}\ge\Delta\) ∧ `same_or_weak_120` → **강화**
   - \(a_{60}-a_{20}\ge\Delta\) ∧ `same_or_weak_120` → **약화**
   - \(\lvert a_{20}-a_{60}\rvert < \Delta\) → **지속** (`same_or_weak_120` **불필요**)
6. 그 외 → **—**

표: 순위 / 시장변수 / 상태 / **5D·20D·60D·120D ρ**. 정렬 \(\lvert\rho_{20}\rvert\) 내림차순. KPI 20D 주도 행 강조.

---

## 주도변수 타임라인

창 \(W\in\{5,20,60,120\}\)마다 독립. 사이드바 \(u\) 미사용.

### 파이프라인

`regimes_for_window` =

`calculate_rolling_correlations(W)` → `assign_daily_drivers(min_score=τ_W)` → `compress_driver_regimes`  
(1일 흡수는 **compress 내부**에서 `_absorb_single_day_regimes` 호출)

### 일별 \(D_t\)

날짜 \(t\)에서 \(\lvert\rho\rvert\) 내림차순 1·2위 \(a_{(1)},a_{(2)}\):

| 조건 | \(D_t\) | 저장 |
|------|---------|------|
| \(a_{(1)}<\tau_W\) | `NONE` | \(\rho_t,a_t=\mathrm{NaN}\) |
| \(a_{(1)}-a_{(2)}<\delta\) (\(\delta=0.05\)) | `MIXED` | \(\rho_t,a_t=\mathrm{NaN}\); `mix_*`에 1·2위. **두 ρ를 평균하지 않음** |
| 그 외 | 1위 id | \(\rho_t=\rho_{(1)},\ a_t=a_{(1)}\) |

MIXED 표시명: `혼합(name1, name2)`.

### 1일 흡수

연속 동일 `driver_id` run 길이 1이면 **id·name만** 이웃 라벨로 교체 (\(i>0\): 직전, 선두: 다음). \(\rho_t,a_t\), mix_* 유지.

### 국면 압축

동일 id 구간 \([t_s,t_e]\):

\[
N=\text{거래일 수},\quad
\bar a=\mathrm{nanmean}(a_t),\quad
\bar\rho=\mathrm{nanmean}(\rho_t)
\]

MIXED: \(\mathrm{nanmean}(\texttt{mix\_abs\_1})\), \(\mathrm{nanmean}(\texttt{mix\_signed\_1})\) 등 다리별.

### 색

\(\texttt{low}=(\bar a.\texttt{fillna}(0)<\tau_W)\):

1. `MIXED` → 앰버 `--fx-color-MIXED`
2. `NONE` 또는 low → 회색 `--fx-color-NONE`
3. 그 외 → `--fx-color-{id}`

오늘자 국면: `[5D] …, [20D] …, [60D] …, [120D] …` (`regime_label_on_date`; NONE → —).

---

## 상관계수 히트맵

as-of 스냅샷 \(\rho_5,\rho_{20},\rho_{60},\rho_{120}\) (열 순서 5D→120D). 행 정렬 \(\lvert\rho_{20}\rvert\) 내림차순. KPI 주도 변수 강제 포함.

채도용 표시값 (텍스트는 실제 \(\rho\)):

\[
\rho^{\mathrm{disp}}_{i,W}
=
\begin{cases}
0.6\,\rho_{i,W} & \lvert\rho_{i,W}\rvert < \tau_W \\
\rho_{i,W} & \text{otherwise}
\end{cases}
\]

`desaturate_factor=0.6`. 사이드바 \(u\) 미사용.

---

## 변수별 상세 분석

- **원본**: `dual_raw_level_chart` (이중축)
- **지수화**: `indexed_level_chart` (단일축)

기준일 \(t_0\): lookback 시작일 이후, 두 시계열 **공통 첫 유효일** (`rebase_base_date`).

\[
I_t = 100 \times \frac{P_t}{P_{t_0}}
\quad (P_{t_0}\neq 0)
\]

rebase는 full `raw_aligned`에서 수행 후 lookback으로 표시. 제목: `지수화 비교 (YYYY-MM-DD = 100)`.

패널: `[USDKRW vs {선택변수}]`, 5/20/60/120D ρ, 그리고 **20D 롤링 시계열** 기준 평균 \|ρ\|·ρ·최소·최대(날짜).  
**상태(`classify_driver_status`)는 상세 패널에 없음** (랭킹 전용).

---

## 역사적 충격일

직전 **252 유효 관측** robust z와 자산별 절대 하한을 동시에 적용. 등급·분위수 없음.

절대 하한은 **2015-01-01 ~ 2026-08-07** (약 11년, 자산별 ~2,758세션) 일간 변화의 **99th percentile**로 산정했습니다.  
원천표의 KTB2Y는 앱 종목코드 **KTB3Y**에 매핑합니다.

### 분석기간 vs 계산기간

```text
as-of 컷 전체
  → 스케일별 일간변화 시계열
      abs:   |Δraw|  (raw_aligned_wide.diff)
      return: log_return
      bp:     diff_bp
  → prior-252 median/MAD → z_t
  → |z|≥z_min AND |x|≥floor
  → 날짜만 lookback [start,end] 필터
  → 표 + "극단값 감지: N개"
```

lookback이 짧아도 median/MAD를 선택 구간 안에서 다시 만들지 않습니다.

### 일간 변화

`SHOCK_ABS_FLOOR` / `SHOCK_FLOOR_SCALE`에 정의된 종목만 대상. `F_NET`(level) 등은 스킵.  
환율·달러인덱스(USDKRW, DXY, USDJPY, USDCNH, EURUSD)는 **원본 레벨 일간 차분**으로 z·하한을 적용하고, 그 외 수익률·금리 자산은 변환열 \(x_t\)를 사용합니다.

### Robust z (look-ahead 금지)

유효 관측 시계열에서 `prior = x.shift(1)`, window=252, `min_periods=252`:

\[
\begin{aligned}
m_t &= \mathrm{median}(x_{t-252},\ldots,x_{t-1}) \\
\mathrm{MAD}_t &= \mathrm{median}\big(\lvert x_i - m_t\rvert\big)_{i=t-252}^{t-1} \\
\sigma_t &= 1.4826 \times \mathrm{MAD}_t \\
z_t &= \frac{x_t - m_t}{\sigma_t}
\end{aligned}
\]

\(1.4826\approx 1/0.67449\): 정규분포에서 \(\mathrm{MAD}\approx 0.67449\,\sigma\).  
선행 유효관측 \(<252\) 또는 \(\sigma_t\le 0\) → \(z_t=\mathrm{NaN}\) → 제외.

사이드바 \(z_{\min}\in\{3.5,4.0,4.5,5.0\}\) (기본 4.0).

### 충격 조건

\[
\lvert z_t\rvert \ge z_{\min}
\quad\land\quad
\lvert x_t\rvert \ge \texttt{SHOCK\_ABS\_FLOOR}[\mathrm{id}]
\]

| 자산 | 절대 하한 | 단위·스케일 |
|------|-----------|-------------|
| USDKRW | 23 | 원 (`abs` Δraw) |
| DXY | 1.4 | pt (`abs`) |
| USDJPY | 2.7 | 엔 (`abs`) |
| USDCNH | 0.07 | 위안 (`abs`) |
| EURUSD | 0.02 | 달러 (`abs`) |
| KOSPI | 0.038 | log_return (3.8%) |
| SPX | 0.027 | log_return (2.7%) |
| NDX | 0.035 | log_return (3.5%) |
| VIX | 0.30 | log_return (30%) |
| WTI | 0.084 | log_return (8.4%) |
| GOLD | 0.03 | log_return (3%) |
| UST2Y | 18 | diff_bp |
| UST10Y | 17 | diff_bp |
| KTB3Y | 12 | diff_bp (표기 KTB2Y→KTB3Y) |
| KTB10Y | 12 | diff_bp |

### UI

- 캡션: 252거래일 robust z + 절대하한  
- `극단값 감지: N개` (\(N=\) 필터 후 행 수; 없으면 0 + “조건 충족 충격일 없음”)  
- 표: 날짜 / 시장변수 / 일간변동 / threshold(절대하한) / 단위 / robust z-score / threshold(\(|z|\) 하한)  
- 일간변동·절대 threshold는 숫자만 표시(단위 열에 원·pt·%·bp 등). return 스케일은 ×100 후 표기.

구현: [`src/analytics.py`](src/analytics.py) `detect_historical_shocks`.

---

## 테스트

| 파일 | 범위 |
|------|------|
| `tests/test_ingestion.py` | 날짜 변환, UPSERT, USDKRW 필수 |
| `tests/test_transformation.py` | 로그수익·bp·level·ffill 금지·시차·as-of 스냅 |
| `tests/test_analytics.py` | 롤링 상관·주도·국면·랭킹·충격일·`sig_abs(5)`·세션 스냅 |
| `tests/test_charts_display.py` | Top-N·히트맵(5D 열)·지수화 rebase |
