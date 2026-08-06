"""FX Correlation Monitor — Streamlit dashboard (static settled closes only)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.instruments import (
    DEFAULT_DRIVER_IDS,
    INSTRUMENT_BY_ID,
    TARGET_ID,
    get_driver_instruments,
)
from config.thresholds import (
    ANALYSIS_WINDOWS,
    DISPLAY_MIN_ABS_DEFAULT,
    ROBUST_Z_ABS_MIN,
    display_floor,
    sig_abs,
)
from src.analytics import (
    DRIVER_MIXED,
    DRIVER_NONE,
    calculate_rolling_correlations,
    classify_driver_status,
    detect_historical_shocks,
    latest_top_driver,
    multi_window_correlations,
    regimes_for_window,
    regime_label_on_date,
)
from src.database import get_db_status, load_market_data
from src.transformation import build_analysis_frame
from src.utils import (
    DEFAULT_DB_PATH,
    DEFAULT_LOOKBACK_PERIOD,
    LOOKBACK_PERIODS,
    db_mtime_key,
    format_corr,
    format_fx,
    format_lookback_period,
    lookback_range,
    setup_logging,
)
from src.theme import load_css_vars, read_styles_css
from src.charts import (
    DISPLAY_MODE_LABELS,
    PLOTLY_CONFIG,
    build_rank_line,
    correlation_heatmap,
    driver_timeline_chart,
    dual_raw_level_chart,
    indexed_level_chart,
    rebase_base_date,
    rebase_series_to_100,
    rolling_correlation_chart,
)

logger = logging.getLogger(__name__)
setup_logging(False)

st.set_page_config(
    page_title="FX Correlation Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)


_CSS_VARS: dict[str, str] = {}
TABLE_HEIGHT = 420


def _load_css() -> None:
    global _CSS_VARS
    text = read_styles_css()
    if text:
        st.markdown(f"<style>{text}</style>", unsafe_allow_html=True)
        _CSS_VARS = load_css_vars()
    else:
        _CSS_VARS = {}


@st.cache_data(show_spinner=False)
def cached_market_data(db_path: str, mtime: float) -> pd.DataFrame:
    return load_market_data(db_path)


@st.cache_data(show_spinner=False)
def cached_db_status(db_path: str, mtime: float) -> dict:
    return get_db_status(db_path)


def _safe_message(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def render_empty_state() -> None:
    st.title("FX Correlation Monitor")
    st.caption("USDKRW와 주요 시장변수 간 롤링 상관관계 및 시기별 주도변수 변화를 모니터링합니다.")
    st.info(
        "SQLite에 적재된 데이터가 없습니다.\n\n"
        "1. 인포맥스에서 Excel을 추출합니다.\n"
        "2. `data/raw/`에 저장합니다.\n"
        "3. 아래 명령으로 적재합니다.\n\n"
        '`python scripts/ingest_excel.py --file "data/raw/infomax_raw.xlsx"`\n\n'
        "본 대시보드는 실시간 데이터가 아닌 **전일 확정 종가**만 사용합니다."
    )


def sidebar_controls() -> dict:
    st.sidebar.header("분석 설정")

    if st.sidebar.button("⟲ 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    period_key = st.sidebar.selectbox(
        "분석 기간",
        LOOKBACK_PERIODS,
        index=LOOKBACK_PERIODS.index(DEFAULT_LOOKBACK_PERIOD),
    )

    min_abs = st.sidebar.slider(
        "전역 임계값 |ρ|",
        0.0,
        1.0,
        float(DISPLAY_MIN_ABS_DEFAULT),
        0.05,
    )

    robust_z_min = st.sidebar.slider(
        "Robust z-score |z|",
        3.5,
        5.0,
        float(ROBUST_Z_ABS_MIN),
        0.5,
    )

    drivers = get_driver_instruments()
    all_options = {d.display_name: d.instrument_id for d in drivers}
    default_names = [
        INSTRUMENT_BY_ID[i].display_name
        for i in DEFAULT_DRIVER_IDS
        if i in INSTRUMENT_BY_ID and INSTRUMENT_BY_ID[i].active
    ]
    all_names = list(all_options.keys())

    with st.sidebar.expander("변수 선택", expanded=False):
        if "var_multiselect" not in st.session_state:
            st.session_state["var_multiselect"] = [n for n in default_names if n in all_names]
        else:
            st.session_state["var_multiselect"] = [
                n for n in st.session_state["var_multiselect"] if n in all_names
            ] or [n for n in default_names if n in all_names]

        st.multiselect(
            "표시 변수",
            options=all_names,
            key="var_multiselect",
            label_visibility="collapsed",
        )

        def _restore_default_vars() -> None:
            st.session_state["var_multiselect"] = [n for n in default_names if n in all_names]

        st.button(
            "기본값 복원",
            use_container_width=True,
            on_click=_restore_default_vars,
        )

    selected_ids = [
        all_options[n]
        for n in st.session_state.get("var_multiselect", default_names)
        if n in all_options
    ]

    return {
        "period_key": period_key,
        "selected_ids": selected_ids,
        "min_abs": float(min_abs),
        "robust_z_min": float(robust_z_min),
    }


def kpi_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="fx-card">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_meta_banner(as_of_str: str, period_key: str) -> None:
    period_label = format_lookback_period(period_key, as_of_str)
    st.markdown(
        f"""
        <div class="fx-meta-banner">
          <div class="fx-meta-grid">
            <div class="fx-meta-item">
              <div class="fx-meta-label">기준일</div>
              <div class="fx-meta-value">{as_of_str}</div>
            </div>
            <div class="fx-meta-item">
              <div class="fx-meta-label">분석 기간</div>
              <div class="fx-meta-value">{period_label}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def driver_row_style(is_driver: bool, ncols: int) -> list[str]:
    if not is_driver:
        return [""] * ncols
    bg = _CSS_VARS.get("fx-row-driver-bg")
    return [f"background-color:{bg}"] * ncols


