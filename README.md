# UPMC Optimization — Project README

## Overview

This project contains two independent pipelines developed for UPMC to support physician deployment optimization and referral ecosystem analysis across western Pennsylvania.

**Physician Deployment Optimization** (`main_deployment.py`)
Establishes a baseline for intraday surgeon travel (windshield time and mileage) across UPMC facilities, assigns each surgeon a home hospital, home office, and home ASC, and computes an optimized baseline reflecting reduced travel under consolidated facility assignments.

**Referral Ecosystem Analysis** (`main_referral.py`)
Maps UPMC office visit volume and specialty distribution across the service area, analyzes patient access to specialty care by zip code, and builds routing tables showing the nearest specialty clinic for each urgent care and primary care anchor location. Produces a suite of interactive HTML maps and CSV deliverables.

---

## Project Structure

```
UPMC-Optimization/
│
├── main_deployment.py          # Entry point: physician deployment pipeline
├── main_referral.py            # Entry point: referral ecosystem pipeline
├── utils.py                    # Shared utilities: Excel loading, geocoding, data cleaning, and where specialty groupings are defined
├── config.py                   # API keys (not committed to version control)
├── params.py                   # Tunable analysis thresholds
│
├── src/
│   ├── physician_deployment/
│   │   ├── distance_matrix_generator.py   # Facility address lookup and pairwise drive matrix
│   │   ├── windshield_baseline.py         # Intraday travel baseline (all facilities)
│   │   ├── home_assignment.py             # Surgeon home hospital, office, and ASC assignment
│   │   └── new_baseline.py                # Optimized travel baseline (assigned facilities only)
│   │
│   └── referral_ecosystem/
│       ├── locations.py                   # UPMC and competitor facility geocoding
│       ├── census_data.py                 # ACS population, growth, and shapefile processing
│       ├── maps.py                        # Volume, specialty, and demographic map generation
│       ├── analysis.py                    # Drive time matrices, routing tables, access analysis
│       ├── ecosystem_map.py               # Full-region UC and PC routing map
│       ├── three_ecosystems.py            # Regional routing maps (North, Southwest, East)
│       └── visualizations.ipynb           # Includes several visualizations (these are not made automatically)
│   
│
├── data/                       # Input Excel files (not committed — see Data Requirements)
├── data_out/                   # CSV outputs written by the pipeline
├── cache/                      # Cached geocodes and API responses (auto-generated)
└── maps/                       # HTML map outputs (auto-generated)
```

---

## Setup

### 1. Dependencies

Install required Python packages:

```bash
pip install pandas numpy googlemaps openrouteservice folium branca requests shapefile msoffcrypto regex python-dotenv
```

### 2. API Keys

Create a `.env` file in the project root with the following:

```python
GOOGLE_MAPS_KEY = "your_google_maps_api_key"
ORS_API_KEY = "your_openrouteservice_api_key"
```

The Google Maps key requires the following APIs enabled: Geocoding API, Distance Matrix API, and Places API (New). 
The OpenRouteService key is used for the office-to-office drive time matrix (free tier supported).

`config.py` loads these values automatically at runtime. Never commit `.env` to version control: it is listed in `.gitignore`.

### 3. Data Files

Place all input Excel files in the `data/` directory before running. All files are password-protected and the pipeline will prompt for passwords at runtime.

**Required for both pipelines:**
| File | Description |
|------|-------------|
| Patient visits Excel file | Epic office visit data including department address, specialty, visit counts, and provider ID |

**Required for physician deployment only:**
| File | Description |
|------|-------------|
| Surgical data Excel file | Case-level surgical data with surgeon NPI, facility, procedure date, and case volume |
| Crosswalk Excel file | Maps surgeon NPIs to Epic provider IDs |

**Required for referral ecosystem only (placed directly in `data/`):**
| File | Description |
|------|-------------|
| `Hospital Locations.xlsx` | UPMC hospital names and addresses |
| `ASC Data.xlsx` | UPMC ASC addresses |
| `Competitor Data.xlsx` | AHN and WVU facility addresses |
| `2024.12.05 MedExpress UCC's part of JV.xlsx` | UPMC urgent care locations |

---

## How to Run

### Physician Deployment Pipeline

```bash
python main_deployment.py
```

The pipeline will prompt for three Excel files in order:

1. **Surgical data** — case-level OR data
2. **Crosswalk** — NPI to Epic provider ID mapping
3. **Patient visits** — office visit data

Surgeons with fewer than 30 total cases are excluded from the deployment analysis. Surgeons with fewer than 50 linked office visits are excluded from home office assignment.

### Referral Ecosystem Pipeline

```bash
python main_referral.py
```

The pipeline will prompt for one Excel file:

1. **Patient visits** — office visit data

All other data files (facility locations, shapefiles, census data) are loaded automatically from the `data/` directory or fetched from external APIs on first run.

---

## Outputs

### Physician Deployment (`data_out/`)

