import os
import json
import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from config import GOOGLE_MAPS_KEY
from config import ORS_API_KEY
import googlemaps
import openrouteservice
import time
from params import (
    UC_MIN_VISITS,
    UC_MIN_PCT,
    PC_ANCHOR_MIN_VISITS,
    PC_ANCHOR_MIN_PCT,
    PC_SPEC_MIN_VISITS,
    PC_SPEC_MIN_PCT,
    HOSP_PROXIMITY_THRESHOLD_MILES,
    OFFICE_MIN_VISITS,
    OFFICE_MIN_PCT
)

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")
map_dir = os.path.join(base_dir, "maps")

uc_to_office_cache = os.path.join(cache_dir, "uc_to_office_times.json")
office_classifier_file = os.path.join(out_dir, "Office Visits in Community vs. Hospital.csv")
office_classifier_no_pediatrics_file = os.path.join(out_dir, "Office Visits in Community vs. Hospital (no pediatrics).csv")
sites_by_vol_file = os.path.join(out_dir, "Top Offices by Visit Volume.csv")
uc_to_office_time_matrix = os.path.join(out_dir, "Urgent Care to Office Matrix.csv")
uc_drives_file = os.path.join(out_dir, "Urgent Care to Office Drive Times by Specialty (weighted average).csv")
zip_to_office_cache = os.path.join(cache_dir, "zip_to_office_times.json")
zip_access_file = os.path.join(out_dir, "Zip Access by Specialty Matrix (nearest office).csv")
pop_coverage_file = os.path.join(out_dir, "Population Coverage Index.csv")
uc_routing_file = os.path.join(out_dir, "UC Routing Table.csv")
office_to_office_cache = os.path.join(cache_dir, "office_to_office_times.json")
office_to_office_file = os.path.join(out_dir, "Office to Office Drive Times.csv")
pc_routing_file = os.path.join(out_dir, "PC to Specialty Routing Table.csv")


# for hosp_community_classifier
def haversine(lat1, lng1, lat2, lng2):
    """
        Compute the distance in miles between two lat/lng points.

        Parameters
        ----------
        lat1, lng1 : float
            Coordinates of the first point.
        lat2, lng2 : float
            Coordinates of the second point.

        Returns
        -------
        float
            Distance in miles.
        """

    R = 3958.8  # Earth radius in miles
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def build_specialty_vol(patients_df):
    """
    Compute per-location specialty visit volumes and percentage of total
    location volume for each specialty.

    Used as a shared helper across analysis functions to avoid duplicating
    this aggregation. Filtering by min_visits and min_pct is intentionally
    left to the calling function, as different callers apply different
    thresholds.

    Parameters
    ----------
    patients_df : pd.DataFrame
        Cleaned patient visit data; must contain columns: Normalized Address,
        Specialty Grouping, Total Visits.

    Returns
    -------
    pd.DataFrame
        Columns: Normalized Address, Specialty Grouping, Total Visits,
        Location Total, Pct of Location.
    """

    specialty_vol = patients_df.groupby(
        ['Normalized Address', 'Specialty Grouping']
    )['Total Visits'].sum().reset_index()

    location_total = patients_df.groupby('Normalized Address')['Total Visits'].sum().reset_index()
    location_total.columns = ['Normalized Address', 'Location Total']
    specialty_vol = specialty_vol.merge(location_total, on='Normalized Address')
    specialty_vol['Pct of Location'] = specialty_vol['Total Visits'] / specialty_vol['Location Total'] * 100

    return specialty_vol


