# Solar Curtailment and Data Center Colocation Simulator

A Python-based simulation investigating how colocating a data center and battery energy storage with a large-scale solar farm can reduce renewable energy curtailment under grid export constraints.

Using Bhadla Solar Park in Rajasthan, India, as a case study, the project models solar generation, evaluates different grid export limits, and compares curtailment across baseline, data-center-only, and data-center-plus-battery scenarios.

## Overview

Solar farms can generate more electricity than the grid is able to accept, resulting in **solar energy curtailment**. Meanwhile, data centers require substantial amounts of electricity, and battery storage can retain surplus generation for later use.

This project explores how flexible data-center workloads and battery storage could make use of otherwise-curtailed solar energy.

The simulation investigates three scenarios:

1. **Baseline:** Solar generation is constrained by a grid export limit, and excess generation is curtailed.
2. **Data center:** A colocated data center absorbs some surplus generation through a configurable flexible load.
3. **Data center + battery:** Flexible data-center consumption is combined with battery storage to absorb additional surplus energy and supply stored energy to data-center loads during nighttime hours.

The objective is to quantify how these configurations affect average daily curtailment under different grid constraints.

## Key Features

- **Solar generation modelling:** Fits a smooth, sine-based daily generation profile to observed hourly solar data and scales it to the specified plant capacity.
- **Grid export constraints:** Simulates five export limits, ranging from 60% to 95% of the solar farm's nameplate capacity.
- **Flexible data-center workloads:** Tests multiple flexible load capacities to investigate how adjustable demand can absorb surplus solar generation.
- **Battery energy storage:** Models charging, discharging, energy capacity, power limits, and charge/discharge efficiency.
- **Daily generation variability:** Applies reproducible random variation to represent day-to-day changes in solar output.
- **Scenario comparison:** Calculates average daily curtailed energy and percentage reductions relative to the baseline.
- **Visual analysis:** Generates plots comparing observed and modelled generation, curtailment, battery state of charge, and the effects of different system configurations.
- **Exportable results:** Saves a summary of the simulation results to a CSV file for further analysis.

## Model Parameters

The principal parameters are defined at the beginning of `solar_model.py` and can be modified to investigate alternative system configurations.

| Parameter | Default value |
|---|---:|
| Solar farm capacity | 2,245 MW |
| Grid export limits | 60%, 70%, 80%, 90%, 95% |
| Critical data-center load | 100 MW |
| Flexible data-center load scenarios | 0, 200, 400, 600 MW |
| Battery capacity scenarios | 0, 100, 200, 500 MWh |
| Battery charge power limit | 500 MW |
| Battery discharge power limit | 500 MW |
| Battery round-trip efficiency | 90% |
| Daily generation variation | 5% standard deviation |
| Random seed | 42 |

The simulation evaluates combinations of grid export limits, flexible loads, and battery capacities. These parameters can be adjusted to examine different operating conditions.

## Methodology

### 1. Data ingestion and processing

The program loads hourly solar data from a CSV file or a ZIP archive containing CSV files. It supports solar irradiance data, expressed as Global Horizontal Irradiance (GHI), or a direct power-output column.

When power output is not supplied, it estimates generation using:


\[
P_{\mathrm{MW}}=\frac{GHI \times A \times \eta}{10^6}
\]

where:

- \(GHI\) is solar irradiance in W/m².
- \(A\) is the assumed collector area in m².
- \(\eta\) is panel efficiency.
- \(10^6\) converts watts to megawatts.

The resulting data is indexed by timestamp for hourly simulation.

### 2. Solar generation model

The program calculates the average generation profile for each hour of the day, normalizes the profile, and constructs a smooth sine-based curve.

The curve is scaled to the configured plant capacity and adjusted using seeded daily variation. Generation is then set to zero between 18:00 and 06:00.

This provides a simplified, repeatable representation of daily solar generation for comparing system configurations.

### 3. Curtailment calculation

For a grid export limit \(L\), the allowed export is:

\[
P_{\mathrm{allowed}}=L \times P_{\mathrm{capacity}}
\]

The baseline curtailed power is:

\[
P_{\mathrm{curtailed}}=
\max(0,P_{\mathrm{solar}}-P_{\mathrm{allowed}})
\]

Hourly curtailed power is aggregated into daily energy totals, expressed in MWh.

### 4. Data-center and battery simulation