| File | Description |
|------|-------------|
| `Physician Durations Matrix.csv` | Pairwise driving duration matrix between all facilities (minutes) |
| `Physicians Distance Matrix.csv` | Pairwise driving distance matrix between all facilities (miles) |
| `Physicians Normalized Distances Matrix.csv` | Row-normalized distance matrix |
| `Windshield Time Baseline.csv` | Per-day travel detail for all multi-facility days (all facilities) |
| `Physician Work Breakdown.csv` | Per-surgeon summary of days worked, travel days, total hours and miles (baseline) |
| `Facility Specialty Weights.csv` | ASC x specialty case volume concentration matrix |
| `Physician Home Assignment.csv` | Home hospital, office, and ASC assignment per surgeon with volume percentages and tier |
| `Optimized Windshield Time Baseline.csv` | Per-day travel detail filtered to assigned facility pairs only |
| `Optimized Physician Work Breakdown.csv` | Per-surgeon summary under optimized assignment |

### Referral Ecosystem (`data_out/`)

| File | Description |
|------|-------------|
| `Office Data with Coordinates.csv` | Full cleaned patient visit dataset with geocoded coordinates |
| `Office Volume Data.csv` | Total and new patient visit volume aggregated by office location |
| `Office Volume by Specialty.csv` | Visit volume by office location and specialty grouping |
| `UPMC Hospital, ASC, Urgent Care Locations.csv` | Geocoded UPMC facility locations |
| `Competitor Locations.csv` | Geocoded AHN and WVU facility locations |
| `Office Visits in Community vs. Hospital.csv` | Office locations classified as hospital-based or community-based with visit volumes |
| `Office Visits in Community vs. Hospital (no pediatrics).csv` | Same as above excluding Pediatrics |
| `Top Offices by Visit Volume.csv` | All office locations ranked by total visit volume with location type |
| `Urgent Care to Office Matrix.csv` | Drive time matrix from each UC to each office location (minutes) |
| `Urgent Care to Office Drive Times by Specialty (weighted average).csv` | Volume-weighted average drive time from each UC to qualifying offices per specialty |
| `Zip Access by Specialty Matrix (nearest office).csv` | Minimum drive time from each zip code to nearest qualifying office per specialty |
| `Population Coverage Index.csv` | Specialty-level population access summary with tier breakdowns and largest desert zips |
| `UC Routing Table.csv` | Primary and backup specialty clinic per urgent care, with drive times and coordinates |
| `Office to Office Drive Times.csv` | Pairwise drive time matrix between all office locations (minutes, via ORS) |
| `PC to Specialty Routing Table.csv` | Primary and backup specialty clinic per primary care anchor, with drive times and coordinates |
| `Zip Population Growth.csv` | Zip-level population percent change 2020–2023 |

### Referral Ecosystem Maps (`maps/`)

| File | Description |
|------|-------------|
| `Specialty Map.html` | Office visit volume by specialty with toggleable specialty layers |
| `Volume Map.html` | Total and new patient visit volume by office location |
| `Tract Heat Map (Population).html` | Census tract population choropleth |
| `Census Tract Growth Map.html` | Census tract population change 2019–2023 |
| `Zip Code Population Growth Map.html` | Zip code population change 2020–2023 |
| `Ecosystem Map.html` | Full-region UC and PC routing map, layered by drive time tier |
| `Cranberry-Butler Map.html` | North region routing map (UC and PC to specialty) |
| `Southwest Map.html` | Southwest region routing map |
| `Irwin-Latrobe Map.html` | East region routing map |

---

## Caching

The `cache/` directory stores API responses and processed geodata to avoid redundant calls on subsequent runs. If a cache file exists, the pipeline loads it directly and skips the corresponding API call.

**Cache files include:** geocoded addresses, distance matrices, zip and tract GeoJSON, ACS population data, and ORS office-to-office times.

To force a re-run of any step, delete the corresponding cache file from `cache/`. To force a full re-run from scratch, delete the entire `cache/` directory — it will be recreated automatically.

**Do not delete cache files unless the underlying data has changed**, as re-running API calls consumes quota and time.

---

## Parameters

All tunable analysis thresholds are defined in `params.py`. Adjust these values before running if the qualifying criteria need to change.

```python
# Minimum visit count and location share for a UC routing destination to qualify
UC_MIN_VISITS = 300
UC_MIN_PCT = 15.0

# PC anchor qualification thresholds
PC_ANCHOR_MIN_VISITS = 3000
PC_ANCHOR_MIN_PCT = 40.0

# Specialty destination qualification thresholds for PC routing
PC_SPEC_MIN_VISITS = 300
PC_SPEC_MIN_PCT = 15.0

# Hospital/community classifier: max distance (miles) from a hospital to be labeled hospital-based
HOSP_PROXIMITY_THRESHOLD_MILES = 0.25

# General office qualification thresholds (access desert, coverage index, UC drives)
OFFICE_MIN_VISITS = 50
OFFICE_MIN_PCT = 5.0
```

After changing any threshold, delete the relevant output CSVs in `data_out/` so they are regenerated on the next run. Cached drive time matrices do not need to be deleted: they are inputs to the analysis, not outputs of it.