def hosp_community_classifier(offices, hospitals, patients_df, threshold_miles=HOSP_PROXIMITY_THRESHOLD_MILES):
    """
        Classify each office location as Hospital-based or Community-based by
        proximity to a known UPMC hospital.

        An office within threshold_miles of any hospital is labeled 'Hospital';
        all others are labeled 'Community'. Writes two CSVs: one with all
        specialties and one with Pediatrics excluded.

        # Requested deliverable — confirm if still needed

        Parameters
        ----------
        offices : pd.DataFrame
            Must contain columns: Normalized Address, lat, lng.
        hospitals : pd.DataFrame
            Must contain columns: Address, lat, lng.
        patients_df : pd.DataFrame
            Cleaned patient visit data used to aggregate visit volumes.
        threshold_miles : float, optional
            Distance threshold in miles for hospital-based classification.
            Default is 0.25.

        Returns
        -------
        pd.DataFrame
            offices DataFrame with added column: Location Type.
        """

    # offices needs: Normalized Address, lat, lng
    # hospitals needs: Address, lat, lng

    results = {}
    for _, office in offices.iterrows():
        is_hospital_based = False
        for _, hospital in hospitals.iterrows():
            dist = haversine(office['lat'], office['lng'], hospital['lat'], hospital['lng'])
            if dist <= threshold_miles:
                is_hospital_based = True
                break
        results[office['Normalized Address']] = 'Hospital' if is_hospital_based else 'Community'

    offices = offices.copy()
    offices['Location Type'] = offices['Normalized Address'].map(results)

    classified_df = patients_df.merge(
        offices[['Normalized Address', 'Location Type']],
        on='Normalized Address',
        how='left'
    )

    aggregated_results = classified_df.groupby(['Normalized Address','Location Type'])['Total Visits'].sum().reset_index()
    aggregated_results.to_csv(office_classifier_file)
    print("Office community/hospital classification file made.")

    summary = aggregated_results.groupby('Location Type')['Total Visits'].sum().reset_index()
    print("\nAggregated Results:\n",summary)


    pediatrics_removed = patients_df[patients_df['Specialty Grouping'] != 'Pediatrics']

    classified_df2 = pediatrics_removed.merge(
        offices[['Normalized Address', 'Location Type']],
        on='Normalized Address',
        how='left'
    )
    aggregated_results2 = classified_df2.groupby(['Normalized Address', 'Location Type'])['Total Visits'].sum().reset_index()
    aggregated_results2.to_csv(office_classifier_no_pediatrics_file)

    summary2 = aggregated_results2.groupby('Location Type')['Total Visits'].sum().reset_index()
    print("\nAggregated Results without Pediatrics:\n", summary2)

    return offices



def top_sites_by_volume(patients_df: pd.DataFrame, classified_offices: pd.DataFrame):
    """
        Rank all office locations by total visit volume and join location type.

        Writes results to CSV sorted descending by Total Visits.

        # Requested deliverable — confirm if still needed

        Parameters
        ----------
        patients_df : pd.DataFrame
            Cleaned patient visit data.
        classified_offices : pd.DataFrame
            Output of hosp_community_classifier(); must contain
            Normalized Address and Location Type.
        """

    volume = patients_df.groupby('Normalized Address')['Total Visits'].sum().reset_index()
    volume_sorted = volume.sort_values(by='Total Visits', ascending=False).reset_index(drop=True)

    final_df = pd.merge(volume_sorted, classified_offices[['Normalized Address', 'Location Type']], on='Normalized Address', how='left')
    final_df.to_csv(sites_by_vol_file, index=False)
    print("\nTop Offices by Volume file created")


def get_uc_to_office_times(urgent_cares: pd.DataFrame, offices: pd.DataFrame) -> pd.DataFrame:
    """
        Compute drive times in minutes from each urgent care to each office
        location using the Google Maps Distance Matrix API.

        Results are cached to disk. On subsequent runs the cache is loaded
        directly, skipping API calls. Also writes the full matrix to CSV.

        Parameters
        ----------
        urgent_cares : pd.DataFrame
            Must contain columns: Address, lat, lng.
        offices : pd.DataFrame
            Must contain columns: Normalized Address, lat, lng.

        Returns
        -------
        pd.DataFrame
            Matrix with UC addresses as index, office addresses as columns,
            values in minutes.
        """

    if os.path.exists(uc_to_office_cache):
        print("UC to office cache found. Skipping API call.")
        with open(uc_to_office_cache, 'r') as f:
            return pd.DataFrame(json.load(f)).T

    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)

    uc_list = urgent_cares[['Address', 'lat', 'lng']].dropna(subset=['lat', 'lng'])
    office_list = offices[['Normalized Address', 'lat', 'lng']].dropna(subset=['lat', 'lng'])

    office_coords = [{'lat': row['lat'], 'lng': row['lng']} for _, row in office_list.iterrows()]
    office_names = office_list['Normalized Address'].tolist()

    print(f"Computing drive times: {len(uc_list)} UCs x {len(office_list)} offices...")

    results = {}
    DEST_CHUNK_SIZE = 25

    for _, uc_row in uc_list.iterrows():
        uc_address = uc_row['Address']
        uc_coord = [{'lat': uc_row['lat'], 'lng': uc_row['lng']}]
        office_times = {}

        for j in range(0, len(office_coords), DEST_CHUNK_SIZE):
            dest_chunk = office_coords[j:j + DEST_CHUNK_SIZE]
            name_chunk = office_names[j:j + DEST_CHUNK_SIZE]
            try:
                response = gmaps.distance_matrix(
                    origins=uc_coord,
                    destinations=dest_chunk,
                    mode="driving",
                    departure_time="now",
                    traffic_model="best_guess"
                )
                if response['status'] == 'OK':
                    for name, el in zip(name_chunk, response['rows'][0]['elements']):
                        office_times[name] = (
                            el.get('duration_in_traffic', el['duration'])['value'] / 60
                            if el['status'] == 'OK' else None
                        )
            except Exception as e:
                print(f"  [ERROR] UC {uc_address}: {e}")
                for name in name_chunk:
                    office_times[name] = None

        results[uc_address] = office_times

    with open(uc_to_office_cache, 'w') as f:
        json.dump(results, f, indent=4)

    df = pd.DataFrame(results).T
    df.to_csv(uc_to_office_time_matrix)

    return df



