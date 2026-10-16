#!/usr/bin/env python3
"""
solar_model.py

Simulate solar energy curtailment and the benefits of colocating a data center
and battery storage with a large solar farm (Bhadla Solar Park example).

Assumptions & Inputs:
- Expects a CSV at ./data/bhadla_data.csv containing hourly NSRDB-like records.
  Required columns: Year, Month, Day, Hour (1-24 typically) and preferably GHI or
  a Power Output column. The script tries to be flexible with column names.
- If "Power Output" is absent, it estimates power output from GHI using:
    power_MW = (GHI [W/m2] * PANEL_AREA [m2] * PANEL_EFFICIENCY) / 1e6
  (we use 1e6 to convert watts to MW; comment explains units).
- Time resolution: hourly.

Outputs:
- Several matplotlib figures (each followed by plt.show()).
- Text-print summary and a summary table printed with pandas.
- Modular functions for each step.

"""

import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------
# CONFIGURABLE CONSTANTS
# ---------------------------
DATA_PATH = Path("data") / "bhadla_data.zip"   # expected local csv path

# Physical parameters for power estimation (changeable)
PANEL_AREA = 1e6           # m^2  (total collector area used for estimate example)
PANEL_EFFICIENCY = 0.18    # unitless

# Bhadla site & system constants
SOLAR_CAPACITY = 2245      # MW (nameplate capacity used to scale modeled sine curve)
GRID_LIMIT_FRACS = [0.6, 0.7, 0.8, 0.9, 0.95]  # fraction of SOLAR_CAPACITY allowed export

# Data center and battery parameters
DATACENTER_CRITICAL_LOAD = 100  # MW constant critical load
DATACENTER_FLEXIBLE_MAX = 400   # MW flexible load that can absorb curtailed power
BATTERY_CAPACITY = 200          # MWh (energy capacity)
BATTERY_EFFICIENCY = 0.9        # round-trip efficiency fraction

# Round-trip efficiency (charge * discharge)
BATTERY_ROUNDTRIP_EFF = 0.90    # 90% round-trip efficiency

# More realistic battery parameters
BATTERY_CHARGE_RATE = 500.0     # MW maximum charge power (MW == MWh per hour)
BATTERY_DISCHARGE_RATE = 500.0  # MW maximum discharge power
# Split round-trip efficiency into charge/discharge (even split by sqrt is a common simple choice)
BATTERY_CHARGE_EFF = float(np.sqrt(BATTERY_ROUNDTRIP_EFF))
BATTERY_DISCHARGE_EFF = float(np.sqrt(BATTERY_ROUNDTRIP_EFF))

# Day-to-day solar variation (applied multiplicatively per day)
DAILY_VARIATION_STD = 0.05      # 5% standard deviation (tuneable). Clip applied later.
DAILY_VARIATION_SEED = 42       # for reproducibility

# Simulation settings
LOCAL_TZ = None  # Not converting tz; assume dataset in local time
PLOT_DAY_SAMPLE = None  # if None script picks first day in data for daily plots

# Data Center Realism
CRITICAL_LOAD_FRACTION = 0.4      # 40% of total DC load is non-flexible
MAX_RAMP_RATE = 50                # MW per hour
COOLING_FRACTION = 0.3            # cooling = 30% of compute load

# ---------------------------
# Utility & Loading Functions
# ---------------------------

