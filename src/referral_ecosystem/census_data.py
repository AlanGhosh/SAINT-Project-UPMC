import os
import json
import zipfile
import io
import requests
import pandas as pd
import numpy as np
import shapefile

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")

census_data_file = os.path.join(out_dir, "Census Data.csv")
tract_geojson_file = os.path.join(cache_dir, "Tract Geometry.json")
zip_geojson_file = os.path.join(cache_dir, "Zip Geometry.json")

zip_shp_cache = os.path.join(cache_dir, "zcta_shapefile")
tract_shp_cache = os.path.join(cache_dir, "tract_shapefile")

ACS_URL = "https://api.census.gov/data/2020/acs/acs5"
ZCTA_CROSSWALK_URL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"
TRACT_SHP_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_tract_500k.zip"
ZIP_SHP_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"




def get_target_zips(df: pd.DataFrame) -> set:
    """
    Extract the set of unique 5-digit zip codes from patient visit data.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain column: Dept Zip.

    Returns
    -------
    set of str
        Zero-padded 5-digit zip code strings.
    """

    return set(df['Dept Zip'].astype(str).str.zfill(5).unique())

def get_zip_geojson(target_zips: set) -> dict:
    """
    Build a GeoJSON FeatureCollection for the target zip codes from the
    national ZCTA shapefile.

    Downloads and caches the shapefile on first run. Subsequent runs load
    from the cached GeoJSON file.

    Parameters
    ----------
    target_zips : set of str
        Zip codes to include in the GeoJSON.

    Returns
    -------
    dict
        GeoJSON FeatureCollection with one feature per zip code.
    """

    if os.path.exists(zip_geojson_file):
        print("Zip GeoJSON found. Skipping shapefile processing.")
        with open(zip_geojson_file, 'r') as f:
            return json.load(f)

    if not os.path.exists(zip_shp_cache) or not os.listdir(zip_shp_cache):
        print("Downloading national ZCTA shapefile...")
        download_shapefile(ZIP_SHP_URL, zip_shp_cache)

    shp_file = next(f for f in os.listdir(zip_shp_cache) if f.endswith('.shp'))
    sf = shapefile.Reader(os.path.join(zip_shp_cache, shp_file))
    fields = [f[0] for f in sf.fields[1:]]

    print("Building zip GeoJSON...")
    features = []
    for rec, shape in zip(sf.records(), sf.shapes()):
        row = dict(zip(fields, rec))
        zcta = row.get('ZCTA5CE20', '')
        if zcta not in target_zips:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "ZCTA5CE20": zcta,
            },
            "geometry": shapefile.Shape.__geo_interface__.fget(shape)
        })

    geojson = {"type": "FeatureCollection", "features": features}
    with open(zip_geojson_file, 'w') as f:
        json.dump(geojson, f)
    print(f"  {len(features)} zip boundaries saved.")
    return geojson


def get_county_fips(target_zips: set) -> set:
    """
    Derive the set of county FIPS codes that contain the target zip codes
    using the Census ZCTA-to-county crosswalk.

    Parameters
    ----------
    target_zips : set of str
        5-digit zip code strings.

    Returns
    -------
    set of str
        5-digit county FIPS codes.
    """

    print("Fetching ZCTA-to-county crosswalk...")
    rel_df = pd.read_csv(ZCTA_CROSSWALK_URL, sep='|', dtype=str)
    matched = rel_df[rel_df['GEOID_ZCTA5_20'].isin(target_zips)]
    county_fips = set(matched['GEOID_COUNTY_20'].unique())
    print(f"  Found {len(county_fips)} counties covering {len(target_zips)} zip codes.")
    return county_fips


zip_geojson_file = os.path.join(cache_dir, "Zip Geometry.json")
ZIP_SHP_URL = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"