def uc_to_office_drives_by_specialty(
    uc_to_office_times: pd.DataFrame,
    patients_df: pd.DataFrame,
    min_visits: int = OFFICE_MIN_VISITS,
    min_pct: float = OFFICE_MIN_PCT
) -> pd.DataFrame:
    """
    For each urgent care, compute the volume-weighted average drive time
    per specialty to qualifying office locations.

    Qualifying offices must meet both a minimum visit count and a minimum
    percentage of their total location volume for that specialty. Writes
    results to CSV.

    Parameters
    ----------
    uc_to_office_times : pd.DataFrame
        Drive time matrix from get_uc_to_office_times().
    patients_df : pd.DataFrame
        Cleaned patient visit data.
    min_visits : int, optional
        Minimum specialty visit count for an office to qualify. Default 50.
    min_pct : float, optional
        Minimum specialty visit share (%) of location total to qualify.
        Default 5.0.

    Returns
    -------
    pd.DataFrame
        One row per UC, one column per specialty, values in minutes.
    """
    specialty_vol = build_specialty_vol(patients_df)
    qualifying = specialty_vol[
        (specialty_vol['Total Visits'] >= min_visits) &
        (specialty_vol['Pct of Location'] >= min_pct)
        ]

    specialties = sorted(qualifying['Specialty Grouping'].unique())
    results = {uc: {} for uc in uc_to_office_times.index}

    for specialty in specialties:
        spec_df = qualifying[qualifying['Specialty Grouping'] == specialty]
        qualifying_offices = spec_df['Normalized Address'].tolist()
        valid_offices = [o for o in qualifying_offices if o in uc_to_office_times.columns]

        if not valid_offices:
            continue

        times_subset = uc_to_office_times[valid_offices]
        vol_lookup = spec_df.set_index('Normalized Address')['Total Visits']

        for uc_address in uc_to_office_times.index:
            uc_times = times_subset.loc[uc_address].dropna()
            if uc_times.empty:
                results[uc_address][specialty] = None
                continue

            aligned_vols = vol_lookup.reindex(uc_times.index).fillna(0)
            total_vol = aligned_vols.sum()

            if total_vol == 0:
                results[uc_address][specialty] = None
                continue

            weighted_avg = (uc_times * aligned_vols).sum() / total_vol
            results[uc_address][specialty] = round(weighted_avg, 1)

    result_df = pd.DataFrame(results).T
    result_df.index.name = 'UC Address'
    result_df = result_df[specialties]  # ensure consistent column order
    result_df.to_csv(uc_drives_file)

    return result_df


