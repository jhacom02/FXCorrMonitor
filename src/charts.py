"""Plotly chart builders for FXCorrMonitor."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config.instruments import INSTRUMENT_BY_ID, SPECIAL_COLORS, color_for
from config.thresholds import CORR_GUIDE_SOFT, CORR_GUIDE_STRONG, sig_abs
from src.theme import load_css_vars

_CSS = load_css_vars()


def _tok(name: str) -> str:
    if name not in _CSS:
        raise KeyError(f"missing CSS token --{name}")
    return _CSS[name]


CHART_LAYOUT = dict(
    paper_bgcolor=_tok("fx-chart-paper"),
    plot_bgcolor=_tok("fx-chart-plot"),
    font=dict(color=_tok("fx-chart-font"), size=12),
    hoverlabel=dict(
        bgcolor=_tok("fx-chart-plot"),
        bordercolor=_tok("fx-chart-grid"),
        font=dict(color=_tok("fx-chart-font"), size=12),
        namelength=-1,
    ),
)

INSET_LEGEND = dict(
    orientation="h",
    yanchor="top",
    y=0.98,
    xanchor="right",
    x=1,
    font=dict(size=11),
    bgcolor=_tok("fx-chart-hover-bg"),
    borderwidth=0,
)

DETAIL_INSET_LEGEND = {
    **INSET_LEGEND,
    "x": 0.93,
}

CHART_SUBTITLE = dict(font=dict(size=15), x=0.5, xanchor="center")

DISPLAY_MODE_TOP3 = "top_3"
DISPLAY_MODE_TOP5 = "top_5"
DISPLAY_MODE_TOP7 = "top_7"
DISPLAY_MODE_ALL = "all"

DISPLAY_MODE_LABELS = {
    DISPLAY_MODE_TOP3: "Top 3",
    DISPLAY_MODE_TOP5: "Top 5",
    DISPLAY_MODE_TOP7: "Top 7",
    DISPLAY_MODE_ALL: "전체",
}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "displayModeBar": "hover",
    "modeBarButtonsToRemove": [
        "select2d",
        "lasso2d",
        "autoScale2d",
        "toggleSpikelines",
    ],
}

HEATMAP_COLORSCALE = [
    [0.0, _tok("fx-heatmap-n1")],
    [0.25, _tok("fx-heatmap-n05")],
    [0.5, _tok("fx-heatmap-0")],
    [0.75, _tok("fx-heatmap-p05")],
    [1.0, _tok("fx-heatmap-p1")],
]


def _empty_message_fig(message: str, height: int = 420) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(color=_tok("fx-chart-muted"), size=14),
    )
    fig.update_layout(
        **CHART_LAYOUT,
        height=height,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def _latest_abs_ranking(corr_long: pd.DataFrame, instrument_ids: list[str]) -> pd.DataFrame:
    if corr_long.empty or not instrument_ids:
        return pd.DataFrame(columns=["instrument_id", "display_name", "abs_correlation", "rolling_correlation"])
    df = corr_long[corr_long["instrument_id"].isin(instrument_ids)].copy()
    if df.empty:
        return pd.DataFrame(columns=["instrument_id", "display_name", "abs_correlation", "rolling_correlation"])
    as_of = df["date"].max()
    latest = df[df["date"] == as_of].dropna(subset=["abs_correlation"])
    return latest.sort_values("abs_correlation", ascending=False).reset_index(drop=True)


def resolve_chart_instruments(
    corr_long: pd.DataFrame,
    selected_instruments: list[str],
    current_driver_id: str | None,
    display_mode: str = DISPLAY_MODE_TOP5,
    min_abs_correlation: float = 0.0,
) -> dict[str, Any]:
    special = {"NONE", "MIXED", None, ""}
    driver_id = current_driver_id if current_driver_id not in special else None

    selected = [i for i in selected_instruments if i]
    ranking = _latest_abs_ranking(corr_long, selected)
    passed = ranking[ranking["abs_correlation"] >= float(min_abs_correlation)].copy()

    n_cap = None
    if display_mode == DISPLAY_MODE_TOP3:
        n_cap = 3
    elif display_mode == DISPLAY_MODE_TOP5:
        n_cap = 5
    elif display_mode == DISPLAY_MODE_TOP7:
        n_cap = 7

    if display_mode == DISPLAY_MODE_ALL:
        show_ids = list(passed["instrument_id"]) if not passed.empty else []
    else:
        show_ids = list(passed["instrument_id"].head(n_cap)) if not passed.empty else []

    driver_forced = False
    driver_outside_selection = False
    if driver_id:
        if driver_id not in selected:
            driver_outside_selection = True
        if driver_id not in show_ids:
            show_ids = [driver_id] + [i for i in show_ids if i != driver_id]
            driver_forced = True
        else:
            show_ids = [driver_id] + [i for i in show_ids if i != driver_id]

    if driver_id and display_mode != DISPLAY_MODE_ALL:
        rest = [i for i in show_ids if i != driver_id]
        ordered_rest = [i for i in passed["instrument_id"] if i in rest]
        for i in rest:
            if i not in ordered_rest:
                ordered_rest.append(i)
        show_ids = ([driver_id] if driver_id in show_ids else []) + ordered_rest
    elif display_mode == DISPLAY_MODE_ALL and driver_id and driver_id in show_ids:
        show_ids = [driver_id] + [i for i in show_ids if i != driver_id]

    mode_label = DISPLAY_MODE_LABELS.get(display_mode, display_mode)
    actual_n = len([i for i in show_ids if i != driver_id]) if driver_id else len(show_ids)
    if display_mode != DISPLAY_MODE_ALL and n_cap is not None:
        display_count_label = f"상위 {min(len(show_ids), n_cap)}개" if len(show_ids) < n_cap else mode_label
        if len(show_ids) < n_cap:
            display_count_label = f"상위 {len(show_ids)}개"
        else:
            display_count_label = mode_label
    else:
        display_count_label = mode_label if display_mode != DISPLAY_MODE_ALL else "전체"

    return {
        "show_ids": show_ids,
        "passed_ids": list(passed["instrument_id"]) if not passed.empty else [],
        "top_n_ids": [i for i in show_ids if i != driver_id] if driver_id else list(show_ids),
        "driver_id": driver_id,
        "driver_forced": driver_forced,
        "driver_outside_selection": driver_outside_selection,
        "display_count_label": display_count_label,
        "n_cap": n_cap,
        "actual_count": len(show_ids),
    }


def build_rank_line(
    corr_long: pd.DataFrame,
    show_ids: list[str],
) -> str:
    if not show_ids or corr_long.empty:
        return ""
    ranking = _latest_abs_ranking(corr_long, show_ids)
    if ranking.empty:
        return ""
    order = {iid: i for i, iid in enumerate(show_ids)}
    ranking = ranking.copy()
    ranking["_ord"] = ranking["instrument_id"].map(lambda x: order.get(x, 999))
    ranking = ranking.sort_values("_ord")
    circles = "①②③④⑤⑥⑦⑧⑨⑩"
    parts = []
    for i, row in enumerate(ranking.itertuples()):
        mark = circles[i] if i < len(circles) else f"{i + 1}."
        rho = float(row.rolling_correlation)
        parts.append(f"{mark} {row.display_name} ({rho:.2f})")
    return f"오늘자 주도변수: " + ",  ".join(parts)


def rolling_correlation_chart(
    correlation_df: pd.DataFrame,
    selected_instruments: list[str],
    current_driver_id: str | None,
    display_mode: str = DISPLAY_MODE_TOP5,
    min_abs_correlation: float = 0.0,
    color_map: dict[str, str] | None = None,
    window: int = 20,
    title: str | None = None,
    height: int = 520,
    initial_zoom_years: float | None = None,
) -> tuple[go.Figure, dict[str, Any]]:
    empty_info = {
        "show_ids": [],
        "passed_ids": [],
        "top_n_ids": [],
        "driver_id": None,
        "driver_forced": False,
        "driver_outside_selection": False,
        "display_count_label": DISPLAY_MODE_LABELS.get(display_mode, display_mode),
        "actual_count": 0,
    }

    if (
        correlation_df is None
        or correlation_df.empty
        or correlation_df["rolling_correlation"].notna().sum() == 0
    ):
        return _empty_message_fig("표시할 롤링 상관계수가 없습니다.", height=height), empty_info

    df = correlation_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    info = resolve_chart_instruments(
        df,
        selected_instruments=selected_instruments,
        current_driver_id=current_driver_id,
        display_mode=display_mode,
        min_abs_correlation=min_abs_correlation,
    )
    show_ids = info["show_ids"]
    if not show_ids:
        return (
            _empty_message_fig(
                f"최소 상관계수(|ρ| ≥ {min_abs_correlation:.2f})를 충족하는 시장변수가 없습니다.",
                height=height,
            ),
            info,
        )

    def _color(iid: str) -> str:
        if color_map and iid in color_map:
            return color_map[iid]
        return color_for(iid)

    fig = go.Figure()
    driver_id = info["driver_id"]
    is_all = display_mode == DISPLAY_MODE_ALL
    driver_latest_point: tuple[pd.Timestamp, float, str, str] | None = None

    for iid in show_ids:
        grp = df[df["instrument_id"] == iid].sort_values("date")
        if grp.empty:
            continue
        is_driver = driver_id is not None and iid == driver_id
        if is_driver:
            width, opacity = 3.2, 1.0
        elif is_all:
            width, opacity = 1.3, 0.65
        else:
            width, opacity = 1.6, 0.70

        name = str(grp["display_name"].iloc[0])

        color = _color(str(iid))
        y_vals = grp["rolling_correlation"]
        hover_vals = ["—" if pd.isna(v) else f"{float(v):.2f}" for v in y_vals]
        fig.add_trace(
            go.Scatter(
                x=grp["date"],
                y=y_vals,
                mode="lines",
                name=name,
                line=dict(color=color, width=width),
                opacity=opacity,
                customdata=hover_vals,
                hovertemplate="%{fullData.name}: %{customdata}<extra></extra>",
            )
        )

        if is_driver:
            valid = grp.dropna(subset=["rolling_correlation"])
            if not valid.empty:
                last = valid.iloc[-1]
                driver_latest_point = (
                    pd.Timestamp(last["date"]),
                    float(last["rolling_correlation"]),
                    str(last["display_name"]),
                    color,
                )

    if driver_latest_point is not None:
        dt, val, dname, dcolor = driver_latest_point
        sign = "+" if val > 0 else ""
        fig.add_trace(
            go.Scatter(
                x=[dt],
                y=[val],
                mode="markers+text",
                text=[f"{dname}  {sign}{val:.2f}"],
                textposition="middle right",
                textfont=dict(color=dcolor, size=12),
                marker=dict(size=9, color=dcolor, line=dict(width=1, color=_tok("fx-chart-font"))),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    for y0, y1 in [
        (CORR_GUIDE_STRONG, 1.0),
        (-1.0, -CORR_GUIDE_STRONG),
    ]:
        fig.add_hrect(
            y0=y0,
            y1=y1,
            fillcolor=_tok("fx-chart-band"),
            line_width=0,
            layer="below",
        )

    grid = _tok("fx-chart-grid")
    for y in (0, CORR_GUIDE_SOFT, -CORR_GUIDE_SOFT, CORR_GUIDE_STRONG, -CORR_GUIDE_STRONG):
        if y == 0:
            fig.add_hline(y=y, line_dash="solid", line_color=grid, line_width=1.2)
        elif abs(y) == CORR_GUIDE_STRONG:
            fig.add_hline(
                y=y,
                line_dash="dot",
                line_color=_tok("fx-chart-hline-strong"),
                line_width=1.4,
            )
        else:
            fig.add_hline(
                y=y,
                line_dash="dot",
                line_color=_tok("fx-chart-hline-soft"),
                line_width=1,
            )

    margin = dict(l=40, r=40, t=20, b=40)

    xaxis: dict[str, Any] = dict(
        title="",
        gridcolor=grid,
        tickformat="%Y-%m",
        hoverformat="%Y-%m-%d",
        rangeslider=dict(visible=False),
    )
    if initial_zoom_years and initial_zoom_years > 0:
        x_max = df["date"].max()
        x_min_data = df["date"].min()
        zoom_start = x_max - pd.DateOffset(years=initial_zoom_years)
        if zoom_start > x_min_data:
            xaxis["range"] = [zoom_start, x_max]

    fig.update_layout(
        **CHART_LAYOUT,
        margin=margin,
        legend=INSET_LEGEND,
        title=None,
        height=height,
        yaxis=dict(range=[-1.05, 1.05], title="Rolling correlation", gridcolor=grid),
        xaxis=xaxis,
        hovermode="x unified",
    )
    return fig, info


def correlation_heatmap(
    multi_corr: pd.DataFrame,
    height: int = 480,
    current_driver_id: str | None = None,
    desaturate_factor: float = 0.6,
) -> go.Figure:
    if multi_corr is None or multi_corr.empty:
        return _empty_message_fig("히트맵을 그릴 상관계수가 없습니다.", height=height)

    df = multi_corr.copy()
    df["window_label"] = df["window"].map(lambda w: f"{int(w)}D")

    if "instrument_id" not in df.columns:
        name_to_id = {v.display_name: k for k, v in INSTRUMENT_BY_ID.items()}
        df["instrument_id"] = df["display_name"].map(name_to_id)

    pivot = df.pivot_table(
        index="instrument_id",
        columns="window_label",
        values="rolling_correlation",
        aggfunc="last",
    )
    cols = [c for c in ["5D", "20D", "60D", "120D"] if c in pivot.columns]
    pivot = pivot.reindex(columns=cols)

    if "20D" in pivot.columns:
        pivot = pivot.assign(_abs20=pivot["20D"].abs()).sort_values(
            "_abs20", ascending=False, na_position="last"
        ).drop(columns=["_abs20"])
    else:
        pivot = pivot.sort_index()

    display_names: list[str] = []
    y_labels: list[str] = []
    for iid in pivot.index:
        inst = INSTRUMENT_BY_ID.get(str(iid))
        name = inst.display_name if inst else str(iid)
        display_names.append(name)
        y_labels.append(name)

    floors = {
        5: sig_abs(5),
        20: sig_abs(20),
        60: sig_abs(60),
        120: sig_abs(120),
    }
    col_floors = [
        float(floors.get(int(c.replace("D", "")), 0.0)) for c in cols
    ]

    z = np.asarray(pivot.values, dtype=float)
    display_z = z.copy()
    finite = np.isfinite(z)
    low_mask = np.zeros_like(z, dtype=bool)
    for j, floor in enumerate(col_floors):
        low_mask[:, j] = finite[:, j] & (np.abs(z[:, j]) < floor)
    display_z[low_mask] = z[low_mask] * desaturate_factor

    n_rows, n_cols = z.shape
    text: list[list[str]] = []
    custom: list[list[list[str]]] = []
    display_list: list[list[float | None]] = []
    for i in range(n_rows):
        text_row: list[str] = []
        custom_row: list[list[str]] = []
        d_row: list[float | None] = []
        for j in range(n_cols):
            val = float(z[i, j]) if finite[i, j] else None
            dval = float(display_z[i, j]) if finite[i, j] else None
            d_row.append(dval)
            text_row.append("" if val is None else f"{val:.2f}")
            custom_row.append(
                [
                    display_names[i],
                    cols[j] if j < len(cols) else "",
                    "" if val is None else f"{val:.2f}",
                ]
            )
        text.append(text_row)
        custom.append(custom_row)
        display_list.append(d_row)

    fig = go.Figure(
        data=go.Heatmap(
            z=display_list,
            x=cols,
            y=y_labels,
            zmin=-1,
            zmax=1,
            zmid=0,
            colorscale=HEATMAP_COLORSCALE,
            xgap=1,
            ygap=1,
            text=text,
            texttemplate="%{text}",
            textfont=dict(color=_tok("fx-chart-font"), size=12),
            customdata=custom,
            hovertemplate=(
                "변수: %{customdata[0]}<br>"
                "기간: %{customdata[1]}<br>"
                "ρ: %{customdata[2]}<extra></extra>"
            ),
            hoverlabel=CHART_LAYOUT["hoverlabel"],
            colorbar=dict(
                title=dict(
                    text="ρ",
                    side="right",
                    font=dict(color=_tok("fx-chart-tick"), size=12),
                ),
                thickness=12,
                len=0.78,
                outlinewidth=0,
                tickfont=dict(color=_tok("fx-chart-tick"), size=11),
            ),
            showscale=True,
        )
    )
    hm_paper = _tok("fx-heatmap-paper")
    grid = _tok("fx-chart-grid")
    tick = _tok("fx-chart-tick")
    fig.update_layout(
        paper_bgcolor=hm_paper,
        plot_bgcolor=hm_paper,
        font=dict(color=_tok("fx-chart-font"), size=12),
        hoverlabel=CHART_LAYOUT["hoverlabel"],
        margin=dict(l=120, r=60, t=36, b=24),
        title=None,
        height=max(height, 36 * max(len(y_labels), 1) + 100),
        xaxis=dict(
            side="top",
            tickfont=dict(color=tick, size=12),
            ticks="",
            showgrid=False,
            linecolor=grid,
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(color=tick, size=12),
            ticks="",
            showgrid=False,
            linecolor=grid,
        ),
        template="plotly_dark",
    )
    return fig


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = _tok("fx-timeline-invalid").lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def driver_timeline_chart(
    regimes: pd.DataFrame,
    height: int = 170,
    low_confidence_threshold: float = 0.0,
    title: str | None = None,
    x_range: tuple[Any, Any] | list[Any] | None = None,
) -> go.Figure:
    if regimes is None or regimes.empty:
        return _empty_message_fig("주도변수 구간이 없습니다.", height=height)

    df = regimes.copy()
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["end_plot"] = df["end_date"] + pd.Timedelta(days=1)
    df["low_confidence"] = df["average_abs_correlation"].fillna(0) < low_confidence_threshold

    fig = go.Figure()
    none_fill = _hex_to_rgba(SPECIAL_COLORS.get("NONE", _tok("fx-color-NONE")), 0.85)
    mixed_fill = _hex_to_rgba(SPECIAL_COLORS.get("MIXED", _tok("fx-color-MIXED")), 0.85)
    for _, row in df.sort_values("start_date").iterrows():
        did = str(row["driver_id"])
        low = bool(row["low_confidence"]) or did == "NONE"
        if did == "MIXED":
            fill = mixed_fill
        elif low:
            fill = none_fill
        else:
            fill = _hex_to_rgba(color_for(did), 0.85)

        if did == "NONE":
            driver_txt = "—"
            avg_abs_txt = "—"
            avg_s_txt = "—"
        elif did == "MIXED":
            driver_txt = str(row["driver_name"])

            def _fmt_pair(v1: Any, v2: Any) -> str:
                def one(v: Any) -> str:
                    return "—" if v is None or pd.isna(v) else f"{float(v):.2f}"

                return f"{one(v1)}, {one(v2)}"

            avg_abs_txt = _fmt_pair(row.get("mix_avg_abs_1"), row.get("mix_avg_abs_2"))
            avg_s_txt = _fmt_pair(row.get("mix_avg_signed_1"), row.get("mix_avg_signed_2"))
        else:
            driver_txt = str(row["driver_name"])
            avg_abs = row["average_abs_correlation"]
            avg_s = row["average_signed_correlation"]
            avg_abs_txt = "—" if pd.isna(avg_abs) else f"{float(avg_abs):.2f}"
            avg_s_txt = "—" if pd.isna(avg_s) else f"{float(avg_s):.2f}"
        hover = (
            f"주도변수: {driver_txt}<br>"
            f"시작일: {row['start_date'].date()}<br>"
            f"종료일: {row['end_date'].date()}<br>"
            f"지속일: {int(row['trading_days'])}일<br>"
            f"평균 |ρ|: {avg_abs_txt}<br>"
            f"평균 ρ: {avg_s_txt}<extra></extra>"
        )
        fig.add_trace(
            go.Bar(
                x=[(row["end_plot"] - row["start_date"]).total_seconds() * 1000],
                y=["_"],
                base=[row["start_date"]],
                orientation="h",
                marker=dict(color=fill, line=dict(width=0)),
                name=row["driver_name"],
                hovertemplate=hover,
                showlegend=False,
            )
        )

    xaxis: dict[str, Any] = dict(
        type="date",
        title="",
        gridcolor=_tok("fx-chart-grid"),
        tickformat="%Y-%m",
    )
    if x_range is not None:
        xaxis["range"] = list(x_range)
        xaxis["autorange"] = False

    layout_kw: dict[str, Any] = dict(
        **CHART_LAYOUT,
        margin=dict(l=16, r=20, t=28 if title else 12, b=36),
        height=height,
        barmode="overlay",
        xaxis=xaxis,
        yaxis=dict(title="", showticklabels=False, ticks=""),
        bargap=0.2,
    )
    if title:
        layout_kw["title"] = {**CHART_SUBTITLE, "text": title}
    fig.update_layout(**layout_kw)
    return fig


def series_line_chart(
    series: pd.Series,
    title: str,
    y_title: str,
    color: str | None = None,
    height: int = 320,
    value_format: str = ".2f",
) -> go.Figure:
    if series is None or series.dropna().empty:
        return _empty_message_fig(f"{title}: 표시할 데이터가 없습니다.", height=height)

    line_color = color or _tok("fx-detail-line")
    grid = _tok("fx-chart-grid")
    s = series.dropna().sort_index()
    hover_vals = [
        "—" if pd.isna(v) else format(float(v), value_format)
        for v in s.values
    ]
    fig = go.Figure(
        go.Scatter(
            x=s.index,
            y=s.values,
            mode="lines",
            name=title,
            line=dict(color=line_color, width=1.5),
            customdata=hover_vals,
            hovertemplate="%{fullData.name}: %{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        **CHART_LAYOUT,
        margin=dict(l=40, r=20, t=50, b=40),
        title=title,
        height=height,
        yaxis=dict(title=y_title, gridcolor=grid),
        xaxis=dict(title="", gridcolor=grid, tickformat="%Y-%m", hoverformat="%Y-%m-%d"),
        showlegend=False,
        hovermode="x unified",
    )
    return fig


DETAIL_LEVEL_MARGIN = dict(l=56, r=64, t=28, b=40)


def _y_range_with_legend_headroom(
    *series: pd.Series,
    top_frac: float = 0.16,
    bottom_frac: float = 0.04,
) -> list[float] | None:
    chunks: list[np.ndarray] = []
    for s in series:
        if s is None or s.empty:
            continue
        v = np.asarray(s.dropna().values, dtype=float)
        if v.size:
            chunks.append(v)
    if not chunks:
        return None
    vals = np.concatenate(chunks)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    ymin = float(np.min(vals))
    ymax = float(np.max(vals))
    if ymin == ymax:
        pad = abs(ymin) * 0.05 if ymin != 0 else 1.0
        ymin, ymax = ymin - pad, ymax + pad
    span = ymax - ymin
    usable = max(1e-9, 1.0 - top_frac - bottom_frac)
    display_span = span / usable
    return [ymin - display_span * bottom_frac, ymax + display_span * top_frac]


def dual_raw_level_chart(
    usdkrw: pd.Series,
    driver: pd.Series,
    driver_name: str,
    height: int = 380,
    usd_color: str | None = None,
    driver_color: str | None = None,
    title: str | None = None,
) -> go.Figure:
    from plotly.subplots import make_subplots

    u = usdkrw.dropna().sort_index() if usdkrw is not None else pd.Series(dtype=float)
    d = driver.dropna().sort_index() if driver is not None else pd.Series(dtype=float)
    if u.empty and d.empty:
        return _empty_message_fig("표시할 원본값이 없습니다.", height=height)

    left_color = usd_color or _tok("fx-detail-line")
    right_color = driver_color or _tok("fx-detail-driver-line")
    grid = _tok("fx-chart-grid")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not u.empty:
        u_hover = ["—" if pd.isna(v) else f"{float(v):,.2f}" for v in u.values]
        fig.add_trace(
            go.Scatter(
                x=u.index,
                y=u.values,
                mode="lines",
                name="USDKRW",
                line=dict(color=left_color, width=1.6),
                customdata=u_hover,
                hovertemplate="USDKRW: %{customdata}<extra></extra>",
            ),
            secondary_y=False,
        )
    if not d.empty:
        d_hover = ["—" if pd.isna(v) else f"{float(v):,.2f}" for v in d.values]
        fig.add_trace(
            go.Scatter(
                x=d.index,
                y=d.values,
                mode="lines",
                name=driver_name,
                line=dict(color=right_color, width=1.6),
                customdata=d_hover,
                hovertemplate=f"{driver_name}: %{{customdata}}<extra></extra>",
            ),
            secondary_y=True,
        )
    margin = {**DETAIL_LEVEL_MARGIN, "t": 28 if title else 20}
    layout_kw: dict[str, Any] = dict(
        **CHART_LAYOUT,
        margin=margin,
        height=height,
        hovermode="x unified",
        legend=DETAIL_INSET_LEGEND,
        xaxis=dict(title="", gridcolor=grid, tickformat="%Y-%m", hoverformat="%Y-%m-%d"),
    )
    if title:
        layout_kw["title"] = {**CHART_SUBTITLE, "text": title}
    fig.update_layout(**layout_kw)
    left_range = _y_range_with_legend_headroom(u)
    right_range = _y_range_with_legend_headroom(d)
    fig.update_yaxes(
        title_text="USDKRW",
        secondary_y=False,
        gridcolor=grid,
        range=left_range,
        automargin=False,
    )
    fig.update_yaxes(
        title_text=driver_name,
        secondary_y=True,
        gridcolor=grid,
        showgrid=False,
        range=right_range,
        automargin=False,
    )
    return fig


def indexed_level_chart(
    usdkrw: pd.Series,
    driver: pd.Series,
    driver_name: str,
    height: int = 380,
    usd_color: str | None = None,
    driver_color: str | None = None,
    title: str | None = None,
) -> go.Figure:
    from plotly.subplots import make_subplots

    u = usdkrw.dropna().sort_index() if usdkrw is not None else pd.Series(dtype=float)
    d = driver.dropna().sort_index() if driver is not None else pd.Series(dtype=float)
    if u.empty and d.empty:
        return _empty_message_fig("표시할 지수화 값이 없습니다.", height=height)

    left_color = usd_color or _tok("fx-detail-line")
    right_color = driver_color or _tok("fx-detail-driver-line")
    grid = _tok("fx-chart-grid")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not u.empty:
        u_hover = ["—" if pd.isna(v) else f"{float(v):,.2f}" for v in u.values]
        fig.add_trace(
            go.Scatter(
                x=u.index,
                y=u.values,
                mode="lines",
                name="USDKRW",
                line=dict(color=left_color, width=1.6),
                customdata=u_hover,
                hovertemplate="USDKRW: %{customdata}<extra></extra>",
            ),
            secondary_y=False,
        )
    if not d.empty:
        d_hover = ["—" if pd.isna(v) else f"{float(v):,.2f}" for v in d.values]
        fig.add_trace(
            go.Scatter(
                x=d.index,
                y=d.values,
                mode="lines",
                name=driver_name,
                line=dict(color=right_color, width=1.6),
                customdata=d_hover,
                hovertemplate=f"{driver_name}: %{{customdata}}<extra></extra>",
            ),
            secondary_y=False,
        )
    margin = {**DETAIL_LEVEL_MARGIN, "t": 28 if title else 20}
    layout_kw: dict[str, Any] = dict(
        **CHART_LAYOUT,
        margin=margin,
        height=height,
        hovermode="x unified",
        legend=DETAIL_INSET_LEGEND,
        xaxis=dict(title="", gridcolor=grid, tickformat="%Y-%m", hoverformat="%Y-%m-%d"),
    )
    if title:
        layout_kw["title"] = {**CHART_SUBTITLE, "text": title}
    fig.update_layout(**layout_kw)
    y_range = _y_range_with_legend_headroom(u, d)
    fig.update_yaxes(
        title_text="Index",
        secondary_y=False,
        gridcolor=grid,
        range=y_range,
        automargin=False,
    )
    fig.update_yaxes(
        title_text=driver_name,
        secondary_y=True,
        showgrid=False,
        showticklabels=True,
        ticks="",
        range=y_range,
        automargin=False,
        title_font=dict(color="rgba(0,0,0,0)"),
        tickfont=dict(color="rgba(0,0,0,0)"),
    )
    return fig


def rebase_base_date(*series: pd.Series, start: pd.Timestamp) -> pd.Timestamp | None:
    """First Seoul calendar date on/after start present in every non-empty series."""
    start_ts = pd.Timestamp(start).normalize()
    common: pd.DatetimeIndex | None = None
    for s in series:
        if s is None or s.empty:
            continue
        idx = pd.DatetimeIndex(pd.to_datetime(s.dropna().index)).normalize().unique().sort_values()
        idx = idx[idx >= start_ts]
        if len(idx) == 0:
            return None
        common = idx if common is None else common.intersection(idx)
        if common is None or len(common) == 0:
            return None
    if common is None or len(common) == 0:
        return None
    return pd.Timestamp(common.min())


def rebase_series_to_100(
    series: pd.Series,
    start: pd.Timestamp,
    base_date: pd.Timestamp | None = None,
) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    s = series.dropna().sort_index()
    if s.empty:
        return pd.Series(dtype=float)
    s.index = pd.DatetimeIndex(pd.to_datetime(s.index)).normalize()
    start_ts = pd.Timestamp(start).normalize()
    if base_date is not None:
        base_ts = pd.Timestamp(base_date).normalize()
        if base_ts not in s.index:
            return pd.Series(dtype=float)
        base = float(s.loc[base_ts])
    else:
        window = s[s.index >= start_ts]
        if window.empty:
            return pd.Series(dtype=float)
        base = float(window.iloc[0])
    if not np.isfinite(base) or base == 0.0:
        return pd.Series(dtype=float)
    return 100.0 * s / base