def get_zip_population(target_zips: set, year: int = 2023) -> pd.DataFrame:
    """
    Pull ACS 5-year population estimates for the target zip codes.

    Results are cached by year. On subsequent runs the cache is loaded
    directly.

    Parameters
    ----------
    target_zips : set of str
        Zip codes to retrieve population for.
    year : int, optional
        ACS 5-year estimate year. Default 2023.

    Returns
    -------
    pd.DataFrame
        Columns: Zip Code, Population.
    """

    cache_file = os.path.join(cache_dir, f"zip_population_{year}.json")
    if os.path.exists(cache_file):
        print(f"Zip population cache found for {year}. Skipping ACS API call.")
        with open(cache_file, 'r') as f:
            return pd.DataFrame(json.load(f))

    print(f"Fetching ZCTA populations from ACS 5-year API ({year})...")
    response = requests.get(
        f"https://api.census.gov/data/{year}/acs/acs5",
        params={"get": "B01003_001E,NAME", "for": "zip code tabulation area:*"}
    )
    response.raise_for_status()
    data = response.json()
    pop_df = pd.DataFrame(data[1:], columns=data[0])
    pop_df.columns = ['Population', 'Name', 'ZCTA']
    pop_df['Population'] = pd.to_numeric(pop_df['Population'])
    pop_df = pop_df[pop_df['ZCTA'].isin(target_zips)][['ZCTA', 'Population']]
    pop_df.columns = ['Zip Code', 'Population']
    pop_df['Population'] = pop_df['Population'].fillna(0).astype(int)

    with open(cache_file, 'w') as f:
        json.dump(pop_df.to_dict(orient='records'), f, indent=4)

    return pop_df


def build_zip_growth_df(pop_new: pd.DataFrame, pop_old: pd.DataFrame) -> pd.DataFrame:
    """
    Compute zip-level population percent change between two ACS snapshots.

    Writes results to CSV.

    Parameters
    ----------
    pop_new : pd.DataFrame
        Newer population estimates; columns: Zip Code, Population.
    pop_old : pd.DataFrame
        Older population estimates; columns: Zip Code, Population.

    Returns
    -------
    pd.DataFrame
        Columns: Zip Code, Population_new, Population_old,
        Population Change Pct.
    """

    growth_df = pop_new.merge(pop_old, on='Zip Code', suffixes=('_new', '_old'))
    growth_df['Population Change Pct'] = (
        (growth_df['Population_new'] - growth_df['Population_old']) /
        growth_df['Population_old'] * 100
    ).round(1)
    growth_df['Population Change Pct'] = growth_df['Population Change Pct'].replace([np.inf, -np.inf], 0).fillna(0)
    growth_df.to_csv(os.path.join(out_dir, "Zip Population Growth.csv"), index=False)
    return growth_df



def download_shapefile(url: str, extract_to: str):
    """
    Download a zipped shapefile from a URL and extract it to a local directory.

    Parameters
    ----------
    url : str
        Direct URL to the .zip shapefile.
    extract_to : str
        Local directory path to extract contents into.
    """

    os.makedirs(extract_to, exist_ok=True)
    print(f"  Downloading {url}...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()

    if not r.content[:4] == b'PK\x03\x04':  # zip magic bytes check
        raise ValueError(f"Response is not a zip file. Got: {r.content[:200]}")

    z = zipfile.ZipFile(io.BytesIO(r.content))
    z.extractall(extract_to)
    print(f"  Extracted to {extract_to}")


def get_tract_geojson(county_fips: set) -> dict:
    """
    Build a GeoJSON FeatureCollection for census tracts in the target
    counties from the national tract shapefile.

    Downloads and caches the shapefile on first run.

    Parameters
    ----------
    county_fips : set of str
        5-digit county FIPS codes.

    Returns
    -------
    dict
        GeoJSON FeatureCollection with one feature per census tract.
    """

    if os.path.exists(tract_geojson_file):
        print("Tract GeoJSON found. Skipping shapefile processing.")
        with open(tract_geojson_file, 'r') as f:
            return json.load(f)

    if not os.path.exists(tract_shp_cache) or not os.listdir(tract_shp_cache):
        print("Downloading national census tract shapefile...")
        download_shapefile(TRACT_SHP_URL, tract_shp_cache)

    shp_file = next(f for f in os.listdir(tract_shp_cache) if f.endswith('.shp'))
    sf = shapefile.Reader(os.path.join(tract_shp_cache, shp_file))
    fields = [f[0] for f in sf.fields[1:]]

    print("Building tract GeoJSON...")
    features = []
    for rec, shape in zip(sf.records(), sf.shapes()):
        row = dict(zip(fields, rec))
        full_fips = row['STATEFP'] + row['COUNTYFP']
        if full_fips not in county_fips:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "GEOID": row['GEOID'],
                "ALAND": row['ALAND']
            },
            "geometry": shapefile.Shape.__geo_interface__.fget(shape)
        })

    geojson = {"type": "FeatureCollection", "features": features}
    with open(tract_geojson_file, 'w') as f:
        json.dump(geojson, f)
    print(f"  {len(features)} census tracts saved.")
    return geojson