def get_zip_to_office_times(zip_centroids: pd.DataFrame, offices: pd.DataFrame) -> pd.DataFrame:
    """
        Compute drive times in minutes from each zip code centroid to each
        office location using the Google Maps Distance Matrix API.

        Results are cached to disk.

        Parameters
        ----------
        zip_centroids : pd.DataFrame
            Must contain columns: Zip Code, lat, lng.
        offices : pd.DataFrame
            Must contain columns: Normalized Address, lat, lng.

        Returns
        -------
        pd.DataFrame
            Matrix with zip codes as index, office addresses as columns,
            values in minutes.
        """

    if os.path.exists(zip_to_office_cache):
        print("Zip to office cache found. Skipping API call.")
        with open(zip_to_office_cache, 'r') as f:
            return pd.DataFrame(json.load(f)).T

    gmaps = googlemaps.Client(key=GOOGLE_MAPS_KEY)

    zip_list = zip_centroids.dropna(subset=['lat', 'lng'])
    office_list = offices[['Normalized Address', 'lat', 'lng']].dropna(subset=['lat', 'lng'])

    office_coords = [{'lat': row['lat'], 'lng': row['lng']} for _, row in office_list.iterrows()]
    office_names = office_list['Normalized Address'].tolist()

    print(f"Computing drive times: {len(zip_list)} zips x {len(office_list)} offices...")

    results = {}
    DEST_CHUNK_SIZE = 25

    for _, zip_row in zip_list.iterrows():
        zip_code = zip_row['Zip Code']
        zip_coord = [{'lat': zip_row['lat'], 'lng': zip_row['lng']}]
        office_times = {}

        for j in range(0, len(office_coords), DEST_CHUNK_SIZE):
            dest_chunk = office_coords[j:j + DEST_CHUNK_SIZE]
            name_chunk = office_names[j:j + DEST_CHUNK_SIZE]
            try:
                response = gmaps.distance_matrix(
                    origins=zip_coord,
                    destinations=dest_chunk,
                    mode="driving",
                    departure_time="now",
                    traffic_model="best_guess"
                )
                if response['status'] == 'OK':
                    for name, el in zip(name_chunk, response['rows'][0]['elements']):
                        office_times[name] = (
                            el.get('duration_in_traffic', el['duration'])['value'] / 60
                            if el['status'] == 'OK' else None
                        )
            except Exception as e:
                print(f"  [ERROR] Zip {zip_code}: {e}")
                for name in name_chunk:
                    office_times[name] = None

        results[zip_code] = office_times

    with open(zip_to_office_cache, 'w') as f:
        json.dump(results, f, indent=4)

    return pd.DataFrame(results).T


def zip_access_desert_analysis(
    zip_to_office_times: pd.DataFrame,
    patients_df: pd.DataFrame,
    zip_population: pd.DataFrame,
    min_visits: int = OFFICE_MIN_VISITS,
    min_pct: float = OFFICE_MIN_PCT
) -> pd.DataFrame:
    """
    For each zip code and qualifying specialty, find the minimum drive time
    to any qualifying office and classify into access tiers.

    Tiers: Good Access (<15 min), Moderate Access (15-30 min),
    Limited Access (30-45 min), Access Desert (>=45 min or no office).
    Writes a specialty x zip matrix with drive times and population to CSV.

    Parameters
    ----------
    zip_to_office_times : pd.DataFrame
        Drive time matrix from get_zip_to_office_times().
    patients_df : pd.DataFrame
        Cleaned patient visit data.
    zip_population : pd.DataFrame
        Must contain columns: Zip Code, Population.
    min_visits : int, optional
        Minimum visit count for an office to qualify per specialty. Default 50.
    min_pct : float, optional
        Minimum specialty visit share (%) of location total. Default 5.0.
    """

    specialty_vol = build_specialty_vol(patients_df)
    qualifying = specialty_vol[
        (specialty_vol['Total Visits'] >= min_visits) &
        (specialty_vol['Pct of Location'] >= min_pct)
        ]

    pop_lookup = zip_population.set_index('Zip Code')['Population']
    specialties = sorted(qualifying['Specialty Grouping'].unique())

    def classify_access(minutes):
        if pd.isna(minutes):
            return 'Access Desert'
        elif minutes < 15:
            return 'Good Access'
        elif minutes < 30:
            return 'Moderate Access'
        elif minutes < 45:
            return 'Limited Access'
        else:
            return 'Access Desert'

    rows = []
    for specialty in specialties:
        spec_df = qualifying[qualifying['Specialty Grouping'] == specialty]
        valid_offices = [o for o in spec_df['Normalized Address'].tolist() if o in zip_to_office_times.columns]

        if not valid_offices:
            continue

        times_subset = zip_to_office_times[valid_offices]

        for zip_code in zip_to_office_times.index:
            min_time = times_subset.loc[zip_code].dropna().min() if zip_code in zip_to_office_times.index else np.nan
            tier = classify_access(min_time)
            population = pop_lookup.get(zip_code, 0)
            rows.append({
                'Zip Code': zip_code,
                'Specialty': specialty,
                'Min Drive Time (min)': round(min_time, 1) if not pd.isna(min_time) else None,
                'Access Tier': tier,
                'Population': population
            })

    result_df = pd.DataFrame(rows)

    matrix = result_df.pivot(index='Zip Code', columns='Specialty', values='Min Drive Time (min)')
    matrix = matrix.join(zip_population.set_index('Zip Code')['Population'])
    matrix = matrix.sort_index()  # sorts by Zip Code ascending
    matrix = matrix.reset_index().set_index(['Zip Code', 'Population'])
    matrix.to_csv(zip_access_file)

    print("\nZip access desert analysis file created")