def load_data(csv_path: Path) -> pd.DataFrame:
    """
    Load and combine all CSV files from a ZIP archive or directory.
    - If given a ZIP file (e.g. data/bhadla_data.zip), extracts it to 'data/extracted/'
      and loads all CSV files inside, regardless of internal folder name.
    - If given a CSV file directly, loads that single file.
    Handles NSRDB files that include a metadata row above the header (skipped).
    Returns a DataFrame with a datetime index ('timestamp') and power_MW column.
    """
    import zipfile, glob

    # Determine what type of path was given
    if not csv_path.exists():
        raise FileNotFoundError(f"Input not found: {csv_path.resolve()}")

    # Case 1: ZIP file
    if csv_path.suffix == ".zip":
        extract_dir = csv_path.parent / "extracted"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(csv_path, "r") as z:
            z.extractall(extract_dir)

        # Find all CSVs recursively inside extracted folder
        csv_files = glob.glob(str(extract_dir / "**" / "*.csv"), recursive=True)
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found inside {csv_path.name} after extraction.")

        print(f"✅ Found {len(csv_files)} CSV files inside ZIP.")
        # 🔹 Skip first metadata line in each CSV
        dfs = [pd.read_csv(f, skiprows=2) for f in csv_files]
        df = pd.concat(dfs, ignore_index=True)

    # Case 2: Single CSV file
    elif csv_path.suffix == ".csv":
        # 🔹 Skip first metadata line here too
        df = pd.read_csv(csv_path, skiprows=2)

    else:
        raise ValueError(f"Unsupported file type: {csv_path.suffix}")

    # Normalize column names for flexible lookups
    cols_lower = {c.lower(): c for c in df.columns}

    # Required datetime fields: year, month, day, hour
    for c in ("year", "month", "day", "hour"):
        if c not in cols_lower:
            raise ValueError(f"CSV must contain column '{c}' (case-insensitive). Found: {list(df.columns)}")

    # Build timestamp
    df["timestamp"] = pd.to_datetime(
        dict(
            year=df[cols_lower["year"]],
            month=df[cols_lower["month"]],
            day=df[cols_lower["day"]],
            hour=df[cols_lower["hour"]]
        )
        
    )
    # ✅ Set timestamp as index for time-based operations
    df = df.set_index("timestamp")

    # Handle GHI / Power Output columns
    ghi_col = cols_lower.get("ghi", None)
    power_col = cols_lower.get("power output", None)

    if power_col:
        df["power_MW"] = df[power_col]
    elif ghi_col:
        df["power_MW"] = df[ghi_col] * PANEL_AREA * PANEL_EFFICIENCY / 1e6
    else:
        raise ValueError("No 'Power Output' or 'GHI' column found.")

    print("✅ Data loaded and processed successfully.")
    return df
# ---------------------------
# Modeling functions
# ---------------------------

def plot_one_day(df: pd.DataFrame, day_timestamp=None):
    """
    Plot a single day's observed generation 06:00-18:00 to confirm realistic data.
    If day_timestamp is None, choose the first day available in df.
    """
    if day_timestamp is None:
        day_timestamp = df.index.normalize().unique()[0]  # first day midnight
    day = pd.Timestamp(day_timestamp).normalize()
    mask = (df.index >= day + pd.Timedelta(hours=6)) & (df.index < day + pd.Timedelta(hours=18))
    sample = df.loc[mask].copy()
    if sample.empty:
        print("Warning: no daytime hours found for plotting sample day. Using first 24 hours instead.")
        sample = df.iloc[:24]
    plt.figure(figsize=(10, 4))
    plt.plot(sample.index, sample["power_MW"], marker="o", linestyle="-")
    plt.title(f"Observed power output (sample day: {sample.index[0].date()}) — 06:00-18:00")
    plt.ylabel("Power (MW)")
    plt.xlabel("Time")
    plt.grid(True)
    plt.tight_layout()
    plt.show()