For each configuration, the simulation models flexible data-center consumption and battery charging from surplus generation.

The battery is constrained by its available energy capacity, charge and discharge power limits, and charging/discharging efficiency. During nighttime hours, stored energy can support data-center demand.

The model records hourly curtailment, battery state of charge, charging and discharging energy, and data-center consumption.

### 5. Scenario evaluation

The program evaluates the following flexible-load capacities:

`0, 200, 400, 600 MW`

and battery capacities:

`0, 100, 200, 500 MWh`

For every grid export limit, the simulation compares the baseline against the data-center and data-center-plus-battery configurations.

Percentage curtailment reduction is calculated as:

\[
R=\frac{E_{\mathrm{baseline}}-E_{\mathrm{scenario}}}
{E_{\mathrm{baseline}}}\times100
\]

where \(E\) represents average daily curtailed energy.

## Visualizations and Outputs

Running the program generates several figures:

- **Observed vs. modelled solar generation:** Compares the input generation profile against the fitted model.
- **Daily solar generation:** Examines the observed daytime generation profile for a sample day.
- **Curtailment heatmaps:** Compare average daily curtailment across flexible-load and battery-capacity combinations for each grid export limit.
- **Curtailment comparison chart:** Compares the baseline, data-center-only, and data-center-plus-battery scenarios.
- **24-hour operating profile:** Displays solar generation, battery state of charge, and data-center consumption over a representative day.

The program also prints a summary table containing the scenario, grid export limit, flexible load, battery capacity, average daily curtailed energy, percentage reduction, and data-center energy.

The summary is saved as:

`simulation_summary.csv`

## Installation

### Requirements

- Python 3.10 or later recommended
- NumPy
- pandas
- Matplotlib
- Seaborn

Install the dependencies using:

```bash
pip install numpy pandas matplotlib seaborn
```

## Input Data

Place the input dataset at:

```text
data/
└── bhadla_data.zip
```

The default configuration expects `data/bhadla_data.zip`. Alternatively, `DATA_PATH` can be changed to point to a CSV file directly.

The archive should contain one or more CSV files with the following columns:

| Column | Requirement |
|---|---|
| `Year` | Required |
| `Month` | Required |
| `Day` | Required |
| `Hour` | Required |
| `GHI` | Required if power output is absent |
| `Power Output` | Required if GHI is absent |

Column names are matched case-insensitively. The loader skips the first two rows of each input CSV, so the input format must be compatible with that assumption.

**Data note:** The simulation's results depend on the quality and provenance of the input data. The generation model is a simplified representation of solar output and should not be interpreted as a validated operational forecast.

## Running the Simulation

From the project root directory, run:

```bash
python solar_model.py
```

The script will:

1. Load and process the input data.
2. Fit and scale the solar generation model.
3. Apply daily variability.
4. Run the scenario simulations.
5. Display the generated visualizations.
6. Print the summary statistics.
7. Save `simulation_summary.csv` in the project root.

## Project Structure

```text
solar-curtailment-simulator/
├── solar_model.py
├── data/
│   └── bhadla_data.zip
├── simulation_summary.csv
└── README.md
```

`data/extracted/` is created automatically when ZIP data is loaded. The summary CSV is generated when the simulation completes.

## Limitations and Future Improvements

The current implementation is an exploratory simulation rather than a complete electrical-grid or data-center operations model.

Potential improvements include:

- Incorporating actual solar plant output and validating the fitted generation curve against measured data.
- Modelling realistic cloud cover, seasonal variation, and weather-driven generation changes.
- Adding more detailed data-center workload scheduling, ramp-rate constraints, cooling demand, and critical-load requirements.
- Accounting explicitly for grid imports and the separation between solar-powered and grid-powered data-center consumption.
- Refining battery dispatch, including state-of-charge constraints, degradation, and more detailed efficiency accounting.
- Validating energy balances and comparing results against established energy-system modelling methods.

The model is intended to support comparative analysis of renewable energy utilization and the potential role of flexible computing demand and battery storage in reducing curtailment.

## Technologies

- **Python** — simulation and analysis
- **NumPy** — numerical computation and stochastic variation
- **pandas** — time-series processing and results aggregation
- **Matplotlib** — visualization
- **Seaborn** — curtailment heatmaps

---

*An exploratory energy-systems modelling project examining the intersection of renewable energy, battery storage, and data-center infrastructure.*