def population_coverage_index(
    zip_to_office_times: pd.DataFrame,
    patients_df: pd.DataFrame,
    zip_population: pd.DataFrame,
    classified_offices: pd.DataFrame,
    min_visits: int = OFFICE_MIN_VISITS,
    min_pct: float = OFFICE_MIN_PCT
) -> pd.DataFrame:
    """
    Build a specialty-level population coverage summary table.

    For each specialty, reports total and community office counts, the
    percentage of the service area population falling into each access
    tier, and the five largest access desert zip codes by population.
    Writes results to CSV.

    Parameters
    ----------
    zip_to_office_times : pd.DataFrame
        Drive time matrix from get_zip_to_office_times().
    patients_df : pd.DataFrame
        Cleaned patient visit data.
    zip_population : pd.DataFrame
        Must contain columns: Zip Code, Population.
    classified_offices : pd.DataFrame
        Output of hosp_community_classifier(); used to count community locations.
    min_visits : int, optional
        Minimum visit count for an office to qualify per specialty. Default 50.
    min_pct : float, optional
        Minimum specialty visit share (%) of location total. Default 5.0.
    """

    specialty_vol = build_specialty_vol(patients_df)
    qualifying = specialty_vol[
        (specialty_vol['Total Visits'] >= min_visits) &
        (specialty_vol['Pct of Location'] >= min_pct)
        ]

    community_offices = set(classified_offices[classified_offices['Location Type'] == 'Community']['Normalized Address'])
    pop_lookup = zip_population.set_index('Zip Code')['Population']

    zips_in_matrix = set(zip_to_office_times.index)
    pop_in_matrix = pop_lookup[pop_lookup.index.isin(zips_in_matrix)]
    total_population = pop_in_matrix.sum()
    specialties = sorted(qualifying['Specialty Grouping'].unique())

    rows = []
    for specialty in specialties:
        spec_df = qualifying[qualifying['Specialty Grouping'] == specialty]
        all_locs = spec_df['Normalized Address'].tolist()
        valid_offices = [o for o in all_locs if o in zip_to_office_times.columns]
        community_locs = [o for o in valid_offices if o in community_offices]

        if not valid_offices:
            continue

        times_subset = zip_to_office_times[valid_offices]

        tier_counts = {'Good Access': 0, 'Moderate Access': 0, 'Limited Access': 0, 'Access Desert': 0}
        desert_zips = []

        for zip_code in zip_to_office_times.index:
            min_time = times_subset.loc[zip_code].dropna().min() if not times_subset.loc[zip_code].dropna().empty else np.nan
            population = pop_lookup.get(zip_code, 0)

            if pd.isna(min_time) or min_time >= 45:
                tier_counts['Access Desert'] += population
                desert_zips.append((zip_code, population))
            elif min_time < 15:
                tier_counts['Good Access'] += population
            elif min_time < 30:
                tier_counts['Moderate Access'] += population
            else:
                tier_counts['Limited Access'] += population

        desert_zips_sorted = sorted(desert_zips, key=lambda x: x[1], reverse=True)[:5]
        desert_zip_str = ', '.join([f"{z} ({p:,})" for z, p in desert_zips_sorted])

        rows.append({
            'Specialty': specialty,
            '# Office Locations': len(all_locs),
            '# Community Locations': len(community_locs),
            'Good Access % (<15 min)': round(tier_counts['Good Access'] / total_population * 100, 1),
            'Moderate Access % (15-30 min)': round(tier_counts['Moderate Access'] / total_population * 100, 1),
            'Limited Access % (30-45 min)': round(tier_counts['Limited Access'] / total_population * 100, 1),
            'Access Desert % (>45 min)': round(tier_counts['Access Desert'] / total_population * 100, 1),
            'Largest Desert Zips (population)': desert_zip_str
        })

    result_df = pd.DataFrame(rows)
    result_df.to_csv(pop_coverage_file, index=False)
    print("\nPopulation coverage index file created")
    return result_df