def fit_sine_model(df: pd.DataFrame, capacity_mw: float) -> pd.Series:
    """
    Fit a smooth daily sine-like model to represent average diurnal solar output.

    Updated version:
    - Computes average shape per hour.
    - Builds a smooth sine curve based on observed daylight pattern.
    - Scales the final output so that its maximum equals the PLANT CAPACITY (capacity_mw),
      not just the observed peak. This ensures correct modeled amplitude.
    """
    df2 = df.copy()

    # --- Get hour-of-day ---
    if isinstance(df2.index, pd.DatetimeIndex):
        df2["hour"] = df2.index.hour
    elif "timestamp" in df2.columns:
        df2["hour"] = pd.to_datetime(df2["timestamp"]).dt.hour
    else:
        raise ValueError("No datetime information found for hour extraction.")

    # --- Identify correct power column ---
    if "power_MW" in df2.columns:
        power_col = "power_MW"
    elif "power" in df2.columns:
        power_col = "power"
    else:
        raise KeyError(f"No power column found in df2. Columns: {df2.columns.tolist()}")

    # --- Compute average shape per hour ---
    hourly_avg = df2.groupby("hour")[power_col].mean()
    if hourly_avg.max() <= 0:
        raise ValueError("Hour-of-day average generation is zero across dataset.")

    normalized = hourly_avg / hourly_avg.max()

    # --- Estimate day length and sunrise shift ---
    hours = np.arange(24)
    width_mask = normalized >= 0.1 * normalized.max()
    if width_mask.sum() < 2:
        day_length = 12
    else:
        min_h = hours[width_mask].min()
        max_h = hours[width_mask].max()
        day_length = max(6, max_h - min_h)
    com = np.sum(hours * normalized) / np.sum(normalized)
    sunrise_shift = com - day_length / 2

    # --- Build smooth sine curve ---
    modeled_hourly_norm = np.sin(np.pi * (hours - sunrise_shift) / (day_length + 1e-6))
    modeled_hourly_norm = np.where(modeled_hourly_norm > 0, modeled_hourly_norm, 0)
    modeled_hourly_norm = modeled_hourly_norm ** 1.2
    modeled_hourly_norm = modeled_hourly_norm / modeled_hourly_norm.max()

    # --- ✅ SCALE TO FULL PLANT CAPACITY ---
    modeled_hourly = modeled_hourly_norm * capacity_mw

    # --- Construct modeled series aligned with df.index ---
    modeled = pd.Series(index=df.index, dtype=float)
    for ts in df.index:
        modeled.at[ts] = modeled_hourly[ts.hour]

    # --- Debug print ---
    print(
        f"Scaled modeled solar to capacity: {capacity_mw:.1f} MW | "
        f"Observed peak: {hourly_avg.max():.1f} MW | "
        f"Day length: {day_length:.1f} h"
    )

    return modeled

def compute_curtailment(df_power: pd.Series, grid_limit_frac: float, capacity_mw: float):
    """
    For each hour, compute allowed export = grid_limit_frac * capacity_mw,
    curtailed = max(0, generation - allowed_export).
    Returns curtailed series (MW) and daily totals (MWh).
    """
    allowed_export = grid_limit_frac * capacity_mw
    curtailed = (df_power - allowed_export).clip(lower=0.0)
    # For each day sum curtailed values (hourly MW equals MWh for that hour)
    curtailed_daily = curtailed.resample("D").sum()
    produced_daily = df_power.resample("D").sum()
    possible_daily = pd.Series(capacity_mw*24, index=produced_daily.index)  # theoretical if full capacity every hour (not used in percentages typically)
    # percent lost relative to produced (or relative to potential?) We'll compute relative to produced daily energy
    pct_lost = 100.0 * (curtailed_daily / produced_daily.clip(lower=1e-9))
    return curtailed, curtailed_daily, pct_lost, allowed_export


# ---------------------------
# Simulation of data center & battery
# ---------------------------

