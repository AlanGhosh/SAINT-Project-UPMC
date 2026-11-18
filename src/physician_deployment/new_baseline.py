import pandas as pd
import os
import numpy as np

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
cache_dir = os.path.join(base_dir, "cache")
output_file1 = os.path.join(out_dir, "Optimized Windshield Time Baseline.csv")
output_file2 = os.path.join(out_dir, "Optimized Physician Work Breakdown.csv")



def estimate_travel(row, time_matrix, distance_matrix):
    """
    Estimate windshield time and distance for an optimized workday,
    where only the surgeon's assigned home hospital and home ASC are
    considered as valid travel legs.

    Unlike the windshield baseline, this function only processes two-facility
    days (the assigned pair), taking the average of both directions.

    Parameters
    ----------
    row : pd.Series
        Must contain column: Facility (list of assigned facilities for
        that day after filtering).
    time_matrix : pd.DataFrame
        Duration matrix in minutes.
    distance_matrix : pd.DataFrame
        Distance matrix in miles.

    Returns
    -------
    pd.Series
        [Estimated Windshield Time (min), Estimated Windshield Distance (miles),
        Number of Locations].
    """

    locations = row['Facility']
    num_locations = len(locations)

    if num_locations < 2:
        return pd.Series([0, 0, num_locations])

    a, b = locations[0], locations[1]
    try:
        time = (time_matrix.loc[a, b] + time_matrix.loc[b, a]) / 2
        dist = (distance_matrix.loc[a, b] + distance_matrix.loc[b, a]) / 2
        return pd.Series([time, dist, num_locations])
    except KeyError:
        return pd.Series([0, 0, num_locations])




def run(windshield_df, assignment_df, df_dur, df_dist):
    """
    Compute the optimized windshield time baseline using home facility assignments.

    Filters each surgeon's travel days to only include days where both their
    assigned home hospital and home ASC were visited, then re-estimates travel
    for those days. This reflects the reduction achievable if surgeons are
    consolidated to their assigned facility pair. Writes per-day detail and
    per-surgeon summary to CSV.

    Parameters
    ----------
    windshield_df : pd.DataFrame
        Output of windshield_baseline.run(); per-day travel detail.
    assignment_df : pd.DataFrame
        Output of home_assignment.run(); must contain Home Hospital,
        Home ASC per surgeon NPI.
    df_dur : pd.DataFrame
        Duration matrix in minutes.
    df_dist : pd.DataFrame
        Distance matrix in miles.
    """

    # Build lookup dictionaries from assignment_df
    if assignment_df.index.name == 'Primary Surgeon NPI':
        hospital_lookup = assignment_df['Home Hospital'].to_dict()
        asc_lookup = assignment_df['Home ASC'].to_dict()
    else:
        hospital_lookup = assignment_df.set_index('Primary Surgeon NPI')['Home Hospital'].to_dict()
        asc_lookup = assignment_df.set_index('Primary Surgeon NPI')['Home ASC'].to_dict()

    def filter_facilities(row):
        npi = str(row['Primary Surgeon NPI'])
        facilities = row['Facility']  # numpy array from unique()

        home_hospital = hospital_lookup.get(npi)
        home_asc = asc_lookup.get(npi)

        # Keep only assigned hospital and ASC if they appear in that day's facilities
        assigned = set()
        if home_hospital and home_hospital in facilities:
            assigned.add(home_hospital)
        if home_asc and home_asc in facilities:
            assigned.add(home_asc)

        return list(assigned)

    daily_summary = windshield_df.copy()
    daily_summary['Facility'] = daily_summary.apply(filter_facilities, axis=1)

    # Only keep days where at least 2 assigned facilities were visited (actual travel)
    optimized_travel_days = daily_summary[daily_summary['Facility'].map(len) > 1].copy().reset_index(drop=True)

    optimized_travel_days[['Estimated Windshield Time', 'Estimated Windshield Distance', 'Number of Locations']] = optimized_travel_days.apply(
        lambda row: estimate_travel(row, df_dur, df_dist), axis=1
    )

    travel_day_count = optimized_travel_days.groupby('Primary Surgeon NPI').size().reset_index(name='Days Containing Travel')
    total_miles_df = optimized_travel_days.groupby('Primary Surgeon NPI')['Estimated Windshield Distance'].sum().reset_index()
    total_hours_df = optimized_travel_days.groupby('Primary Surgeon NPI')['Estimated Windshield Time'].sum().reset_index()
    total_hours_df['Estimated Windshield Time'] = total_hours_df['Estimated Windshield Time'] / 60

    surgeon_work_count = pd.merge(travel_day_count, total_miles_df, on='Primary Surgeon NPI', how='outer')
    surgeon_work_count = pd.merge(surgeon_work_count, total_hours_df, on='Primary Surgeon NPI', how='outer')
    surgeon_work_count = surgeon_work_count.fillna(0)

    print("\nNew Windshield Time Baseline:", optimized_travel_days['Estimated Windshield Time'].sum() / 60, "hours")
    print("New Windshield Distance Baseline:", optimized_travel_days['Estimated Windshield Distance'].sum(), "miles")
    optimized_travel_days.to_csv(output_file1)
    surgeon_work_count.to_csv(output_file2)
    print("\nOptimized windshield time baseline files successfully placed in data directory")