def uc_routing_table(
    uc_to_office_times: pd.DataFrame,
    patients_df: pd.DataFrame,
    urgent_cares: pd.DataFrame,
    offices: pd.DataFrame,
    min_visits: int  =UC_MIN_VISITS,
    min_pct: float = UC_MIN_PCT
) -> pd.DataFrame:
    """
        Build the UC-to-specialty routing table assigning each urgent care a
        primary and backup specialty clinic based on minimum drive time.

        Qualifying destination offices must meet both the visit count and
        percentage-of-location thresholds for their specialty. Routing is
        purely drive-time based within the qualifying pool. Appends lat/lng
        coordinates for mapping. Writes results to CSV.

        Parameters
        ----------
        uc_to_office_times : pd.DataFrame
            Drive time matrix from get_uc_to_office_times().
        patients_df : pd.DataFrame
            Cleaned patient visit data.
        urgent_cares : pd.DataFrame
            Filtered urgent care locations; must contain Address, lat, lng.
        offices : pd.DataFrame
            Must contain columns: Normalized Address, lat, lng.
        min_visits : int, optional
            Minimum specialty visit count for a destination office to qualify.
            Default 100.
        min_pct : float, optional
            Minimum specialty visit share (%) of location total. Default 10.0.

        Returns
        -------
        pd.DataFrame
            One row per UC-specialty pair with primary and backup clinic,
            drive times, and coordinates.
        """

    specialty_vol = build_specialty_vol(patients_df)
    qualifying = specialty_vol[
        (specialty_vol['Total Visits'] >= min_visits) &
        (specialty_vol['Pct of Location'] >= min_pct)
        ]

    vol_lookup = qualifying.groupby('Normalized Address')['Total Visits'].sum()
    specialties = sorted(qualifying['Specialty Grouping'].unique())
    rows = []

    for specialty in specialties:
        spec_df = qualifying[qualifying['Specialty Grouping'] == specialty]
        valid_offices = [o for o in spec_df['Normalized Address'].tolist() if o in uc_to_office_times.columns]

        if not valid_offices:
            continue

        times_subset = uc_to_office_times[valid_offices]

        for uc_address in uc_to_office_times.index:
            uc_times = times_subset.loc[uc_address].dropna()
            if uc_times.empty:
                continue

            primary_clinic = uc_times.idxmin()
            primary_time = round(uc_times[primary_clinic], 1)

            remaining = uc_times.drop(index=primary_clinic)
            backup_clinic = remaining.idxmin() if not remaining.empty else None
            backup_time = round(remaining.min(), 1) if not remaining.empty else None

            rows.append({
                'UC Address': uc_address,
                'Specialty': specialty,
                'Primary Clinic': primary_clinic,
                'Primary Drive Time (min)': primary_time,
                'Backup Clinic': backup_clinic,
                'Backup Drive Time (min)': backup_time
            })

    result_df = pd.DataFrame(rows).sort_values(['UC Address', 'Specialty']).reset_index(drop=True)

    # Add UC coordinates
    result_df = result_df.merge(
        urgent_cares[['Address', 'lat', 'lng']].rename(columns={
            'Address': 'UC Address', 'lat': 'UC lat', 'lng': 'UC lng'
        }), on='UC Address', how='left'
    )

    # Add primary clinic coordinates
    result_df = result_df.merge(
        offices[['Normalized Address', 'lat', 'lng']].rename(columns={
            'Normalized Address': 'Primary Clinic', 'lat': 'Primary lat', 'lng': 'Primary lng'
        }), on='Primary Clinic', how='left'
    )

    result_df.to_csv(uc_routing_file, index=False)
    print("\nUC routing table created")
    return result_df





def get_office_to_office_times(offices: pd.DataFrame) -> pd.DataFrame:
    """
    Compute drive times in minutes between all office locations using the
    OpenRouteService Matrix API.

    Used as input for the PC-to-specialty routing table. ORS free tier
    limits requests to 500 elements (origins x destinations); calls are
    chunked accordingly. Results are cached to disk and written to CSV.

    Parameters
    ----------
    offices : pd.DataFrame
        Must contain columns: Normalized Address, lat, lng.

    Returns
    -------
    pd.DataFrame
        Square matrix with office addresses as both index and columns,
        values in minutes.
    """

    if os.path.exists(office_to_office_cache):
        print("Office to office cache found. Skipping ORS call.")
        with open(office_to_office_cache, 'r') as f:
            return pd.DataFrame(json.load(f))

    client = openrouteservice.Client(key=ORS_API_KEY)

    office_list = offices[['Normalized Address', 'lat', 'lng']].dropna(subset=['lat', 'lng'])
    coords = [[row['lng'], row['lat']] for _, row in office_list.iterrows()]  # ORS uses [lng, lat]
    names = office_list['Normalized Address'].tolist()
    n = len(coords)

    print(f"Computing office to office drive times for {n} offices...")

    # ORS free tier limit: 500 matrix elements per request (origins x destinations)
    # Split into chunks: 20 origins x 25 destinations = 500 elements per call
    ORIGIN_CHUNK = 20
    DEST_CHUNK = 25

    results = {name: {} for name in names}

    for i in range(0, n, ORIGIN_CHUNK):
        origin_chunk = coords[i:i + ORIGIN_CHUNK]
        origin_names = names[i:i + ORIGIN_CHUNK]

        for j in range(0, n, DEST_CHUNK):
            dest_chunk = coords[j:j + DEST_CHUNK]
            dest_names = names[j:j + DEST_CHUNK]

            # Combine origins and destinations, track indices
            all_coords = origin_chunk + dest_chunk
            origin_indices = list(range(len(origin_chunk)))
            dest_indices = list(range(len(origin_chunk), len(origin_chunk) + len(dest_chunk)))

            try:
                response = client.distance_matrix(
                    locations=all_coords,
                    sources=origin_indices,
                    destinations=dest_indices,
                    profile='driving-car',
                    metrics=['duration'],
                    units='km'
                )
                durations = response['durations']  # seconds
                for oi, origin_name in enumerate(origin_names):
                    for di, dest_name in enumerate(dest_names):
                        val = durations[oi][di]
                        results[origin_name][dest_name] = round(val / 60, 2) if val is not None else None

                print(f"  Origins {i}-{i+len(origin_chunk)} x Destinations {j}-{j+len(dest_chunk)} done")

            except Exception as e:
                print(f"  [ERROR] Origins {i}-{i+len(origin_chunk)} x Destinations {j}-{j+len(dest_chunk)}: {e}")
                for origin_name in origin_names:
                    for dest_name in dest_names:
                        results[origin_name][dest_name] = None
            time.sleep(1.5)
    with open(office_to_office_cache, 'w') as f:
        json.dump(results, f, indent=4)

    df = pd.DataFrame(results).T
    df = df[names]  # ensure consistent column order
    df.to_csv(office_to_office_file)
    print(f"\nOffice to office matrix saved.")
    return df



