# FXCorrMonitor

USDKRW와 주요 시장변수 간 롤링 상관관계 및 시기별 주도변수 변화를 모니터링합니다.

인포맥스에서 수동 추출한 Excel을 SQLite에 적재하고, Streamlit이 그 DB만 조회하는 **정적 대시보드**입니다. 실시간 시세·외부 AI API는 사용하지 않습니다.

> 상관관계는 동행을 나타낼 뿐, **인과관계를 의미하지 않습니다.**

## 프로젝트 목적

딜링룸·리서치에서 아래 질문에 빠르게 답하기 위한 모니터입니다.

1. **지금** USDKRW 일간 변동과 가장 강하게 동행하는 변수는 무엇인가  
2. 그 상관관계가 **시기별로** 어떻게 변해 왔는가  
3. **5·20·60·120일** 창에서 주도 변수 해석이 어떻게 달라지는가  

여기서 **주도변수**는 인과가 아니라, 선택한 롤링 창에서 USDKRW와의 **절대 상관계수(|ρ|)가 가장 큰 변수**로 정의합니다.

## 주요 기능

| 화면 | 역할 |
|------|------|
| KPI | 당일 20D 기준 주도변수·환율 등 요약 |
| 롤링 상관계수 | 5/20/60/120D 시계열, Top-N 표시·주도 강조 (기본 20D) |
| 주도변수 랭킹 | 5/20/60/120D ρ와 신규·전환·강화·약화·지속 상태 (상태는 20/60/120) |
| 상관계수 히트맵 | 변수×윈도우 |ρ| 한눈에 비교 |
| 주도변수 타임라인 | 시기별 주도·혼합·없음 국면 색깔 표시 |
| 변수별 상세 | 원본(이중축)·지수화(분석 시작일=100) 비교 |
| 데이터 품질 | 커버리지·이상치 후보 |

공통 원칙:

- **전일 확정 종가**만 사용 (장중 현재가 제외)
- 사이드바 **기준일**(전 거래일)부터 **분석 기간**만큼 조회
- 시차 정렬은 **서울환시** 기준 (`same_day` / `previous_us_close`)
- 가격·지수는 로그수익, 금리는 bp 차분, 수급은 레벨로 변환 후 상관 계산

## 기술 스택

Python 3.11+, pandas, NumPy, SQLite, Streamlit, Plotly

## 빠른 시작

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
- 데모: [https://fxcorrmonitor.streamlit.app](https://fxcorrmonitor.streamlit.app)

```bash
pytest
```

## 데이터·설정

| 항목 | 설명 |
|------|------|
| 입력 | 인포맥스 Excel (시트별 종목) |
| 저장 | SQLite `data/fx_dashboard.db` |
| 종목 매핑 | [`config/instruments.py`](config/instruments.py) |
| 유의선·필터 | [`config/thresholds.py`](config/thresholds.py) (예: 5D 0.60 / 20D 0.44 / 60D 0.25 / 120D 0.18) |
| 충격일 절대하한 | 동일 파일 `SHOCK_ABS_FLOOR` — 자산별 일간변화 99th pct (2015-01-01~2026-08-07) |

파생 수익률·상관계수는 DB에 넣지 않고, 대시보드 조회 시 계산합니다.

## 디렉터리 요약

```
FXCorrMonitor/
├─ app/           # Streamlit UI·CSS
├─ config/        # 종목·임계값
├─ src/           # 적재·변환·분석·차트
├─ scripts/       # Excel 적재 CLI
├─ tests/
└─ main.py        # init-db / ingest / run
```