def _signed_rho_text(val: float | None) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}"


def _rho_from_multi(multi: pd.DataFrame, instrument_id: str, window: int) -> float:
    if multi.empty:
        return np.nan
    hit = multi[(multi["instrument_id"] == instrument_id) & (multi["window"] == window)]
    if hit.empty:
        return np.nan
    val = hit.iloc[0]["rolling_correlation"]
    return float(val) if pd.notna(val) else np.nan


def main() -> None:
    _load_css()
    db_path = DEFAULT_DB_PATH
    mtime = db_mtime_key(db_path)

    try:
        status = cached_db_status(str(db_path), mtime)
    except Exception as exc:
        logger.exception("DB status failed")
        st.error(f"데이터베이스 상태를 확인할 수 없습니다: {_safe_message(exc)}")
        return

    controls = sidebar_controls()

    if not status.get("db_exists") or not status.get("market_data_exists") or not status.get("usdkrw_latest_date"):
        render_empty_state()
        return

    st.title("FX Correlation Monitor")
    st.caption("USDKRW와 주요 시장변수 간 롤링 상관관계 및 시기별 주도변수 변화를 모니터링합니다.")

    if not controls["selected_ids"]:
        st.warning("표시할 변수를 하나 이상 선택하세요.")
        return

    try:
        market = cached_market_data(str(db_path), mtime)
        if market.empty:
            render_empty_state()
            return

        frame = build_analysis_frame(
            market,
            include_inactive=False,
        )
        as_of_str = frame["analysis_as_of_date"]
        as_of = pd.Timestamp(as_of_str)

        render_meta_banner(as_of_str, controls["period_key"])

        start, end = lookback_range(as_of, controls["period_key"])

        transformed = frame["transformed_wide"]
        raw_full = frame["raw_aligned_wide"]
        transformed = transformed.loc[(transformed.index >= start) & (transformed.index <= end)]
        raw_aligned = raw_full.loc[(raw_full.index >= start) & (raw_full.index <= end)]

        selected_drivers = [i for i in controls["selected_ids"] if i in transformed.columns]
        if not selected_drivers:
            st.warning("선택한 변수의 유효 데이터가 부족합니다.")
            return

        corr_20 = calculate_rolling_correlations(
            transformed,
            target=TARGET_ID,
            drivers=selected_drivers,
            window=20,
        )
        snap = latest_top_driver(corr_20, sig_abs(20))
        driver_id = snap.get("driver_id")

        heatmap_drivers = list(selected_drivers)
        if driver_id and driver_id not in (DRIVER_NONE, DRIVER_MIXED) and driver_id in transformed.columns:
            if driver_id not in heatmap_drivers:
                heatmap_drivers = heatmap_drivers + [driver_id]

        multi = multi_window_correlations(
            transformed,
            drivers=heatmap_drivers,
            windows=list(ANALYSIS_WINDOWS),
            as_of_date=transformed.index.max() if len(transformed) else as_of,
        )

        display_ids = list(selected_drivers)

        # --- KPI ---
        usd_raw = raw_aligned[TARGET_ID].dropna() if TARGET_ID in raw_aligned.columns else pd.Series(dtype=float)
        latest_fx = float(usd_raw.iloc[-1]) if len(usd_raw) else np.nan
        if len(usd_raw) >= 2:
            latest_chg = float(usd_raw.iloc[-1]) - float(usd_raw.iloc[-2])
        else:
            latest_chg = np.nan

        rho_txt = _signed_rho_text(snap.get("signed_correlation"))
        if pd.isna(latest_chg):
            chg_txt = "—"
        else:
            sign = "+" if latest_chg > 0 else ""
            chg_txt = f"{sign}{latest_chg:,.2f}"

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            driver_kpi = "—" if driver_id == DRIVER_NONE else snap["driver_name"]
            kpi_card("오늘자 주도변수", driver_kpi)
        with c2:
            kpi_card("롤링 상관계수", rho_txt)
        with c3:
            kpi_card("USDKRW", format_fx(latest_fx))
        with c4:
            kpi_card("USDKRW (Chg)", chg_txt)

        with st.expander("분석 기준 보기", expanded=False):
            st.markdown(
                """
<div class="fx-detail-panel">
<ul>
<li>Pearson 롤링 상관계수(20일, 60일, 120일)를 계산합니다.</li>
<li>높은 상관은 동행을 의미하며, 인과관계를 의미하지 않습니다.</li>
<li>전일 확정 종가만 사용하며, 실시간 현재가는 포함하지 않습니다. (출처: Infomax)</li>
<hr>
<li>전역 상관계수 임계값: 0.30 (사이드바 설정 가능)</li>
<li>윈도우 상관계수 임계값(t-test, p=0.05): |20D ρ| ≥ 0.44 / |60D ρ| ≥ 0.25 / |120D ρ| ≥ 0.18</li>
<li>역사적 충격 robust z-score: |robust z| ≥ 4.0 (사이드바 설정)</li>
<li>역사적 충격 절대하한: |통화| ≥ 2% / |주가| ≥ 5% / |VIX| ≥ 30% / |WTI| ≥ 15% / |GOLD| ≥ 3% / |금리| ≥ 20bp</li>
<hr>
<li>[KPI 카드] |20D ρ| 기준 1위 변수만 표시. 윈도우 임계값 이상일 때만 표시.</li>
<li>[롤링 상관계수] 차트에 max(전역 임계값, 윈도우 임계값) 이상인 변수만 표시.</li>
<li>[주도변수 랭킹] 변수 전체 표시. |20D ρ| 내림차순 정렬. 신규/전환/강화/약화/지속 국면 표시.</li>
<li>[상관계수 히트맵] 변수 전체 표시. |20D ρ| 내림차순 정렬. 윈도우 임계값 미만이면 흐림.</li>
<li>[주도변수 타임라인] 시기별 주도/혼합 국면 표시. 주도 없음은 회색, 혼합은 앰버로 표시.</li>
<li>[변수별 상세 분석] 원본값 비교 차트는 이중축, 지수화 비교 차트는 단일축 (분석 시작일=100).</li>
<li>[역사적 충격일] 직전 252거래일 robust z-score & 자산별 절대하한 이상인 outlier 표시.</li>
<li>[데이터 품질] 결측률 표시.</li>
</ul>
</div>
                """,
                unsafe_allow_html=True,
            )

        # --- Rolling chart ---
        st.markdown('<div class="fx-section-title">롤링 상관계수</div>', unsafe_allow_html=True)
        st.caption("최근 롤링 상관계수 기준 상위 N개 시장변수를 표시합니다. 전역 임계값 이상인 변수만 표시합니다.")

        if "roll_window_label" not in st.session_state:
            st.session_state["roll_window_label"] = "20D"
        if "roll_display_label" not in st.session_state:
            st.session_state["roll_display_label"] = list(DISPLAY_MODE_LABELS.values())[0]

        _rw = str(st.session_state["roll_window_label"]).replace("일", "").replace("D", "")
        chart_window = int(_rw)
        display_mode = {
            v: k for k, v in DISPLAY_MODE_LABELS.items()
        }[st.session_state["roll_display_label"]]

        if len(transformed) < chart_window:
            st.warning(
                f"선택 기간({len(transformed)}거래일)이 롤링 윈도우({chart_window}일)보다 짧습니다. "
                "분석 기간을 늘리거나 윈도우를 줄이세요."
            )
            chart_corr = pd.DataFrame()
            chart_info: dict = {"show_ids": []}
        else:
            chart_corr = calculate_rolling_correlations(
                transformed,
                target=TARGET_ID,
                drivers=selected_drivers,
                window=chart_window,
            )
            chart_top = latest_top_driver(chart_corr, sig_abs(chart_window))
            chart_driver_id = chart_top.get("driver_id")
            chart_selected = list(selected_drivers)
            if chart_driver_id and chart_driver_id not in (DRIVER_NONE, DRIVER_MIXED):
                if chart_driver_id in transformed.columns and chart_driver_id not in chart_selected:
                    chart_selected = chart_selected + [chart_driver_id]
                    chart_corr = calculate_rolling_correlations(
                        transformed,
                        target=TARGET_ID,
                        drivers=chart_selected,
                        window=chart_window,
                    )
            fig, chart_info = rolling_correlation_chart(
                chart_corr,
                selected_instruments=selected_drivers,
                current_driver_id=(
                    chart_driver_id if chart_driver_id not in (DRIVER_NONE, DRIVER_MIXED) else None
                ),
                display_mode=display_mode,
                min_abs_correlation=display_floor(chart_window, controls["min_abs"]),
                window=chart_window,
            )
            rank_line = build_rank_line(chart_corr, chart_info.get("show_ids") or [])
            if rank_line:
                st.caption(rank_line)

        f1, f2 = st.columns(2)
        with f1:
            st.selectbox(
                "롤링 윈도우",
                ["20D", "60D", "120D"],
                key="roll_window_label",
            )
        with f2:
            st.selectbox(
                "표시 변수",
                list(DISPLAY_MODE_LABELS.values()),
                key="roll_display_label",
            )

        if len(transformed) >= chart_window and not chart_corr.empty:
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, theme=None)

        # --- Ranking ---
        st.markdown('<div class="fx-section-title">주도변수 랭킹</div>', unsafe_allow_html=True)
        st.caption("최근 20D/60D/120D 상관계수를 표시하며, 국면 열에 신규/전환/강화/약화/지속을 표시합니다.")
        rank_rows: list[dict] = []
        for iid in display_ids:
            inst = INSTRUMENT_BY_ID.get(iid)
            if inst is None:
                continue
            r20 = _rho_from_multi(multi, iid, 20)
            r60 = _rho_from_multi(multi, iid, 60)
            r120 = _rho_from_multi(multi, iid, 120)
            rank_rows.append(
                {
                    "instrument_id": iid,
                    "시장변수": inst.display_name,
                    "국면": classify_driver_status(r20, r60, r120),
                    "20D ρ": r20,
                    "60D ρ": r60,
                    "120D ρ": r120,
                    "_abs20": abs(r20) if pd.notna(r20) else -1.0,
                }
            )
        if not rank_rows:
            st.info("표시할 랭킹 변수가 없습니다.")
        else:
            rank_df = pd.DataFrame(rank_rows).sort_values("_abs20", ascending=False).reset_index(drop=True)
            rank_df.insert(0, "순위", [str(i) for i in range(1, len(rank_df) + 1)])
            driver_rows = set(
                rank_df.index[rank_df["instrument_id"] == driver_id].tolist()
            ) if driver_id else set()

            def _row_style(row: pd.Series) -> list[str]:
                return driver_row_style(row.name in driver_rows, len(row))

            visible = rank_df[["순위", "시장변수", "국면", "20D ρ", "60D ρ", "120D ρ"]]
            styler = (
                visible.style.format(
                    {"20D ρ": "{:.2f}", "60D ρ": "{:.2f}", "120D ρ": "{:.2f}"},
                    na_rep="—",
                ).apply(_row_style, axis=1)
            )
            st.dataframe(
                styler,
                use_container_width=True,
                hide_index=True,
                height=TABLE_HEIGHT,
            )
        st.caption("")

        # --- Heatmap ---
        st.markdown('<div class="fx-section-title">상관계수 히트맵</div>', unsafe_allow_html=True)
        st.caption("히트맵 색상은 상관계수의 부호와 크기를 나타내며 호재/악재를 의미하지 않습니다.")
        if multi.empty:
            st.info("히트맵을 그릴 변수가 없습니다.")
        else:
            st.plotly_chart(
                correlation_heatmap(
                    multi,
                    current_driver_id=driver_id if driver_id not in (DRIVER_NONE, DRIVER_MIXED) else None,
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                theme=None,
            )
        st.caption("")

        # --- Timeline ---
        st.markdown('<div class="fx-section-title">주도변수 타임라인</div>', unsafe_allow_html=True)
        st.caption("주도변수가 없거나 평균 |ρ|가 임계점 미만이면 회색, 주도변수 2개 이상의 혼합 국면이면 앰버로 표시합니다.")
        x_range = [start, end + pd.Timedelta(days=1)]
        as_of_tl = transformed.index.max()
        timeline_regimes: list[tuple[str, pd.DataFrame]] = []
        for w, label in zip(ANALYSIS_WINDOWS, ("20D", "60D", "120D")):
            timeline_regimes.append(
                (label, regimes_for_window(transformed, selected_drivers, w))
            )
        today_parts = [
            f"[{label}] {regime_label_on_date(reg, as_of_tl)}" for label, reg in timeline_regimes
        ]
        st.caption("오늘자 국면: " + ", ".join(today_parts))
        for (label, regimes_w), w in zip(timeline_regimes, ANALYSIS_WINDOWS):
            st.plotly_chart(
                driver_timeline_chart(
                    regimes_w,
                    title=label,
                    x_range=x_range,
                    low_confidence_threshold=sig_abs(w),
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                theme=None,
            )

        # --- Detail ---
        st.markdown('<div class="fx-section-title">변수별 상세 분석</div>', unsafe_allow_html=True)
        st.caption("USDKRW와 선택한 변수의 원본값 및 지수화 비교를 표시합니다.")
        detail_drivers = [d for d in get_driver_instruments() if d.instrument_id in raw_aligned.columns]
        if not detail_drivers:
            st.info("표시할 시장변수가 없습니다.")
        else:
            detail_names = [d.display_name for d in detail_drivers]
            pick_name = st.selectbox("비교 변수 선택", detail_names)
            pick = next(d.instrument_id for d in detail_drivers if d.display_name == pick_name)
            inst = INSTRUMENT_BY_ID[pick]
            usd_s = raw_aligned[TARGET_ID] if TARGET_ID in raw_aligned.columns else pd.Series(dtype=float)
            drv_s = raw_aligned[pick] if pick in raw_aligned.columns else pd.Series(dtype=float)
            st.plotly_chart(
                dual_raw_level_chart(
                    usd_s,
                    drv_s,
                    inst.display_name,
                    title="원본값 비교",
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                theme=None,
            )

            usd_full = raw_full[TARGET_ID] if TARGET_ID in raw_full.columns else pd.Series(dtype=float)
            drv_full = raw_full[pick] if pick in raw_full.columns else pd.Series(dtype=float)
            base_day = rebase_base_date(usd_full, drv_full, start=start)
            usd_idx = rebase_series_to_100(usd_full, start, base_date=base_day)
            drv_idx = rebase_series_to_100(drv_full, start, base_date=base_day)
            usd_idx = usd_idx.loc[(usd_idx.index >= start) & (usd_idx.index <= end)]
            drv_idx = drv_idx.loc[(drv_idx.index >= start) & (drv_idx.index <= end)]
            if base_day is not None:
                idx_title = f"지수화 비교 ({pd.Timestamp(base_day).date()} = 100)"
            else:
                idx_title = "지수화 비교 (분석 시작일 = 100)"
            st.plotly_chart(
                indexed_level_chart(
                    usd_idx,
                    drv_idx,
                    inst.display_name,
                    title=idx_title,
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                theme=None,
            )

            pick_multi = multi[multi["instrument_id"] == pick] if not multi.empty else pd.DataFrame()
            if pick_multi.empty and pick in transformed.columns:
                pick_multi = multi_window_correlations(
                    transformed,
                    drivers=[pick],
                    windows=list(ANALYSIS_WINDOWS),
                    as_of_date=transformed.index.max(),
                )
            m20 = m60 = m120 = np.nan
            for _, r in pick_multi.iterrows():
                if int(r["window"]) == 20:
                    m20 = r["rolling_correlation"]
                elif int(r["window"]) == 60:
                    m60 = r["rolling_correlation"]
                elif int(r["window"]) == 120:
                    m120 = r["rolling_correlation"]

            corr_s = corr_20[corr_20["instrument_id"] == pick].set_index("date")["rolling_correlation"].dropna()
            min_idx = corr_s.idxmin() if len(corr_s) else None
            max_idx = corr_s.idxmax() if len(corr_s) else None
            avg_rho = format_corr(float(corr_s.mean()) if len(corr_s) else np.nan)
            avg_abs_rho = format_corr(float(corr_s.abs().mean()) if len(corr_s) else np.nan)
            min_rho = format_corr(float(corr_s.min()) if len(corr_s) else np.nan)
            max_rho = format_corr(float(corr_s.max()) if len(corr_s) else np.nan)
            min_date = pd.Timestamp(min_idx).date() if min_idx is not None else "—"
            max_date = pd.Timestamp(max_idx).date() if max_idx is not None else "—"
            st.markdown(
                f"""
<div class="fx-detail-panel">
<div>[USDKRW vs {inst.display_name}]</div>
<ul>
<li>20D ρ: {format_corr(m20)}</li>
<li>60D ρ: {format_corr(m60)}</li>
<li>120D ρ: {format_corr(m120)}</li>
<li>평균 |ρ|: {avg_abs_rho}</li>
<li>평균 ρ: {avg_rho}</li>
<li>최소 ρ: {min_rho} ({min_date})</li>
<li>최대 ρ: {max_rho} ({max_date})</li>
</ul>
</div>
<br>
                """,
                unsafe_allow_html=True,
            )

        st.markdown('<div class="fx-section-title">역사적 충격일</div>', unsafe_allow_html=True)
        st.caption("최근 252거래일 변동성을 반영한 robust z-score와 자산별 절대하한을 함께 적용합니다.")
        shocks = detect_historical_shocks(
            frame["transformed_wide"],
            display_start=start,
            display_end=end,
            z_abs_min=controls["robust_z_min"],
        )
        st.caption(f"극단값 감지: {0 if shocks.empty else len(shocks)}개")
        if shocks.empty:
            st.caption("조건을 충족하는 충격일이 없습니다.")
        else:
            change_txt: list[str] = []
            floor_txt: list[str] = []
            for val, floor, unit in zip(
                shocks["value"], shocks["abs_threshold"], shocks["unit"]
            ):
                if unit == "log_return":
                    change_txt.append(f"{float(val) * 100:.2f}%")
                    floor_txt.append(f"{float(floor) * 100:.2f}%")
                else:
                    change_txt.append(f"{float(val):.2f}bp")
                    floor_txt.append(f"{float(floor):.2f}bp")
            show_df = pd.DataFrame(
                {
                    "날짜": shocks["date"],
                    "시장변수": shocks["display_name"],
                    "일간변화": change_txt,
                    "robust z-score": shocks["robust_z"].astype(float),
                    "절대하한": floor_txt,
                    "단위": shocks["unit"],
                }
            )
            st.dataframe(
                show_df,
                use_container_width=True,
                hide_index=True,
                height=TABLE_HEIGHT,
                column_config={
                    "일간변화": st.column_config.TextColumn("일간변화", alignment="right"),
                    "robust z-score": st.column_config.NumberColumn(
                        "robust z-score", format="%.2f"
                    ),
                    "절대하한": st.column_config.TextColumn("절대하한", alignment="right"),
                },
            )
            st.caption("")
            st.caption("")

        with st.expander("데이터 품질"):
            st.markdown("**변수별 데이터 품질**")
            st.caption("데이터 커버리지 확인을 위해 변수별 데이터 품질을 표시합니다.")
            meta_rows = []
            for iid, m in frame["meta"].items():
                meta_rows.append(
                    {
                        "시작일": m.get("first_date"),
                        "종료일": m.get("last_date"),
                        "시장변수": m.get("display_name", iid),
                        "관측수": m.get("obs_count"),
                        "결측률": m.get("missing_rate"),
                    }
                )
            meta_df = pd.DataFrame(meta_rows)
            if not meta_df.empty:
                st.dataframe(
                    meta_df.style.format(
                        {"관측수": "{:,.0f}", "결측률": "{:.2%}"},
                        na_rep="—",
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

    except ValueError as exc:
        logger.exception("Analysis error")
        st.error(_safe_message(exc))
    except Exception as exc:
        logger.exception("Unexpected dashboard error")
        st.error(f"대시보드 처리 중 오류가 발생했습니다: {_safe_message(exc)}")


if __name__ == "__main__":
    main()