def pc_to_specialty_routing_table(
    office_to_office_times: pd.DataFrame,
    patients_df: pd.DataFrame,
    offices: pd.DataFrame,
    pc_min_visits: int = PC_ANCHOR_MIN_VISITS,
    pc_min_pct: float = PC_ANCHOR_MIN_PCT,
    spec_min_visits: int = PC_SPEC_MIN_VISITS,
    spec_min_pct: float = PC_SPEC_MIN_PCT,
) -> pd.DataFrame:
    """
    Build the PC-to-specialty routing table assigning each primary care
    anchor clinic a primary and backup destination per specialty.

    PC anchors must have >= pc_min_visits Primary Care visits and that
    volume must represent >= pc_min_pct% of the location's total visits.
    Specialty destinations must meet the equivalent spec_ thresholds.
    Routing is purely drive-time based within the qualifying pool.
    Appends lat/lng coordinates for mapping. Writes results to CSV.

    Parameters
    ----------
    office_to_office_times : pd.DataFrame
        Drive time matrix from get_office_to_office_times().
    patients_df : pd.DataFrame
        Cleaned patient visit data.
    offices : pd.DataFrame
        Must contain columns: Normalized Address, lat, lng.
    pc_min_visits : int, optional
        Minimum Primary Care visits for an anchor to qualify. Default 3000.
    pc_min_pct : float, optional
        Minimum Primary Care share (%) of location total. Default 40.0.
    spec_min_visits : int, optional
        Minimum specialty visits for a destination to qualify. Default 300.
    spec_min_pct : float, optional
        Minimum specialty share (%) of location total. Default 15.0.

    Returns
    -------
    pd.DataFrame
        One row per PC-specialty pair with primary and backup clinic,
        drive times, and coordinates.
    """

    specialty_vol = build_specialty_vol(patients_df)

    # Define PC anchors
    pc_qualifying = specialty_vol[
        (specialty_vol['Specialty Grouping'] == 'Primary Care') &
        (specialty_vol['Total Visits'] >= pc_min_visits) &
        (specialty_vol['Pct of Location'] >= pc_min_pct)
    ]
    pc_anchors = pc_qualifying['Normalized Address'].tolist()
    valid_pc_anchors = [o for o in pc_anchors if o in office_to_office_times.index]

    if not valid_pc_anchors:
        print("No qualifying PC anchors found.")
        return pd.DataFrame()

    # Define qualifying specialty destinations
    spec_qualifying = specialty_vol[
        (specialty_vol['Specialty Grouping'] != 'Primary Care') &
        (specialty_vol['Total Visits'] >= spec_min_visits) &
        (specialty_vol['Pct of Location'] >= spec_min_pct)
        ]

    specialties = sorted(spec_qualifying['Specialty Grouping'].unique())
    rows = []

    for specialty in specialties:
        spec_df = spec_qualifying[spec_qualifying['Specialty Grouping'] == specialty]
        valid_offices = [o for o in spec_df['Normalized Address'].tolist() if o in office_to_office_times.columns]

        if not valid_offices:
            continue

        times_subset = office_to_office_times.loc[valid_pc_anchors, valid_offices]

        for pc_address in valid_pc_anchors:
            pc_times = times_subset.loc[pc_address].dropna()
            # Exclude self-referral
            pc_times = pc_times[pc_times.index != pc_address]
            if pc_times.empty:
                continue

            primary_clinic = pc_times.idxmin()
            primary_time = round(pc_times[primary_clinic], 1)

            remaining = pc_times.drop(index=primary_clinic)
            backup_clinic = remaining.idxmin() if not remaining.empty else None
            backup_time = round(remaining.min(), 1) if not remaining.empty else None

            rows.append({
                'PC Address': pc_address,
                'Specialty': specialty,
                'Primary Clinic': primary_clinic,
                'Primary Drive Time (min)': primary_time,
                'Backup Clinic': backup_clinic,
                'Backup Drive Time (min)': backup_time
            })

    result_df = pd.DataFrame(rows).sort_values(['PC Address', 'Specialty']).reset_index(drop=True)

    # Add coordinates for mapping
    result_df = result_df.merge(
        offices[['Normalized Address', 'lat', 'lng']].rename(columns={
            'Normalized Address': 'PC Address', 'lat': 'PC lat', 'lng': 'PC lng'
        }), on='PC Address', how='left'
    )
    result_df = result_df.merge(
        offices[['Normalized Address', 'lat', 'lng']].rename(columns={
            'Normalized Address': 'Primary Clinic', 'lat': 'Primary lat', 'lng': 'Primary lng'
        }), on='Primary Clinic', how='left'
    )

    result_df.to_csv(pc_routing_file, index=False)
    print("\nPC to specialty routing table created")
    return result_df