def get_tract_population(county_fips: set, year: int = 2020) -> pd.DataFrame:
    """
    Pull ACS 5-year tract-level population estimates for all tracts in the
    target counties.

    Parameters
    ----------
    county_fips : set of str
        5-digit county FIPS codes.
    year : int, optional
        ACS 5-year estimate year. Default 2020.

    Returns
    -------
    pd.DataFrame
        Columns: Population, Name, State, County, Tract, GEOID.
    """

    state_counties = {}
    for fips in county_fips:
        state = fips[:2]
        county = fips[2:]
        state_counties.setdefault(state, []).append(county)

    frames = []
    for state, counties in state_counties.items():
        for county in counties:
            params = {
                "get": "B01003_001E,NAME",
                "for": "tract:*",
                "in": f"state:{state} county:{county}"
            }
            try:
                r = requests.get(f"https://api.census.gov/data/{year}/acs/acs5", params=params)
                r.raise_for_status()
                data = r.json()
                df = pd.DataFrame(data[1:], columns=data[0])
                df.columns = ['Population', 'Name', 'State', 'County', 'Tract']
                frames.append(df)
            except Exception as e:
                print(f"  Warning: could not fetch tracts for state={state} county={county} year={year}: {e}")

    if not frames:
        return pd.DataFrame()

    tract_df = pd.concat(frames, ignore_index=True)
    tract_df['Population'] = pd.to_numeric(tract_df['Population'], errors='coerce').fillna(0).astype(int)
    tract_df['GEOID'] = tract_df['State'] + tract_df['County'] + tract_df['Tract']
    return tract_df


def build_growth_df(tract_df_new: pd.DataFrame, tract_df_old: pd.DataFrame) -> pd.DataFrame:
    """
    Compute census tract population percent change between two ACS snapshots.

    Tracts with zero population in the base year are assigned 0% change.
    Tracts missing from either year are dropped.

    Parameters
    ----------
    tract_df_new : pd.DataFrame
        Newer tract population data; must contain GEOID, Population.
    tract_df_old : pd.DataFrame
        Older tract population data; must contain GEOID, Population.

    Returns
    -------
    pd.DataFrame
        Columns: GEOID, Population_new, Population_old,
        Population Change Pct.
    """

    growth_df = tract_df_new[['GEOID', 'Population']].merge(
        tract_df_old[['GEOID', 'Population']],
        on='GEOID', suffixes=('_new', '_old')
    )
    growth_df['Population Change Pct'] = (
        (growth_df['Population_new'] - growth_df['Population_old']) / growth_df['Population_old'] * 100
    ).round(1)

    # infinity: old population was 0, division by zero
    growth_df['Population Change Pct'] = growth_df['Population Change Pct'].replace([np.inf, -np.inf], 0)

    # NaN: one or both years had no data for that tract
    growth_df['Population Change Pct'] = growth_df['Population Change Pct'].fillna(0)

    return growth_df



def build_tract_density(tract_df: pd.DataFrame, tract_geojson: dict) -> pd.DataFrame:
    """
    Compute population density and log-transformed density per census tract.

    Land area is sourced from the ALAND field in the tract GeoJSON.

    Parameters
    ----------
    tract_df : pd.DataFrame
        Must contain columns: GEOID, Population.
    tract_geojson : dict
        GeoJSON FeatureCollection from get_tract_geojson().

    Returns
    -------
    pd.DataFrame
        Input DataFrame with added columns: Area, Population Density,
        Pop Density Log.
    """

    area_lookup = {
        f['properties']['GEOID']: f['properties']['ALAND']
        for f in tract_geojson['features']
    }
    tract_df = tract_df.copy()
    tract_df['Area'] = tract_df['GEOID'].map(area_lookup)
    tract_df['Population Density'] = tract_df['Population'] / tract_df['Area']
    tract_df['Pop Density Log'] = np.log1p(tract_df['Population Density'])
    return tract_df


