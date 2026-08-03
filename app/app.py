"""USDKRW Driver Monitor — Streamlit dashboard (static settled closes only)."""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from html import escape
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
from src.analytics import (
    DRIVER_MIXED,
    DRIVER_NONE,
    assign_daily_drivers,
    build_driver_ranking,
    calculate_rolling_correlations,
    compress_driver_regimes,
    compute_driver_scores,
    current_driver_snapshot,
    detect_abnormal_returns,
    multi_window_correlations,
)
from src.database import get_db_status, load_market_data
from src.ingestion import IngestionError, ingest_excel
from src.transformation import build_analysis_frame
from src.utils import (
    DEFAULT_DB_PATH,
    DEFAULT_RAW_DIR,
    db_mtime_key,
    format_corr,
    format_fx,
    format_pct,
    setup_logging,
)
from src.theme import load_css_vars, read_styles_css
from src.charts import (
    DISPLAY_MODE_LABELS,
    PLOTLY_CONFIG,
    build_rank_line,
    correlation_heatmap,
    driver_timeline_chart,
    dual_corr_detail_chart,
    rolling_correlation_chart,
    series_line_chart,
)

logger = logging.getLogger(__name__)
setup_logging(False)

st.set_page_config(
    page_title="USDKRW Driver Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)


_CSS_VARS: dict[str, str] = {}


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
    st.title("USDKRW Driver Monitor")
    st.caption("USDKRW와 주요 시장변수 간 롤링 상관관계 및 시점별 주도 변수 변화를 모니터링합니다.")
    st.info(
        "SQLite에 적재된 데이터가 없습니다.\n\n"
        "1. 인포맥스에서 Excel을 추출합니다.\n"
        "2. `data/raw/`에 저장합니다.\n"
        "3. 아래 명령으로 적재합니다.\n\n"
        '`python scripts/ingest_excel.py --file "data/raw/infomax_raw.xlsx"`\n\n'
        "또는 사이드바 **데이터 업데이트**에서 Excel을 업로드한 뒤 "
        "**Excel을 SQLite에 적재**를 누르세요.\n\n"
        "본 대시보드는 실시간 데이터가 아닌 **전일 확정 종가**만 사용합니다."
    )


def sidebar_controls(status: dict) -> dict:
    st.sidebar.header("분석 설정")

    if st.sidebar.button("⟲ 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    period = st.sidebar.selectbox(
        "분석 기간",
        ["최근 1년", "최근 3년", "최근 5년", "전체", "사용자 설정"],
        index=0,
    )
    custom_start = custom_end = None
    if period == "사용자 설정":
        c1, c2 = st.sidebar.columns(2)
        custom_start = c1.date_input("시작일", value=date.today() - timedelta(days=365))
        custom_end = c2.date_input("종료일", value=date.today())

    window_choice = st.sidebar.selectbox(
        "롤링 윈도우",
        ["20일", "60일", "120일", "사용자 설정"],
        index=0,
    )
    if window_choice == "사용자 설정":
        window = st.sidebar.number_input("윈도우(거래일)", min_value=10, max_value=252, value=20, step=1)
    else:
        window = int(window_choice.replace("일", ""))

    display_label = st.sidebar.selectbox(
        "표시 변수 개수",
        list(DISPLAY_MODE_LABELS.values()),
        index=0,
    )
    display_mode = {v: k for k, v in DISPLAY_MODE_LABELS.items()}[display_label]

    min_abs = st.sidebar.slider("최소 절대 상관계수 |ρ|", 0.0, 1.0, 0.30, 0.05)

    drivers = get_driver_instruments()
    all_options = {d.display_name: d.instrument_id for d in drivers}
    default_names = [
        INSTRUMENT_BY_ID[i].display_name
        for i in DEFAULT_DRIVER_IDS
        if i in INSTRUMENT_BY_ID and INSTRUMENT_BY_ID[i].active
    ]
    all_names = list(all_options.keys())

    with st.sidebar.expander("변수 설정", expanded=False):
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
    with st.sidebar.expander("엑셀 업로드", expanded=False):
        uploaded = st.file_uploader("Infomax Excel", type=["xlsx", "xls"])
        st.caption(f"DB 경로: {DEFAULT_DB_PATH}")
        last_ing = status.get("last_ingestion") or {}
        st.caption(f"최근 파일: {Path(str(last_ing.get('source_file', '—'))).name}")
        st.caption(f"최근 적재: {last_ing.get('completed_at') or last_ing.get('started_at') or '—'}")
        if uploaded is not None and st.button("Excel을 SQLite에 적재", use_container_width=True):
            try:
                DEFAULT_RAW_DIR.mkdir(parents=True, exist_ok=True)
                ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
                dest = DEFAULT_RAW_DIR / f"upload_{ts}_{uploaded.name}"
                dest.write_bytes(uploaded.getvalue())
                result = ingest_excel(dest, db_path=DEFAULT_DB_PATH, replace=False)
                st.cache_data.clear()
                st.success(
                    f"적재 완료: 신규 {result['inserted_rows']} / 갱신 {result['updated_rows']}"
                )
                if result["missing_sheets"]:
                    st.warning("누락 시트: " + ", ".join(result["missing_sheets"]))
                st.rerun()
            except IngestionError as exc:
                logger.exception("Upload ingest failed")
                st.error(_safe_message(exc))
            except Exception as exc:
                logger.exception("Upload ingest failed")
                st.error(f"적재 중 오류가 발생했습니다: {_safe_message(exc)}")

    selected_ids = [
        all_options[n]
        for n in st.session_state.get("var_multiselect", default_names)
        if n in all_options
    ]

    return {
        "period": period,
        "custom_start": custom_start,
        "custom_end": custom_end,
        "window": int(window),
        "display_mode": display_mode,
        "display_label": display_label,
        "selected_ids": selected_ids,
        "min_abs": float(min_abs),
    }


def resolve_date_range(
    period: str,
    as_of: date,
    custom_start: date | None,
    custom_end: date | None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp(as_of)
    if period == "최근 1년":
        start = end - pd.DateOffset(years=1)
    elif period == "최근 3년":
        start = end - pd.DateOffset(years=3)
    elif period == "최근 5년":
        start = end - pd.DateOffset(years=5)
    elif period == "사용자 설정" and custom_start and custom_end:
        start = pd.Timestamp(custom_start)
        end = min(pd.Timestamp(custom_end), end)
    else:
        start = pd.Timestamp("1970-01-01")
    return start.normalize(), end.normalize()


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


def render_meta_banner(as_of_str: str, controls: dict) -> None:
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
              <div class="fx-meta-value">{controls['period']}</div>
            </div>
            <div class="fx-meta-item">
              <div class="fx-meta-label">롤링 윈도우</div>
              <div class="fx-meta-value">{controls['window']}일</div>
            </div>
            <div class="fx-meta-item">
              <div class="fx-meta-label">표시 변수 개수</div>
              <div class="fx-meta-value">{controls['display_label']}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def corr_color(val: float) -> str:
    muted = _CSS_VARS.get("fx-text-muted")
    pos = _CSS_VARS.get("fx-corr-pos")
    neg = _CSS_VARS.get("fx-corr-neg")
    if pd.isna(val):
        return f"color:{muted}"
    if val > 0.05:
        return f"color:{pos}"
    if val < -0.05:
        return f"color:{neg}"
    return f"color:{muted}"


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


def filter_ids_by_min_abs(corr_long: pd.DataFrame, instrument_ids: list[str], min_abs: float) -> list[str]:
    if corr_long.empty:
        return []
    latest = corr_long["date"].max()
    snap = corr_long[
        (corr_long["date"] == latest)
        & (corr_long["instrument_id"].isin(instrument_ids))
        & (corr_long["abs_correlation"] >= min_abs)
    ]
    return list(snap.sort_values("abs_correlation", ascending=False)["instrument_id"])


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

    controls = sidebar_controls(status)

    if not status.get("db_exists") or not status.get("market_data_exists") or not status.get("usdkrw_latest_date"):
        render_empty_state()
        return

    st.title("USDKRW Driver Monitor")
    st.caption("USDKRW와 주요 시장변수 간 롤링 상관관계 및 시점별 주도 변수 변화를 모니터링합니다.")

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

        render_meta_banner(as_of_str, controls)

        start, end = resolve_date_range(
            controls["period"],
            as_of.date(),
            controls["custom_start"],
            controls["custom_end"],
        )

        transformed = frame["transformed_wide"]
        raw_aligned = frame["raw_aligned_wide"]
        transformed = transformed.loc[(transformed.index >= start) & (transformed.index <= end)]
        raw_aligned = raw_aligned.loc[(raw_aligned.index >= start) & (raw_aligned.index <= end)]

        if len(transformed) < controls["window"]:
            st.warning(
                f"선택 기간({len(transformed)}거래일)이 롤링 윈도우({controls['window']}일)보다 짧습니다. "
                "기간을 늘리거나 윈도우를 줄이세요."
            )
            return

        selected_drivers = [i for i in controls["selected_ids"] if i in transformed.columns]
        if not selected_drivers:
            st.warning("선택한 변수의 유효 데이터가 부족합니다.")
            return

        corr_long = calculate_rolling_correlations(
            transformed,
            target=TARGET_ID,
            drivers=selected_drivers,
            window=controls["window"],
        )
        scored = compute_driver_scores(corr_long)
        daily = assign_daily_drivers(scored)
        regimes = compress_driver_regimes(daily)
        snap = current_driver_snapshot(daily, scored)

        driver_id = snap.get("driver_id")
        chart_corr = corr_long
        chart_selected = list(selected_drivers)
        if driver_id and driver_id not in (DRIVER_NONE, DRIVER_MIXED):
            if driver_id in transformed.columns and driver_id not in chart_selected:
                chart_selected = chart_selected + [driver_id]
                chart_corr = calculate_rolling_correlations(
                    transformed,
                    target=TARGET_ID,
                    drivers=chart_selected,
                    window=controls["window"],
                )

        ranking_full = build_driver_ranking(scored, as_of_date=transformed.index.max())
        display_ids = filter_ids_by_min_abs(corr_long, selected_drivers, controls["min_abs"])
        ranking = ranking_full[ranking_full["instrument_id"].isin(display_ids)].copy() if not ranking_full.empty else ranking_full
        if not ranking.empty:
            ranking["rank"] = range(1, len(ranking) + 1)

        heatmap_drivers = list(selected_drivers)
        if driver_id and driver_id not in (DRIVER_NONE, DRIVER_MIXED) and driver_id in transformed.columns:
            if driver_id not in heatmap_drivers:
                heatmap_drivers = heatmap_drivers + [driver_id]

        multi = multi_window_correlations(
            transformed,
            drivers=heatmap_drivers,
            windows=[20, 60, 120],
            as_of_date=transformed.index.max(),
        )

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
            kpi_card("주도 변수", snap["driver_name"])
        with c2:
            kpi_card("롤링 상관계수", rho_txt)
        with c3:
            kpi_card("USDKRW (전일)", format_fx(latest_fx))
        with c4:
            kpi_card("USDKRW (변화)", chg_txt)
        
        with st.expander("분석 기준 보기", expanded=False):
            st.markdown(
                """
- Pearson 롤링 상관계수를 사용합니다.
- 절대 상관계수 최소 기준은 차트, 랭킹, 히트맵, 상세 필터에 적용됩니다.
- 전일 확정 종가만 사용하며 실시간 현재가는 포함하지 않습니다.
- 주도 변수는 선택 기간 내 USDKRW와 가장 안정적으로 동행한 변수이며, 인과관계를 의미하지 않습니다.
                """
            )

        # --- Rolling chart ---
        zoom_years = None
        if controls["period"] in ("최근 3년", "최근 5년", "전체"):
            zoom_years = 1.0

        fig, chart_info = rolling_correlation_chart(
            chart_corr,
            selected_instruments=selected_drivers,
            current_driver_id=driver_id if driver_id not in (DRIVER_NONE, DRIVER_MIXED) else None,
            display_mode=controls["display_mode"],
            min_abs_correlation=controls["min_abs"],
            window=controls["window"],
            initial_zoom_years=zoom_years,
        )
        rank_line = build_rank_line(chart_corr, chart_info.get("show_ids") or [])

        st.markdown('<div class="fx-section-title">롤링 상관계수</div>', unsafe_allow_html=True)
        if rank_line:
            st.caption(rank_line)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, theme=None)

        # --- Ranking ---
        st.markdown('<div class="fx-section-title">주도 변수 랭킹</div>', unsafe_allow_html=True)
        st.caption(
            f"전체 시장변수 {len(selected_drivers)}개 중 최소 상관계수(|ρ| ≥ {controls['min_abs']:.2f})를 충족한 시장변수들을 표시합니다."
        )
        if ranking.empty:
            st.info("최소 상관계수 기준을 충족하는 랭킹 변수가 없습니다.")
        else:
            show = ranking.reset_index(drop=True).copy()
            show = show.rename(
                columns={
                    "rank": "순위",
                    "display_name": "시장변수",
                    "category": "카테고리",
                    "rolling_correlation": "상관계수",
                    "abs_correlation": "절대 상관계수",
                    "driver_score": "안정화 점수",
                    "change_vs_5d": "5일 전 대비 ρ 변화",
                    "observation_count": "유효 관측치",
                }
            )
            fmt_cols = ["상관계수", "절대 상관계수", "안정화 점수", "5일 전 대비 ρ 변화"]
            col_order = [
                "순위",
                "시장변수",
                "카테고리",
                "상관계수",
                "절대 상관계수",
                "안정화 점수",
                "5일 전 대비 ρ 변화",
                "유효 관측치",
            ]
            driver_rows = set(
                show.index[show["instrument_id"] == driver_id].tolist()
            ) if driver_id else set()

            def _style_corr(col: pd.Series) -> list[str]:
                return [corr_color(v) for v in col]

            def _row_style(row: pd.Series) -> list[str]:
                return driver_row_style(row.name in driver_rows, len(row))

            visible = show[col_order]
            styler = (
                visible.style.format({c: "{:.2f}" for c in fmt_cols}, na_rep="—")
                .apply(_style_corr, subset=["상관계수"])
                .apply(_row_style, axis=1)
            )
            st.dataframe(styler, use_container_width=True, hide_index=True)

        # --- Heatmap ---
        st.markdown('<div class="fx-section-title">상관계수 히트맵</div>', unsafe_allow_html=True)
        st.caption(
            "히트맵 색상은 상관계수의 부호와 크기를 나타내며 호재·악재를 의미하지 않습니다."
        )
        if multi.empty:
            st.info("히트맵을 그릴 변수가 없습니다.")
        else:
            st.plotly_chart(
                correlation_heatmap(
                    multi,
                    current_driver_id=driver_id if driver_id not in (DRIVER_NONE, DRIVER_MIXED) else None,
                    min_abs_correlation=controls["min_abs"],
                ),
                use_container_width=True,
                config=PLOTLY_CONFIG,
                theme=None,
            )

        # --- Timeline ---
        st.markdown('<div class="fx-section-title">시기별 주도 변수</div>', unsafe_allow_html=True)
        st.caption("타임라인은 주도 변수 판정 결과 전체입니다. |ρ|&lt;0.30 구간은 흐리게 표시됩니다.")
        st.plotly_chart(
            driver_timeline_chart(regimes, low_confidence_threshold=0.30),
            use_container_width=True,
            config=PLOTLY_CONFIG,
            theme=None,
        )
        if not regimes.empty:
            reg_show = regimes.copy()
            reg_show["낮은 신뢰도"] = reg_show.apply(
                lambda r: (
                    "예"
                    if (
                        pd.notna(r["average_abs_correlation"])
                        and r["average_abs_correlation"] < 0.30
                        and r["driver_id"] not in (DRIVER_NONE, DRIVER_MIXED)
                    )
                    or r["driver_id"] in (DRIVER_NONE, DRIVER_MIXED)
                    else ""
                ),
                axis=1,
            )
            reg_show["start_date"] = pd.to_datetime(reg_show["start_date"]).dt.date
            reg_show["end_date"] = pd.to_datetime(reg_show["end_date"]).dt.date
            reg_show = reg_show.rename(
                columns={
                    "start_date": "시작일",
                    "end_date": "종료일",
                    "driver_name": "주도 변수",
                    "category": "카테고리",
                    "trading_days": "지속 거래일",
                    "average_signed_correlation": "평균 ρ",
                    "average_abs_correlation": "평균 |ρ|",
                    "max_abs_correlation": "최대 |ρ|",
                }
            )
            cols = [
                "시작일",
                "종료일",
                "주도 변수",
                "카테고리",
                "지속 거래일",
                "평균 ρ",
                "평균 |ρ|",
                "최대 |ρ|",
                "낮은 신뢰도",
            ]
            st.dataframe(
                reg_show[cols].style.format(
                    {
                        "평균 ρ": "{:.2f}",
                        "평균 |ρ|": "{:.2f}",
                        "최대 |ρ|": "{:.2f}",
                    },
                    na_rep="—",
                ),
                use_container_width=True,
                hide_index=True,
            )

        # --- Detail ---
        st.markdown('<div class="fx-section-title">변수별 상세 분석</div>', unsafe_allow_html=True)
        st.caption("USDKRW 원본값, 선택 변수 원본값, 롤링 상관계수, 변환값을 함께 표시합니다.")
        detail_ids = list(display_ids)
        if driver_id and driver_id not in (DRIVER_NONE, DRIVER_MIXED) and driver_id in transformed.columns:
            if driver_id not in detail_ids:
                detail_ids = [driver_id] + detail_ids
        detail_map = {
            INSTRUMENT_BY_ID[i].display_name: i
            for i in detail_ids
            if i in INSTRUMENT_BY_ID
        }
        if not detail_map:
            st.info("표시 기준을 충족하는 상세 변수가 없습니다. 최소 |ρ| 기준을 낮춰 보세요.")
        else:
            pick_name = st.selectbox(
                "상세 변수",
                list(detail_map.keys()),
                label_visibility="collapsed",
            )
            pick = detail_map[pick_name]
            inst = INSTRUMENT_BY_ID[pick]

            src_corr = chart_corr if pick in chart_corr["instrument_id"].values else corr_long
            pick_corr = src_corr[src_corr["instrument_id"] == pick].set_index("date")["rolling_correlation"]

            y_title = {
                "log_return": "log return",
                "diff_bp": "bp change",
                "level": "flow (원자료 단위)",
            }.get(inst.transformation, "value")
            detail_color = _CSS_VARS.get("fx-detail-line", "#3FB950")

            r1c1, r1c2 = st.columns(2)
            with r1c1:
                if TARGET_ID in raw_aligned.columns:
                    st.plotly_chart(
                        series_line_chart(
                            raw_aligned[TARGET_ID],
                            title="USDKRW",
                            y_title="level",
                            color=detail_color,
                        ),
                        use_container_width=True,
                        config=PLOTLY_CONFIG,
                        theme=None,
                    )
            with r1c2:
                if pick in raw_aligned.columns:
                    st.plotly_chart(
                        series_line_chart(
                            raw_aligned[pick],
                            title=inst.display_name,
                            y_title="level",
                            color=detail_color,
                        ),
                        use_container_width=True,
                        config=PLOTLY_CONFIG,
                        theme=None,
                    )

            r2c1, r2c2 = st.columns(2)
            with r2c1:
                st.plotly_chart(
                    dual_corr_detail_chart(
                        pick_corr, inst.display_name, controls["window"], detail_color
                    ),
                    use_container_width=True,
                    config=PLOTLY_CONFIG,
                    theme=None,
                )
            with r2c2:
                if pick in transformed.columns:
                    st.plotly_chart(
                        series_line_chart(
                            transformed[pick],
                            title=f"{inst.display_name} 변환값 ({inst.transformation})",
                            y_title=y_title,
                            color=detail_color,
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
                    windows=[20, 60, 120],
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

            series_t = transformed[pick] if pick in transformed.columns else pd.Series(dtype=float)
            valid = series_t.dropna()
            meta = frame["meta"].get(pick, {})
            corr_s = pick_corr.dropna()
            min_idx = corr_s.idxmin() if len(corr_s) else None
            max_idx = corr_s.idxmax() if len(corr_s) else None

            note_line = f"<li>{escape(inst.note)}</li>" if inst.note else ""
            min_rho = format_corr(float(corr_s.min()) if len(corr_s) else np.nan)
            max_rho = format_corr(float(corr_s.max()) if len(corr_s) else np.nan)
            min_date = pd.Timestamp(min_idx).date() if min_idx is not None else "—"
            max_date = pd.Timestamp(max_idx).date() if max_idx is not None else "—"
            st.markdown(
                f"""
<div class="fx-detail-panel">
<ul>
<li>최신 20D ρ: <strong>{format_corr(m20)}</strong></li>
<li>최신 60D ρ: <strong>{format_corr(m60)}</strong></li>
<li>최신 120D ρ: <strong>{format_corr(m120)}</strong></li>
<li>전체 기간 유효 관측치: <strong>{len(valid)}</strong></li>
<li>결측률: <strong>{format_pct(meta.get('missing_rate'))}</strong></li>
<li>최소 ρ: <strong>{min_rho}</strong> ({min_date})</li>
<li>최대 ρ: <strong>{max_rho}</strong> ({max_date})</li>
{note_line}
</ul>
</div>
                """,
                unsafe_allow_html=True,
            )

        # --- Data quality ---
        with st.expander("데이터 품질"):
            meta_rows = []
            for iid, m in frame["meta"].items():
                meta_rows.append(
                    {
                        "종목": m.get("display_name", iid),
                        "instrument_id": iid,
                        "최초 일자": m.get("first_date"),
                        "최신 일자": m.get("last_date"),
                        "관측치 수": m.get("obs_count"),
                        "결측률": m.get("missing_rate"),
                    }
                )
            meta_df = pd.DataFrame(meta_rows)
            if not meta_df.empty:
                st.dataframe(
                    meta_df.style.format({"결측률": "{:.1%}"}, na_rep="—"),
                    use_container_width=True,
                    hide_index=True,
                )
            last_ing = status.get("last_ingestion") or {}
            st.write(f"최근 적재 파일: `{last_ing.get('source_file', '—')}`")
            st.write(f"적재 상태: {last_ing.get('status', '—')}")

            abnormal = detect_abnormal_returns(transformed, raw_aligned)
            st.markdown("**비정상 수익률·금리 변화 후보**")
            if abnormal.empty:
                st.caption("기준을 초과하는 관측이 없습니다.")
            else:
                st.dataframe(abnormal, use_container_width=True, hide_index=True)

    except ValueError as exc:
        logger.exception("Analysis error")
        st.error(_safe_message(exc))
    except Exception as exc:
        logger.exception("Unexpected dashboard error")
        st.error(f"대시보드 처리 중 오류가 발생했습니다: {_safe_message(exc)}")


if __name__ == "__main__":
    main()