def run(upmc_locations: pd.DataFrame, patients_df: pd.DataFrame, target_zips, zip_population, zip_centroids):
    """
        Execute the full referral ecosystem analysis pipeline.

        Steps:
        1. Classify offices as hospital-based or community-based.
        2. Rank offices by visit volume.
        3. Compute UC-to-office and zip-to-office drive time matrices.
        4. Run zip access desert and population coverage analyses.
        5. Build UC routing table.
        6. Compute office-to-office drive times via ORS.
        7. Build PC-to-specialty routing table.

        Parameters
        ----------
        upmc_locations : pd.DataFrame
            Combined UPMC facility DataFrame from locations.run(); must contain
            Facility, Address, lat, lng.
        patients_df : pd.DataFrame
            Cleaned patient visit data.
        target_zips : set
            Zip codes present in the patient visit data.
        zip_population : pd.DataFrame
            Must contain columns: Zip Code, Population.
        zip_centroids : pd.DataFrame
            Must contain columns: Zip Code, lat, lng.

        Returns
        -------
        uc_routing : pd.DataFrame
            UC-to-specialty routing table.
        pc_routing : pd.DataFrame
            PC-to-specialty routing table.
        urgent_cares_filtered : pd.DataFrame
            Urgent care locations filtered to target zip codes.
        """

    hospitals = upmc_locations[upmc_locations['Facility'] == 'Hospital'].copy()
    offices = patients_df[['Normalized Address', 'lat', 'lng']].drop_duplicates(subset='Normalized Address')

    classified_offices = hosp_community_classifier(offices, hospitals, patients_df)
    top_sites_by_volume(patients_df, classified_offices)

    urgent_cares = upmc_locations[upmc_locations['Facility'] == 'Urgent Care'].copy()
    urgent_cares["Zip"] = urgent_cares["Address"].str.extract(r'(\d{5})(?:\.0)?$')[0].astype(float).astype("Int64").astype(str).str.zfill(5)
    urgent_cares_filtered = urgent_cares[urgent_cares["Zip"].isin(target_zips)]

    uc_to_offices_time_matrix = get_uc_to_office_times(urgent_cares_filtered, offices)
    uc_to_office_drives_by_specialty(uc_to_offices_time_matrix, patients_df)

    zip_to_office_times = get_zip_to_office_times(zip_centroids, offices)
    zip_access_desert_analysis(zip_to_office_times, patients_df, zip_population)
    population_coverage_index(zip_to_office_times, patients_df, zip_population, classified_offices)

    uc_routing = uc_routing_table(uc_to_offices_time_matrix, patients_df, urgent_cares_filtered, offices)

    office_to_office_times = get_office_to_office_times(offices)
    pc_routing = pc_to_specialty_routing_table(office_to_office_times, patients_df, offices)

    return uc_routing, pc_routing, urgent_cares_filtered