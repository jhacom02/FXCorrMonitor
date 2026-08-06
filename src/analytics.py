"""Rolling correlation and driver analytics for FXCorrMonitor."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from config.instruments import INSTRUMENT_BY_ID, TARGET_ID
from config.thresholds import (
    ANALYSIS_WINDOWS,
    MAD_NORMAL_SCALE,
    MIN_PERIOD_RATIO,
    MIXED_SCORE_GAP,
    ROBUST_Z_ABS_MIN,
    ROBUST_Z_WINDOW,
    SHOCK_ABS_FLOOR,
    STATUS_ABS_DELTA,
    sig_abs,
)

DRIVER_NONE = "NONE"
DRIVER_MIXED = "MIXED"
DRIVER_NONE_NAME = "없음"
DRIVER_MIXED_NAME = "혼합"


def min_periods_for_window(window: int, min_period_ratio: float = MIN_PERIOD_RATIO) -> int:
    return int(math.ceil(window * min_period_ratio))


def calculate_rolling_correlations(
    transformed_df: pd.DataFrame,
    target: str = TARGET_ID,
    drivers: list[str] | None = None,
    window: int = 20,
    min_period_ratio: float = MIN_PERIOD_RATIO,
) -> pd.DataFrame:
    if transformed_df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "instrument_id",
                "display_name",
                "rolling_correlation",
                "abs_correlation",
                "observation_count",
            ]
        )

    if target not in transformed_df.columns:
        raise ValueError(f"시장변수 '{target}'가 변환된 데이터프레임에 없습니다.")

    if drivers is None:
        drivers = [c for c in transformed_df.columns if c != target]

    min_periods = min_periods_for_window(window, min_period_ratio)
    target_s = transformed_df[target]
    rows: list[dict[str, Any]] = []

    for iid in drivers:
        if iid not in transformed_df.columns:
            continue
        driver_s = transformed_df[iid]
        pair = pd.concat([target_s, driver_s], axis=1, keys=["target", "driver"])
        corr = (
            pair["target"]
            .rolling(window=window, min_periods=min_periods)
            .corr(pair["driver"])
        )
        valid = pair["target"].notna() & pair["driver"].notna()
        obs_count = valid.astype(int).rolling(window=window, min_periods=1).sum()

        inst = INSTRUMENT_BY_ID.get(iid)
        display = inst.display_name if inst else iid

        for dt, value in corr.items():
            if pd.isna(value):
                rolling_corr = np.nan
            else:
                rolling_corr = float(value)
                if rolling_corr > 1.0 or rolling_corr < -1.0:
                    rolling_corr = float(np.clip(rolling_corr, -1.0, 1.0))
            n_obs = obs_count.loc[dt]
            rows.append(
                {
                    "date": pd.Timestamp(dt).normalize(),
                    "instrument_id": iid,
                    "display_name": display,
                    "rolling_correlation": rolling_corr,
                    "abs_correlation": abs(rolling_corr) if pd.notna(rolling_corr) else np.nan,
                    "observation_count": int(n_obs) if pd.notna(n_obs) else 0,
                }
            )

    out = pd.DataFrame(rows)
    if not out.empty:
        bad = out["rolling_correlation"].dropna()
        if len(bad) and ((bad < -1.0 - 1e-9) | (bad > 1.0 + 1e-9)).any():
            raise ValueError("Rolling correlation out of [-1, 1] range")
    return out


def _display_for_driver(driver_id: str) -> str:
    if driver_id == DRIVER_NONE:
        return DRIVER_NONE_NAME
    if driver_id == DRIVER_MIXED:
        return DRIVER_MIXED_NAME
    inst = INSTRUMENT_BY_ID.get(driver_id)
    if inst:
        return inst.display_name
    return driver_id


def assign_daily_drivers(
    corr_long: pd.DataFrame,
    min_score: float,
    mixed_gap: float = MIXED_SCORE_GAP,
) -> pd.DataFrame:
    empty_cols = [
        "date",
        "driver_id",
        "driver_name",
        "signed_correlation",
        "abs_correlation",
        "mix_signed_1",
        "mix_abs_1",
        "mix_signed_2",
        "mix_abs_2",
    ]
    if corr_long.empty:
        return pd.DataFrame(columns=empty_cols)

    def _blank_mix() -> dict[str, Any]:
        return {
            "mix_signed_1": np.nan,
            "mix_abs_1": np.nan,
            "mix_signed_2": np.nan,
            "mix_abs_2": np.nan,
        }

    records: list[dict[str, Any]] = []
    for dt, grp in corr_long.groupby("date"):
        valid = grp.dropna(subset=["abs_correlation"]).copy()
        mix = _blank_mix()
        if valid.empty:
            records.append(
                {
                    "date": dt,
                    "driver_id": DRIVER_NONE,
                    "driver_name": DRIVER_NONE_NAME,
                    "signed_correlation": np.nan,
                    "abs_correlation": np.nan,
                    **mix,
                }
            )
            continue

        valid = valid.sort_values("abs_correlation", ascending=False)
        top = valid.iloc[0]
        top_abs = float(top["abs_correlation"])
        second = valid.iloc[1] if len(valid) > 1 else None
        second_abs = float(second["abs_correlation"]) if second is not None else -np.inf

        if top_abs < min_score:
            driver_id = DRIVER_NONE
            name = DRIVER_NONE_NAME
            signed = np.nan
            abs_c = np.nan
        elif (top_abs - second_abs) < mixed_gap and second is not None:
            driver_id = DRIVER_MIXED
            n1 = str(top["display_name"])
            n2 = str(second["display_name"])
            name = f"혼합({n1}, {n2})"
            signed = np.nan
            abs_c = np.nan
            mix = {
                "mix_signed_1": (
                    float(top["rolling_correlation"]) if pd.notna(top["rolling_correlation"]) else np.nan
                ),
                "mix_abs_1": top_abs,
                "mix_signed_2": (
                    float(second["rolling_correlation"])
                    if pd.notna(second["rolling_correlation"])
                    else np.nan
                ),
                "mix_abs_2": second_abs,
            }
        else:
            driver_id = str(top["instrument_id"])
            name = _display_for_driver(driver_id)
            signed = float(top["rolling_correlation"]) if pd.notna(top["rolling_correlation"]) else np.nan
            abs_c = top_abs

        records.append(
            {
                "date": dt,
                "driver_id": driver_id,
                "driver_name": name,
                "signed_correlation": signed,
                "abs_correlation": abs_c,
                **mix,
            }
        )

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


def latest_top_driver(corr_long: pd.DataFrame, min_abs: float) -> dict[str, Any]:
    empty = {
        "driver_id": DRIVER_NONE,
        "driver_name": DRIVER_NONE_NAME,
        "signed_correlation": np.nan,
        "abs_correlation": np.nan,
    }
    if corr_long is None or corr_long.empty:
        return empty

    df = corr_long.copy()
    df["date"] = pd.to_datetime(df["date"])
    as_of = df["date"].max()
    snap = df[df["date"] == as_of].dropna(subset=["abs_correlation"])
    if snap.empty:
        return empty

    top = snap.sort_values("abs_correlation", ascending=False).iloc[0]
    top_abs = float(top["abs_correlation"])
    if top_abs < float(min_abs):
        return empty

    did = str(top["instrument_id"])
    return {
        "driver_id": did,
        "driver_name": _display_for_driver(did),
        "signed_correlation": (
            float(top["rolling_correlation"]) if pd.notna(top["rolling_correlation"]) else np.nan
        ),
        "abs_correlation": top_abs,
    }


def _absorb_single_day_regimes(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty or len(daily) < 2:
        return daily.copy()

    out = daily.sort_values("date").reset_index(drop=True).copy()
    old_names = out["driver_name"].tolist()
    ids = list(out["driver_id"].tolist())
    name_src = list(range(len(ids)))

    i = 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[i]:
            j += 1
        run_len = j - i + 1
        if run_len == 1:
            if i > 0:
                ids[i] = ids[i - 1]
                name_src[i] = name_src[i - 1]
            elif i + 1 < len(ids):
                ids[i] = ids[i + 1]
                name_src[i] = i + 1
        i = j + 1

    names = [old_names[name_src[k]] for k in range(len(ids))]
    out["driver_id"] = ids
    out["driver_name"] = names
    return out


def regimes_for_window(
    transformed_df: pd.DataFrame,
    drivers: list[str],
    window: int,
    target: str = TARGET_ID,
) -> pd.DataFrame:
    corr = calculate_rolling_correlations(
        transformed_df,
        target=target,
        drivers=drivers,
        window=window,
    )
    daily = assign_daily_drivers(corr, min_score=sig_abs(window))
    return compress_driver_regimes(daily)


def _corr_sign(value: float) -> int | None:
    if pd.isna(value) or float(value) == 0.0:
        return None
    return 1 if float(value) > 0 else -1


def classify_driver_status(
    rho_20: float,
    rho_60: float,
    rho_120: float,
) -> str:
    s20_floor = sig_abs(20)
    s60_floor = sig_abs(60)
    s120_floor = sig_abs(120)

    if pd.isna(rho_20) or abs(float(rho_20)) < s20_floor:
        return "—"

    a20 = abs(float(rho_20))
    a60 = abs(float(rho_60)) if pd.notna(rho_60) else 0.0
    a120 = abs(float(rho_120)) if pd.notna(rho_120) else 0.0
    s20 = _corr_sign(rho_20)
    s60 = _corr_sign(rho_60) if pd.notna(rho_60) else None
    s120 = _corr_sign(rho_120) if pd.notna(rho_120) else None

    if a60 < s60_floor and a120 < s120_floor:
        return "신규"

    if s20 is not None and s60 is not None and s20 != s60 and a60 >= s60_floor:
        return "전환"
    if (
        s20 is not None
        and s60 is not None
        and s120 is not None
        and s20 == s60
        and s20 != s120
        and a60 >= s60_floor
        and a120 >= s120_floor
    ):
        return "전환"

    if s20 is not None and s60 is not None and s20 == s60:
        same_or_weak_120 = s120 == s20 or a120 < s120_floor
        if a20 - a60 >= STATUS_ABS_DELTA and same_or_weak_120:
            return "강화"
        if a60 - a20 >= STATUS_ABS_DELTA and same_or_weak_120:
            return "약화"
        if abs(a20 - a60) < STATUS_ABS_DELTA:
            return "지속"

    return "—"


def compress_driver_regimes(daily_drivers: pd.DataFrame) -> pd.DataFrame:
    if daily_drivers.empty:
        return pd.DataFrame(
            columns=[
                "start_date",
                "end_date",
                "driver_id",
                "driver_name",
                "trading_days",
                "average_signed_correlation",
                "average_abs_correlation",
                "min_signed_correlation",
                "max_signed_correlation",
                "max_abs_correlation",
                "mix_avg_signed_1",
                "mix_avg_abs_1",
                "mix_avg_signed_2",
                "mix_avg_abs_2",
            ]
        )

    absorbed = _absorb_single_day_regimes(daily_drivers)
    for col in ("mix_signed_1", "mix_abs_1", "mix_signed_2", "mix_abs_2"):
        if col not in absorbed.columns:
            absorbed[col] = np.nan

    regimes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for _, row in absorbed.sort_values("date").iterrows():
        did = row["driver_id"]
        if current is None or current["driver_id"] != did:
            if current is not None:
                regimes.append(_finalize_regime(current))
            current = {
                "driver_id": did,
                "driver_name": row["driver_name"],
                "dates": [row["date"]],
                "signed": [row["signed_correlation"]],
                "abs": [row["abs_correlation"]],
                "mix_signed_1": [row["mix_signed_1"]],
                "mix_abs_1": [row["mix_abs_1"]],
                "mix_signed_2": [row["mix_signed_2"]],
                "mix_abs_2": [row["mix_abs_2"]],
            }
        else:
            current["dates"].append(row["date"])
            current["signed"].append(row["signed_correlation"])
            current["abs"].append(row["abs_correlation"])
            current["mix_signed_1"].append(row["mix_signed_1"])
            current["mix_abs_1"].append(row["mix_abs_1"])
            current["mix_signed_2"].append(row["mix_signed_2"])
            current["mix_abs_2"].append(row["mix_abs_2"])

    if current is not None:
        regimes.append(_finalize_regime(current))

    out = pd.DataFrame(regimes)
    if not out.empty:
        out = out.sort_values("start_date", ascending=False).reset_index(drop=True)
    return out


def _nanmean_list(values: list[Any]) -> float:
    s = pd.Series(values, dtype=float)
    return float(s.mean()) if s.notna().any() else np.nan


def _finalize_regime(current: dict[str, Any]) -> dict[str, Any]:
    signed = pd.Series(current["signed"], dtype=float)
    abs_s = pd.Series(current["abs"], dtype=float)
    is_mixed = current["driver_id"] == DRIVER_MIXED
    return {
        "start_date": pd.Timestamp(current["dates"][0]).normalize(),
        "end_date": pd.Timestamp(current["dates"][-1]).normalize(),
        "driver_id": current["driver_id"],
        "driver_name": current["driver_name"],
        "trading_days": len(current["dates"]),
        "average_signed_correlation": float(signed.mean()) if signed.notna().any() else np.nan,
        "average_abs_correlation": float(abs_s.mean()) if abs_s.notna().any() else np.nan,
        "min_signed_correlation": float(signed.min()) if signed.notna().any() else np.nan,
        "max_signed_correlation": float(signed.max()) if signed.notna().any() else np.nan,
        "max_abs_correlation": float(abs_s.max()) if abs_s.notna().any() else np.nan,
        "mix_avg_signed_1": _nanmean_list(current["mix_signed_1"]) if is_mixed else np.nan,
        "mix_avg_abs_1": _nanmean_list(current["mix_abs_1"]) if is_mixed else np.nan,
        "mix_avg_signed_2": _nanmean_list(current["mix_signed_2"]) if is_mixed else np.nan,
        "mix_avg_abs_2": _nanmean_list(current["mix_abs_2"]) if is_mixed else np.nan,
    }


def regime_label_on_date(regimes: pd.DataFrame, as_of: pd.Timestamp) -> str:
    if regimes is None or regimes.empty:
        return "—"
    as_of_ts = pd.Timestamp(as_of).normalize()
    df = regimes.copy()
    df["start_date"] = pd.to_datetime(df["start_date"]).dt.normalize()
    df["end_date"] = pd.to_datetime(df["end_date"]).dt.normalize()
    hit = df[(df["start_date"] <= as_of_ts) & (df["end_date"] >= as_of_ts)]
    if hit.empty:
        return "—"
    row = hit.iloc[0]
    if str(row["driver_id"]) == DRIVER_NONE:
        return "—"
    name = row["driver_name"]
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return "—"
    return str(name)


def build_driver_ranking(
    corr_long: pd.DataFrame,
    as_of_date: pd.Timestamp | None = None,
    lag_days: int = 5,
) -> pd.DataFrame:
    empty_cols = [
        "rank",
        "instrument_id",
        "display_name",
        "rolling_correlation",
        "abs_correlation",
        "change_vs_5d",
        "observation_count",
    ]
    if corr_long.empty:
        return pd.DataFrame(columns=empty_cols)

    df = corr_long.copy()
    df["date"] = pd.to_datetime(df["date"])
    if as_of_date is None:
        as_of = df["date"].max()
    else:
        as_of = pd.Timestamp(as_of_date).normalize()

    latest = df[df["date"] == as_of].copy()
    if latest.empty:
        return pd.DataFrame(columns=empty_cols)

    dates = sorted(df["date"].unique())
    try:
        idx = dates.index(as_of)
        lag_date = dates[idx - lag_days] if idx >= lag_days else None
    except ValueError:
        lag_date = None

    lag_map: dict[str, float] = {}
    if lag_date is not None:
        lag = df[df["date"] == lag_date]
        for _, r in lag.iterrows():
            if pd.notna(r["rolling_correlation"]):
                lag_map[r["instrument_id"]] = float(r["rolling_correlation"])

    latest = latest.sort_values("abs_correlation", ascending=False, na_position="last")
    latest["rank"] = range(1, len(latest) + 1)
    latest["change_vs_5d"] = latest.apply(
        lambda r: (
            float(r["rolling_correlation"]) - lag_map[r["instrument_id"]]
            if r["instrument_id"] in lag_map and pd.notna(r["rolling_correlation"])
            else np.nan
        ),
        axis=1,
    )

    return latest[empty_cols].reset_index(drop=True)


def multi_window_correlations(
    transformed_df: pd.DataFrame,
    drivers: list[str],
    windows: list[int] | None = None,
    target: str = TARGET_ID,
    as_of_date: pd.Timestamp | None = None,
    min_period_ratio: float = MIN_PERIOD_RATIO,
) -> pd.DataFrame:
    windows = list(windows) if windows is not None else list(ANALYSIS_WINDOWS)
    if as_of_date is None:
        as_of = transformed_df.index.max()
    else:
        as_of = pd.Timestamp(as_of_date).normalize()

    records: list[dict[str, Any]] = []
    for w in windows:
        long_df = calculate_rolling_correlations(
            transformed_df,
            target=target,
            drivers=drivers,
            window=w,
            min_period_ratio=min_period_ratio,
        )
        if long_df.empty:
            continue
        snap = long_df[long_df["date"] == as_of]
        for _, r in snap.iterrows():
            records.append(
                {
                    "instrument_id": r["instrument_id"],
                    "display_name": r["display_name"],
                    "window": w,
                    "rolling_correlation": r["rolling_correlation"],
                }
            )
    return pd.DataFrame(records)


def _rolling_mad(prior: pd.Series, window: int) -> pd.Series:
    def _mad(arr: np.ndarray) -> float:
        med = float(np.median(arr))
        return float(np.median(np.abs(arr - med)))

    return prior.rolling(window=window, min_periods=window).apply(_mad, raw=True)


def _robust_z_series(x: pd.Series, window: int = ROBUST_Z_WINDOW) -> pd.Series:
    prior = x.shift(1)
    rolling_median = prior.rolling(window=window, min_periods=window).median()
    rolling_mad = _rolling_mad(prior, window)
    robust_sigma = MAD_NORMAL_SCALE * rolling_mad
    z = (x - rolling_median) / robust_sigma
    z = z.where(robust_sigma > 0)
    return z


def detect_historical_shocks(
    transformed_wide: pd.DataFrame,
    display_start: pd.Timestamp | None = None,
    display_end: pd.Timestamp | None = None,
    z_abs_min: float | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if transformed_wide.empty:
        return pd.DataFrame()

    threshold = float(z_abs_min) if z_abs_min is not None else float(ROBUST_Z_ABS_MIN)
    start = pd.Timestamp(display_start) if display_start is not None else None
    end = pd.Timestamp(display_end) if display_end is not None else None

    for iid in transformed_wide.columns:
        floor = SHOCK_ABS_FLOOR.get(iid)
        if floor is None:
            continue
        inst = INSTRUMENT_BY_ID.get(iid)
        if inst is None:
            continue
        if inst.transformation == "diff_bp":
            unit = "diff_bp"
        elif inst.transformation == "log_return":
            unit = "log_return"
        else:
            continue

        s = transformed_wide[iid].dropna()
        if s.empty:
            continue
        z = _robust_z_series(s)
        mask = z.abs() >= threshold
        mask &= s.abs() >= floor
        mask &= z.notna()
        if start is not None:
            mask &= s.index >= start
        if end is not None:
            mask &= s.index <= end

        flagged_idx = s.index[mask]
        for dt in flagged_idx:
            rows.append(
                {
                    "date": pd.Timestamp(dt).date().isoformat(),
                    "instrument_id": iid,
                    "display_name": inst.display_name,
                    "value": float(s.loc[dt]),
                    "robust_z": float(z.loc[dt]),
                    "abs_threshold": float(floor),
                    "unit": unit,
                }
            )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["date", "instrument_id"], ascending=[False, True]
    ).reset_index(drop=True)