def get_zip_centroids(target_zips: set) -> pd.DataFrame:
    """
    Compute the geographic centroid (lat/lng) for each target zip code
    from the cached ZCTA shapefile bounding boxes.

    Parameters
    ----------
    target_zips : set of str
        Zip codes to compute centroids for.

    Returns
    -------
    pd.DataFrame
        Columns: Zip Code, lat, lng.
    """

    if not os.path.exists(zip_shp_cache) or not os.listdir(zip_shp_cache):
        print("Downloading national ZCTA shapefile for zip centroids...")
        download_shapefile(ZIP_SHP_URL, zip_shp_cache)

    shp_file = next(f for f in os.listdir(zip_shp_cache) if f.endswith('.shp'))
    sf = shapefile.Reader(os.path.join(zip_shp_cache, shp_file))
    fields = [f[0] for f in sf.fields[1:]]

    rows = []
    for rec, shape in zip(sf.records(), sf.shapes()):
        row = dict(zip(fields, rec))
        zcta = row.get('ZCTA5CE20', '')
        if zcta not in target_zips:
            continue
        bbox = shape.bbox  # [min_lng, min_lat, max_lng, max_lat]
        centroid_lat = (bbox[1] + bbox[3]) / 2
        centroid_lng = (bbox[0] + bbox[2]) / 2
        rows.append({'Zip Code': zcta, 'lat': centroid_lat, 'lng': centroid_lng})

    print(f"  {len(rows)} zip centroids computed.")
    return pd.DataFrame(rows)


def get_all_zips_in_counties(county_fips: set) -> set:
    """
    Return all zip codes that fall within the derived service area counties,
    not just those present in the patient dataset.

    Used to ensure visual completeness on maps (no blank zip polygons within
    the service area).

    Parameters
    ----------
    county_fips : set of str
        5-digit county FIPS codes.

    Returns
    -------
    set of str
        All 5-digit zip codes within the target counties.
    """

    print("Fetching all zip codes within service area counties...")
    rel_df = pd.read_csv(ZCTA_CROSSWALK_URL, sep='|', dtype=str)
    all_zips = set(rel_df[rel_df['GEOID_COUNTY_20'].isin(county_fips)]['GEOID_ZCTA5_20'].unique())
    print(f"  Found {len(all_zips)} zip codes across {len(county_fips)} counties.")
    return all_zips


def run(patients_df: pd.DataFrame):
    """
    Execute the full census data pipeline.

    Steps:
    1. Derive target zip codes and county FIPS from patient data.
    2. Expand to all zips within those counties for map coverage.
    3. Fetch tract and zip GeoJSON shapefiles.
    4. Pull ACS population estimates for 2023 and 2019/2020.
    5. Compute tract and zip population growth.
    6. Compute tract population density.
    7. Compute zip centroids for drive time analysis.

    Parameters
    ----------
    patients_df : pd.DataFrame
        Cleaned patient visit data from utils.run_data_clean().

    Returns
    -------
    tract_df : pd.DataFrame
        Tract population with density columns.
    tract_geojson : dict
        GeoJSON for census tracts in service area counties.
    target_zips : set of str
        Zip codes present in patient data.
    zip_population : pd.DataFrame
        2023 population estimates for all county zip codes.
    zip_growth_df : pd.DataFrame
        Zip-level population change 2020-2023.
    zip_geojson : dict
        GeoJSON for all zip codes in service area counties.
    zip_centroids : pd.DataFrame
        Centroids for target zip codes only.
    tract_growth_df : pd.DataFrame
        Tract-level population change 2019-2023.
    """

    target_zips = get_target_zips(patients_df)
    county_fips = get_county_fips(target_zips)
    all_zips = get_all_zips_in_counties(county_fips)

    tract_geojson = get_tract_geojson(county_fips)
    tract_df = get_tract_population(county_fips, year=2023)
    tract_df = build_tract_density(tract_df, tract_geojson)
    tract_df_old = get_tract_population(county_fips, year=2019)
    tract_growth_df = build_growth_df(tract_df, tract_df_old)

    # Use all_zips for maps (visual completeness)
    zip_geojson = get_zip_geojson(all_zips)
    zip_population = get_zip_population(all_zips, year=2023)
    zip_pop_2020 = get_zip_population(all_zips, year=2020)
    zip_growth_df = build_zip_growth_df(zip_population, zip_pop_2020)

    # Use target_zips for drive time analysis (grounded in actual data)
    zip_centroids = get_zip_centroids(target_zips)

    return tract_df, tract_geojson, target_zips, zip_population, zip_growth_df, zip_geojson, zip_centroids, tract_growth_df