def simulate_colocation(df_timeindex: pd.DatetimeIndex,
                         solar_generation: pd.Series,
                         grid_limit_frac: float,
                         capacity_mw: float,
                         dc_critical_mw: float,
                         dc_flexible_max_mw: float,
                         battery_capacity_mwh: float):
    """
    Simulate hourly for a single grid_limit_frac scenario.

    Rules / priority:
    1. Allowed export to grid = grid_limit_frac * capacity_mw. Any generation above that is 'excess'.
    2. Without colocated loads/battery, excess is curtailed.
    3. With data center:
        - Data center takes its CRITICAL_LOAD always (served from grid or solar or battery — for this simulation we only track consumption, not grid import).
        - During daytime hours when excess exists, flexible load can absorb up to dc_flexible_max_mw of excess each hour. Flexible load is assumed schedulable and runs only if excess is available (we prefer to run flexible load during day to use curtailed energy).
    4. Battery charges from remaining excess after data center flexible absorption.
       Charging is limited by:
         - remaining excess power
         - battery charge power limit (BATTERY_CHARGE_RATE)
         - remaining energy capacity (battery_capacity_mwh - SOC)
    5. At night (18:00–06:00 inclusive hours), solar_generation is zero and the
       battery discharges to support data center demand (critical + flexible),
       limited by:
         - state of charge (SOC)
         - discharge power limit (BATTERY_DISCHARGE_RATE)
         - discharge efficiency (BATTERY_DISCHARGE_EFF)
    6. Battery charging stores energy_in (MWh) and effective stored energy available for discharge later is energy_in * efficiency (round-trip).
    7. We track battery state-of-charge (SOC) in MWh.

    Returns a dict with hourly time series for:
     - curtailed_baseline (no DC/Batt)
     - curtailed_with_dc
     - curtailed_with_dc_batt
     - dc_served_energy (MWh)
     - battery_soc (MWh)
     - battery_charged_energy_total, battery_discharged_energy_total, battery_cycles_estimate
    """
    # Setup series containers
    index = df_timeindex
    n = len(index)
    # Hourly arrays
    gen = solar_generation.reindex(index).fillna(0.0).astype(float)  # MW
    allowed_export = grid_limit_frac * capacity_mw

    # Baseline curtailed (no DC or battery)
    curtailed_baseline = (gen - allowed_export).clip(lower=0.0)  # MW curtailed per hour
    # Initialize others
    curtailed_with_dc = np.zeros(n)  # MW
    curtailed_with_dc_batt = np.zeros(n)  # MW
    dc_served = np.zeros(n)  # MW consumed by data center in that hour (total)
    battery_soc = np.zeros(n)  # MWh at end of hour
    battery_charged = np.zeros(n)  # MWh charged this hour
    battery_discharged = np.zeros(n)  # MWh discharged this hour

    soc = 0.0  # initial SOC MWh

    # Helper: hour-of-day
    hours = index.hour

    for i, ts in enumerate(index):
        hour = hours[i]
        gen_i = gen.iloc[i]  # MW available this hour
        # Allowed export to grid (MW). Any gen above this is available to absorb (excess)
        excess = max(0.0, gen_i - allowed_export)
        # Curtailment baseline is excess (if not absorbed)
        # Scenario WITH DC (but no battery): DC absorbs up to flexible_max of excess
        dc_absorb = min(excess, dc_flexible_max_mw)
        curtailed_with_dc[i] = max(0.0, excess - dc_absorb)
        # Data center consumption this hour:
        # The datacenter always has critical load. Flexible portion runs only when absorbing curtailed or supported by battery.
        # During day (gen > 0) flexible is served from excess (dc_absorb). During night, flexible will be served from battery if available (below).
        # For daytime we'll set dc_served = critical + absorbed flexible
        # For nighttime handled below.
        # Start with critical load always required:
        dc_this_hour = dc_critical_mw
        # If absorbing some flexible this hour (daytime)
        dc_this_hour += dc_absorb

        # Battery logic for "with battery" scenario:
        # First, try to absorb remaining excess after data center flexible load into battery
        remaining_excess_after_dc = max(0.0, excess - dc_absorb)
        # energy to store (MWh) since each hour is 1 hour, MW == MWh
        energy_to_store = remaining_excess_after_dc  # MWh for this hour (available to charge)
        # Space available in battery (MWh)
        space = max(0.0, battery_capacity_mwh - soc)

        # Apply charge power limit (MW) and space limit (MWh)
        charge_power_limited = min(energy_to_store, BATTERY_CHARGE_RATE)  # MWh this hour max by power limit
        actual_charge_from_excess = min(space / BATTERY_CHARGE_EFF if BATTERY_CHARGE_EFF>0 else 0.0, charge_power_limited)
        # actual_charge_from_excess = amount of energy (MWh) pulled from excess to send to charger
        # The amount that ends up stored = actual_charge_from_excess * BATTERY_CHARGE_EFF
        stored_energy = actual_charge_from_excess * BATTERY_CHARGE_EFF
        soc += stored_energy
        battery_charged[i] = actual_charge_from_excess  # MWh taken from excess (for bookkeeping)

        # After charging, curtailed_with_dc_batt is any leftover excess not used for dc_absorb or battery charge
        curtailed_with_dc_batt[i] = max(0.0, remaining_excess_after_dc - actual_charge_from_excess)

        if hour >= 18 or hour < 6:
            # Desired DC load (critical + flexible)
            desired_dc_load = dc_critical_mw + dc_flexible_max_mw

            # How much energy can battery deliver this hour considering stored SOC and discharge eff:
            max_energy_deliverable_by_soc = soc * BATTERY_DISCHARGE_EFF  # MWh available to deliver
            # And limit by discharge power
            max_energy_deliverable = min(max_energy_deliverable_by_soc, BATTERY_DISCHARGE_RATE)

            # Energy needed this hour (MWh) to fully serve desired DC load
            energy_needed = desired_dc_load

            energy_delivered = min(max_energy_deliverable, energy_needed)

            # Remove equivalent stored energy from soc (account for discharge efficiency)
            if BATTERY_DISCHARGE_EFF > 0:
                energy_drawn_from_soc = energy_delivered / BATTERY_DISCHARGE_EFF
            else:
                energy_drawn_from_soc = 0.0
            soc = max(0.0, soc - energy_drawn_from_soc)

            battery_discharged[i] = energy_delivered  # MWh delivered to DC
            # Data center served by battery this hour (MWh)
            # But we also allow grid to supply the remainder if needed; here we report how much dc served by battery + direct (daytime) absorption earlier.
            # For the "with battery" scenario, we consider dc_served equal to battery-delivered + any daytime absorption (which we've accounted for in dc_this_hour)
            # Here we set dc_this_hour as the energy delivered from battery (if any) plus any direct (there's no generation at night).
            # We'll set dc_this_hour to energy_delivered (MWh) which equals MW for this hour, but ensure critical minimum is met either from battery or grid.
            # For bookkeeping we set dc_this_hour to min(energy_delivered, desired_dc_load) because any shortfall is served by grid (not counted as battery)
            dc_this_hour = energy_delivered
            # any shortfall is assumed supplied from grid (not counted here)
        # Store arrays
        dc_served[i] = dc_this_hour
        battery_soc[i] = soc

    # Convert MW arrays to pandas Series (MWh per hour)
    series_index = index
    result = {
        "curtailed_baseline": pd.Series(curtailed_baseline.values, index=series_index),
        "curtailed_with_dc": pd.Series(curtailed_with_dc, index=series_index),
        "curtailed_with_dc_batt": pd.Series(curtailed_with_dc_batt, index=series_index),
        "dc_served_MW": pd.Series(dc_served, index=series_index),  # MW per hour (== MWh)
        "battery_soc_MWh": pd.Series(battery_soc, index=series_index),
        "battery_charged_MWh": pd.Series(battery_charged, index=series_index),
        "battery_discharged_MWh": pd.Series(battery_discharged, index=series_index),
    }

    # Totals & simple cycle estimate: total charged / battery_capacity approximates cycles (overestimate if partial)
    # battery_charged currently stored the energy pulled from excess (MWh); stored energy (after charge eff) = sum(battery_charged * charge_eff)
    total_drawn_from_excess = result["battery_charged_MWh"].sum()
    total_stored = (result["battery_charged_MWh"] * BATTERY_CHARGE_EFF).sum()  # MWh actually stored after charging losses
    total_discharged = result["battery_discharged_MWh"].sum()  # MWh delivered to loads
    cycle_estimate = min(total_stored / battery_capacity_mwh, total_discharged / battery_capacity_mwh) if battery_capacity_mwh > 0 else 0.0
    result["battery_total_drawn_from_excess_MWh"] = total_drawn_from_excess
    result["battery_total_stored_MWh"] = total_stored
    result["battery_total_discharged_MWh"] = total_discharged
    result["battery_cycles_estimate"] = cycle_estimate
    result["battery_total_discharged_MWh"] = total_discharged
    result["battery_cycles_estimate"] = cycle_estimate

    return result


