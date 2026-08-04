"""Rolling correlation and driver analytics for FXCorrMonitor."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from config.instruments import INSTRUMENT_BY_ID, TARGET_ID

DRIVER_NONE = "NONE"
DRIVER_MIXED = "MIXED"
DRIVER_NONE_NAME = "없음"
DRIVER_MIXED_NAME = "혼합"

MIN_DRIVER_SCORE = 0.30
MIXED_SCORE_GAP = 0.05
SCORE_WINDOW = 5


def min_periods_for_window(window: int, min_period_ratio: float = 0.8) -> int:
    return int(math.ceil(window * min_period_ratio))


def calculate_rolling_correlations(
    transformed_df: pd.DataFrame,
    target: str = TARGET_ID,
    drivers: list[str] | None = None,
    window: int = 20,
    min_period_ratio: float = 0.8,
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
        raise ValueError(f"Target '{target}' not in transformed dataframe")

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


def compute_driver_scores(
    corr_long: pd.DataFrame,
    score_window: int = SCORE_WINDOW,
) -> pd.DataFrame:
    if corr_long.empty:
        return corr_long.copy()

    df = corr_long.sort_values(["instrument_id", "date"]).copy()
    scores = []
    for iid, grp in df.groupby("instrument_id", sort=False):
        g = grp.sort_values("date")
        score = (
            g["abs_correlation"]
            .rolling(window=score_window, min_periods=1)
            .median()
        )
        tmp = g.copy()
        tmp["driver_score"] = score
        scores.append(tmp)
    return pd.concat(scores, ignore_index=True)


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
    scored_corr: pd.DataFrame,
    min_score: float = MIN_DRIVER_SCORE,
    mixed_gap: float = MIXED_SCORE_GAP,
) -> pd.DataFrame:
    if scored_corr.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "driver_id",
                "driver_name",
                "signed_correlation",
                "abs_correlation",
                "driver_score",
            ]
        )

    records: list[dict[str, Any]] = []
    for dt, grp in scored_corr.groupby("date"):
        valid = grp.dropna(subset=["driver_score"]).copy()
        if valid.empty:
            records.append(
                {
                    "date": dt,
                    "driver_id": DRIVER_NONE,
                    "driver_name": DRIVER_NONE_NAME,
                    "signed_correlation": np.nan,
                    "abs_correlation": np.nan,
                    "driver_score": np.nan,
                }
            )
            continue

        valid = valid.sort_values("driver_score", ascending=False)
        top = valid.iloc[0]
        top_score = float(top["driver_score"])
        second = valid.iloc[1] if len(valid) > 1 else None
        second_score = float(second["driver_score"]) if second is not None else -np.inf

        if top_score < min_score:
            driver_id = DRIVER_NONE
            name = DRIVER_NONE_NAME
            signed = np.nan
            abs_c = np.nan
            score = top_score
        elif (top_score - second_score) < mixed_gap and second is not None:
            driver_id = DRIVER_MIXED
            n1 = str(top["display_name"])
            n2 = str(second["display_name"])
            name = f"혼합({n1}, {n2})"
            signed = np.nan
            abs_c = np.nan
            score = top_score
        else:
            driver_id = str(top["instrument_id"])
            name = _display_for_driver(driver_id)
            signed = float(top["rolling_correlation"]) if pd.notna(top["rolling_correlation"]) else np.nan
            abs_c = float(top["abs_correlation"]) if pd.notna(top["abs_correlation"]) else np.nan
            score = top_score

        records.append(
            {
                "date": dt,
                "driver_id": driver_id,
                "driver_name": name,
                "signed_correlation": signed,
                "abs_correlation": abs_c,
                "driver_score": score,
            }
        )

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


def _absorb_single_day_regimes(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty or len(daily) < 2:
        return daily.copy()

    out = daily.sort_values("date").reset_index(drop=True).copy()
    orig_ids = out["driver_id"].tolist()
    old_names = out["driver_name"].tolist()
    ids = list(orig_ids)

    i = 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[i]:
            j += 1
        run_len = j - i + 1
        if run_len == 1:
            prev_id = ids[i - 1] if i > 0 else None
            next_id = ids[i + 1] if i + 1 < len(ids) else None
            if prev_id is not None and next_id is not None and prev_id == next_id:
                ids[i] = prev_id
            elif prev_id is not None and next_id is not None and prev_id != next_id:
                ids[i] = DRIVER_MIXED
            elif prev_id is not None and next_id is None:
                ids[i] = prev_id
            elif prev_id is None and next_id is not None:
                ids[i] = next_id
        i = j + 1

    names = []
    for i, did in enumerate(ids):
        if did == orig_ids[i]:
            names.append(old_names[i])
        else:
            names.append(_display_for_driver(did))
    out["driver_id"] = ids
    out["driver_name"] = names
    return out


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
            ]
        )

    absorbed = _absorb_single_day_regimes(daily_drivers)
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
            }
        else:
            current["dates"].append(row["date"])
            current["signed"].append(row["signed_correlation"])
            current["abs"].append(row["abs_correlation"])

    if current is not None:
        regimes.append(_finalize_regime(current))

    out = pd.DataFrame(regimes)
    if not out.empty:
        out = out.sort_values("start_date", ascending=False).reset_index(drop=True)
    return out


def _finalize_regime(current: dict[str, Any]) -> dict[str, Any]:
    signed = pd.Series(current["signed"], dtype=float)
    abs_s = pd.Series(current["abs"], dtype=float)
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
    }


def build_driver_ranking(
    scored_corr: pd.DataFrame,
    as_of_date: pd.Timestamp | None = None,
    lag_days: int = 5,
) -> pd.DataFrame:
    empty_cols = [
        "rank",
        "instrument_id",
        "display_name",
        "rolling_correlation",
        "abs_correlation",
        "driver_score",
        "change_vs_5d",
        "observation_count",
    ]
    if scored_corr.empty:
        return pd.DataFrame(columns=empty_cols)

    df = scored_corr.copy()
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
    min_period_ratio: float = 0.8,
) -> pd.DataFrame:
    windows = windows or [20, 60, 120]
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


def current_driver_snapshot(
    daily_drivers: pd.DataFrame,
    scored_corr: pd.DataFrame,
) -> dict[str, Any]:
    empty = {
        "driver_id": DRIVER_NONE,
        "driver_name": DRIVER_NONE_NAME,
        "signed_correlation": np.nan,
        "abs_correlation": np.nan,
        "driver_score": np.nan,
        "previous_driver_id": None,
        "previous_driver_name": None,
        "regime_start": None,
        "regime_days": 0,
    }
    if daily_drivers.empty:
        return empty

    d = daily_drivers.sort_values("date")
    latest = d.iloc[-1]
    current_id = latest["driver_id"]

    regime_start = latest["date"]
    regime_days = 1
    for i in range(len(d) - 2, -1, -1):
        if d.iloc[i]["driver_id"] == current_id:
            regime_start = d.iloc[i]["date"]
            regime_days += 1
        else:
            break

    prev_row = d.iloc[len(d) - regime_days - 1] if len(d) > regime_days else None

    score = latest["driver_score"]
    if current_id not in (DRIVER_NONE, DRIVER_MIXED) and not scored_corr.empty:
        match = scored_corr[
            (scored_corr["date"] == latest["date"])
            & (scored_corr["instrument_id"] == current_id)
        ]
        if not match.empty:
            score = match.iloc[0]["driver_score"]

    return {
        "driver_id": current_id,
        "driver_name": latest["driver_name"],
        "signed_correlation": latest["signed_correlation"],
        "abs_correlation": latest["abs_correlation"],
        "driver_score": float(score) if pd.notna(score) else np.nan,
        "previous_driver_id": prev_row["driver_id"] if prev_row is not None else None,
        "previous_driver_name": prev_row["driver_name"] if prev_row is not None else None,
        "regime_start": pd.Timestamp(regime_start).date().isoformat(),
        "regime_days": regime_days,
    }


def detect_abnormal_returns(
    transformed_wide: pd.DataFrame,
    raw_aligned_wide: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if transformed_wide.empty:
        return pd.DataFrame()

    for iid in transformed_wide.columns:
        inst = INSTRUMENT_BY_ID.get(iid)
        if inst is None:
            continue
        s = transformed_wide[iid].dropna()
        if s.empty:
            continue

        if inst.transformation == "diff_bp":
            thresh = 50.0
            mask = s.abs() > thresh
            unit = "bp"
        elif iid == "VIX":
            thresh = 0.50
            mask = s.abs() > thresh
            unit = "log_return"
        elif inst.transformation == "log_return":
            thresh = 0.10
            mask = s.abs() > thresh
            unit = "log_return"
        else:
            continue

        flagged = s[mask]
        for dt, val in flagged.items():
            rows.append(
                {
                    "date": pd.Timestamp(dt).date().isoformat(),
                    "instrument_id": iid,
                    "display_name": inst.display_name,
                    "value": float(val),
                    "threshold": thresh,
                    "unit": unit,
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "instrument_id"], ascending=[False, True]) if rows else pd.DataFrame()