# ---------------------------
# Higher-level experiment driver
# ---------------------------

def run_all_simulations(df: pd.DataFrame):
    """
    Orchestrate the full workflow:
    - Fit sine model scaled to SOLAR_CAPACITY
    - For each grid limit fraction:
        * compute baseline curtailment
        * simulate colocation with DC only
        * simulate colocation with DC + battery
    - Produce plots and summary table
    """
    print("Fitting smooth sine model to average daily pattern and scaling to capacity...")
    # --- Handle both possible column names: "power_MW" or "power" ---
    if "power_MW" in df.columns:
        solar_col = "power_MW"
    elif "power" in df.columns:
        solar_col = "power"
    else:
        raise ValueError(f"No valid power column found in df: {df.columns.tolist()}")

    # --- Fit smooth sine model ---
    modeled = fit_sine_model(df[[solar_col]].rename(columns={solar_col: "power_MW"}), SOLAR_CAPACITY)

    # Debug print (optional but helpful)
    print(f"Modeled solar gen range: min={modeled.min():.2f} MW, max={modeled.max():.2f} MW")

    # --- Apply simple day-to-day variation to modeled output ---
    # Build reproducible random daily multipliers with small sigma (clip to avoid negative/absurd values)
    days = pd.Index(modeled.index.normalize().unique())
    rng = np.random.default_rng(DAILY_VARIATION_SEED)
    daily_factors = pd.Series(rng.normal(loc=1.0, scale=DAILY_VARIATION_STD, size=len(days)), index=days)
    daily_factors = daily_factors.clip(lower=1.0 - 3*DAILY_VARIATION_STD, upper=1.0 + 3*DAILY_VARIATION_STD)

    # Apply factor per day
    modeled = modeled.copy()
    for day, factor in daily_factors.items():
        mask = modeled.index.normalize() == day
        modeled.loc[mask] = modeled.loc[mask] * factor

    print(f"Applied day-to-day variation (std={DAILY_VARIATION_STD}) — sample day factors head:\n{daily_factors.head()}")

    # To keep realistic day/night observed pattern, zero modeled during hours where mean observed is near zero
    # (but our fit already does that). For safety, force 0 between 18:00 - 06:00
    modeled.loc[(modeled.index.hour >= 18) | (modeled.index.hour < 6)] = 0.0


    # Plot actual vs modeled for the first 3 days for a quick visual
    plt.figure(figsize=(12, 4))
    # Pick up to first 72 hours
    sample_end = min(len(df), 72)
    plt.plot(df.index[:sample_end], df["power_MW"].iloc[:sample_end], label="Observed power (MW)")
    plt.plot(modeled.index[:sample_end], modeled.iloc[:sample_end], label="Modeled smooth solar (MW)", linestyle="--")
    plt.legend()
    plt.xlabel("Time")
    plt.ylabel("Power (MW)")
    plt.title("Observed vs. Modeled Smooth Solar Output (first 72 hours)")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # 1-day sample plot 06:00-18:00
    sample_day = df.index.normalize().unique()[0] if PLOT_DAY_SAMPLE is None else pd.Timestamp(PLOT_DAY_SAMPLE)
    plot_one_day(df, day_timestamp=sample_day)

     # Run experiments for each grid limit
    summary_rows = []
    results_per_limit = {}

    FLEX_LOADS = [0, 200, 400, 600]      # MW flexible data center max
    BATTERIES = [0, 100, 200, 500]    # MWh battery capacities

    for frac in GRID_LIMIT_FRACS:
        print(f"\nSimulating grid export limit = {frac*100:.0f}% of capacity ({frac*SOLAR_CAPACITY:.1f} MW)...")
        # Precompute baseline curtailment once per frac
        curtailed, curtailed_daily, pct_lost, allowed_export = compute_curtailment(modeled, frac, SOLAR_CAPACITY)
        avg_daily_curtailed_baseline = curtailed_daily.mean()
        avg_daily_produced = df["power_MW"].resample("D").sum().mean()

        # Loop over DC flex and battery combos and append summary rows per combo
        for dc_flex in FLEX_LOADS:
            for batt_cap in BATTERIES:
                print(f"  Running: GridLimit={int(frac*100)}%, Flex={dc_flex}MW, Batt={batt_cap}MWh")
                sim = simulate_colocation(
                    df.index, modeled, frac, SOLAR_CAPACITY,
                    DATACENTER_CRITICAL_LOAD, dc_flex,
                    batt_cap, #BATTERY_EFFICIENCY
                )

                # Aggregate daily totals for this combo
                curtailed_with_dc_daily = sim["curtailed_with_dc"].resample("D").sum()
                curtailed_with_dc_batt_daily = sim["curtailed_with_dc_batt"].resample("D").sum()
                dc_served_daily = sim["dc_served_MW"].resample("D").sum()

                avg_curtailed_dc = curtailed_with_dc_daily.mean()
                avg_curtailed_dc_batt = curtailed_with_dc_batt_daily.mean()
                avg_dc_energy = dc_served_daily.mean()

                reduction_pct_dc = 100.0 * (avg_daily_curtailed_baseline - avg_curtailed_dc) / avg_daily_curtailed_baseline if avg_daily_curtailed_baseline>0 else 0.0
                reduction_pct_dc_batt = 100.0 * (avg_daily_curtailed_baseline - avg_curtailed_dc_batt) / avg_daily_curtailed_baseline if avg_daily_curtailed_baseline>0 else 0.0

                # Store summary row FOR THIS COMBO
                summary_rows.append({
                    "Scenario": "Baseline (no DC/Batt)",
                    "Grid_Limit_frac": frac,
                    "Curtailed_MWh": avg_daily_curtailed_baseline,
                    "Reduction_pct": 0.0,
                    "DataCenter_MWh": 0.0,
                    "Flex_Load_MW": dc_flex,
                    "Battery_MWh": batt_cap,
                })
                summary_rows.append({
                    "Scenario": "With Data Center",
                    "Grid_Limit_frac": frac,
                    "Curtailed_MWh": avg_curtailed_dc,
                    "Reduction_pct": reduction_pct_dc,
                    "DataCenter_MWh": avg_dc_energy,
                    "Flex_Load_MW": dc_flex,
                    "Battery_MWh": batt_cap,
                })
                summary_rows.append({
                    "Scenario": "With Data Center + Battery",
                    "Grid_Limit_frac": frac,
                    "Curtailed_MWh": avg_curtailed_dc_batt,
                    "Reduction_pct": reduction_pct_dc_batt,
                    "DataCenter_MWh": avg_dc_energy,
                    "Flex_Load_MW": dc_flex,
                    "Battery_MWh": batt_cap,
                })

                # Save detailed results for this specific combo keyed by tuple
                results_per_limit[(frac, dc_flex, batt_cap)] = {
                    "modeled": modeled,
                    "curtailed_baseline": curtailed,
                    "sim": sim,
                    "avg_daily_curtailed_baseline": avg_daily_curtailed_baseline,
                    "avg_curtailed_dc": avg_curtailed_dc,
                    "avg_curtailed_dc_batt": avg_curtailed_dc_batt,
                    "avg_dc_energy": avg_dc_energy,
                }

        # Save full results for plotting details per fraction
        results_per_limit[frac] = {
            "modeled": modeled,
            "curtailed_baseline": curtailed,
            "sim": sim,
            "avg_daily_curtailed_baseline": avg_daily_curtailed_baseline,
            "avg_curtailed_dc": avg_curtailed_dc,
            "avg_curtailed_dc_batt": avg_curtailed_dc_batt,
            "avg_dc_energy": avg_dc_energy,
        }

    # Convert summary rows to DataFrame and print
    summary_df = pd.DataFrame(summary_rows)
    # include Flex_Load_MW and Battery_MWh in the ordering so pivot_table works
    summary_df = summary_df[[
        "Scenario", "Grid_Limit_frac", "Flex_Load_MW", "Battery_MWh",
        "Curtailed_MWh", "Reduction_pct", "DataCenter_MWh"
    ]]

    print("\nSUMMARY TABLE (averaged per day across dataset):")
    print(summary_df.to_string(index=False, float_format="{:,.2f}".format))

    import seaborn as sns

    subset = summary_df[summary_df["Scenario"] == "With Data Center + Battery"]

    print("Summary DF columns:", summary_df.columns.tolist())
    print(summary_df.head())

    for frac in sorted(subset["Grid_Limit_frac"].unique()):
        pivot = subset[subset["Grid_Limit_frac"] == frac].pivot_table(
            index="Flex_Load_MW", columns="Battery_MWh", values="Curtailed_MWh"
        )

        plt.figure(figsize=(6,4))
        sns.heatmap(pivot, annot=True, fmt=".0f", cmap="YlGnBu")
        plt.title(f"Curtailment (MWh/day) for Grid Limit = {int(frac*100)}%")
        plt.xlabel("Battery Capacity (MWh)")
        plt.ylabel("Flexible Load (MW)")
        plt.tight_layout()
        plt.show()

    # Plot curtailment comparisons (bar chart) for each grid limit and scenario
    # We'll plot baseline vs DC vs DC+Battery average curtailed MWh
    fracs = GRID_LIMIT_FRACS
    baseline_vals = [results_per_limit[f]["avg_daily_curtailed_baseline"] for f in fracs]
    dc_vals = [results_per_limit[f]["avg_curtailed_dc"] for f in fracs]
    dc_batt_vals = [results_per_limit[f]["avg_curtailed_dc_batt"] for f in fracs]

    x = np.arange(len(fracs))
    width = 0.25

    print("\n=== Curtailment summary preview ===")
    print(summary_df.head())

    # Extract mean values directly from the summary table
    mean_dc = summary_df.loc[summary_df["Scenario"] == "With Data Center", "Curtailed_MWh"].mean()
    mean_dc_batt = summary_df.loc[summary_df["Scenario"] == "With Data Center + Battery", "Curtailed_MWh"].mean()

    print(f"With data center mean curtailed energy (MWh/day): {mean_dc:.2f}")
    print(f"With data center + battery mean curtailed energy (MWh/day): {mean_dc_batt:.2f}")
    print("====================================\n")



    plt.figure(figsize=(10, 5))
    plt.bar(x - width, baseline_vals, width=width, label="Baseline curtailed (MWh/day)")
    plt.bar(x, dc_vals, width=width, label="With Data Center")
    plt.bar(x + width, dc_batt_vals, width=width, label="With Data Center + Battery")
    plt.xlabel("Grid export limit fraction")
    plt.xticks(x, [f"{int(f*100)}%" for f in fracs])
    plt.ylabel("Average curtailed energy (MWh/day)")
    plt.title("Curtailment comparison across grid export limits")
    plt.legend()
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.show()

    # Show 24-hour cycle plots for the first grid limit as example: solar, battery SOC, DC consumption
    example_frac = fracs[0]
    print(f"\nPlotting 24-hour behavior example for grid limit {example_frac*100:.0f}% (first available day)...")
    res = results_per_limit[example_frac]
    # pick one representative day: first day in data
    first_day = df.index.normalize().unique()[0]
    mask_24 = (res["modeled"].index >= first_day) & (res["modeled"].index < first_day + pd.Timedelta(days=1))
    t = res["modeled"].index[mask_24]
    fig, ax = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    ax[0].plot(t, res["modeled"].loc[mask_24], label="Modeled solar (MW)")
    ax[0].plot(t, df["power_MW"].loc[mask_24], label="Observed (MW)", alpha=0.6)
    ax[0].set_ylabel("Power (MW)")
    ax[0].legend()
    ax[0].grid(True)

    ax[1].plot(t, res["sim"]["battery_soc_MWh"].loc[mask_24], label="Battery SOC (MWh)")
    ax[1].set_ylabel("Battery SOC (MWh)")
    ax[1].legend()
    ax[1].grid(True)

    ax[2].plot(t, res["sim"]["dc_served_MW"].loc[mask_24], label="Data center served (MW)")
    ax[2].set_ylabel("Data Center (MW)")
    ax[2].set_xlabel("Time")
    ax[2].legend()
    ax[2].grid(True)

    plt.suptitle(f"24-hour cycle example (day {first_day.date()}) — grid limit {int(example_frac*100)}%")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

    # Print summary key results in plain text
    print("\nKey plain-text summaries:")
    for frac in fracs:
        r = results_per_limit[frac]
        print(f"- Grid limit {int(frac*100)}% ({frac*SOLAR_CAPACITY:.1f} MW allowed):")
        print(f"  * Avg curtailed baseline (MWh/day): {r['avg_daily_curtailed_baseline']:.2f}")
        print(f"  * Avg curtailed with DC (MWh/day): {r['avg_curtailed_dc']:.2f}")
        print(f"  * Avg curtailed with DC+Batt (MWh/day): {r['avg_curtailed_dc_batt']:.2f}")
        print(f"  * Avg DC energy from curtailed/batt (MWh/day): {r['avg_dc_energy']:.2f}")
        print("")

    return summary_df, results_per_limit


# ---------------------------
# Main execution
# ---------------------------

def main():
    print("=== Solar Curtailment & Colocation Simulator ===")
    print(f"Loading data from: {DATA_PATH}")
    df = load_data(DATA_PATH)
    print(f"Data loaded. Time range: {df.index.min()} to {df.index.max()}")
    print(f"Total hours loaded: {len(df)}")
    # Quick check: ensure at least some daytime values exist
    if df["power_MW"].max() <= 0:
        print("WARNING: Estimated or observed power output is zero across the dataset. Check GHI or power columns.")
    # Run simulations & plotting
    summary_df, results = run_all_simulations(df)
    # Save summary to CSV for convenience
    out_path = Path("simulation_summary.csv")
    summary_df.to_csv(out_path, index=False)
    print(f"Summary table saved to {out_path.resolve()}")
    print("Script complete.")


if __name__ == "__main__":
    main()
