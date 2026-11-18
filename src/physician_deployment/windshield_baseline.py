import pandas as pd
import os
import itertools
import numpy as np

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(base_dir, "data")
out_dir = os.path.join(base_dir, "data_out")
output_file1 = os.path.join(out_dir, "Windshield Time Baseline.csv")
output_file2 = os.path.join(out_dir, "Physician Work Breakdown.csv")


def estimate_travel(row, time_matrix, distance_matrix):
    """
        Estimate total windshield time and distance for a surgeon's workday
        by averaging across all possible facility visit orderings.

        For days with two facilities, this is simply the average of both
        directional travel times. For more than two facilities, all permutations
        are evaluated and averaged.

        Parameters
        ----------
        row : pd.Series
            Must contain column: Facility (array of facility names visited
            that day).
        time_matrix : pd.DataFrame
            Duration matrix in minutes from distance_matrix_generator.
        distance_matrix : pd.DataFrame
            Distance matrix in miles from distance_matrix_generator.

        Returns
        -------
        pd.Series
            [Estimated Windshield Time (min), Estimated Windshield Distance (miles),
            Number of Locations].
        """

    locations = row['Facility']
    route_times = []
    route_dists = []
    num_locations = len(locations)

    try:
        for perm in itertools.permutations(locations):
            total_time = 0
            total_dist = 0
            for i in range(len(perm) - 1):
                total_time += time_matrix.loc[perm[i], perm[i + 1]]
                total_dist += distance_matrix.loc[perm[i], perm[i + 1]]
            route_times.append(total_time)
            route_dists.append(total_dist)

        return pd.Series([np.mean(route_times), np.mean(route_dists), num_locations])

    except KeyError:
        return pd.Series([0, 0, num_locations])


def run(surgeries_df: pd.DataFrame, durations_df, distance_df):
    """
        Compute the intraday windshield time baseline for all surgeons.

        Groups surgical cases by surgeon and date, identifies days where
        multiple facilities were visited, and estimates travel time and
        distance for each such day. Writes per-day detail and per-surgeon
        summary to CSV.

        Parameters
        ----------
        surgeries_df : pd.DataFrame
            Must contain columns: Primary Surgeon NPI, Procedure Date, Facility.
        durations_df : pd.DataFrame
            Duration matrix from distance_matrix_generator.run().
        distance_df : pd.DataFrame
            Distance matrix from distance_matrix_generator.run().

        Returns
        -------
        pd.DataFrame
            Per-day travel detail for days containing inter-facility travel.
        """

    daily_summary = surgeries_df.groupby(['Primary Surgeon NPI', 'Procedure Date'])['Facility'].unique().reset_index()
    surgeon_days = surgeries_df.groupby(['Primary Surgeon NPI', 'Procedure Date']).size().reset_index()
    work_days = surgeon_days.groupby('Primary Surgeon NPI').size().reset_index(name='Days Worked')
    travel_days = daily_summary[daily_summary['Facility'].map(len) > 1].copy().reset_index(drop=True)

    travel_days[['Estimated Windshield Time', 'Estimated Windshield Distance', 'Number of Locations']] = travel_days.apply(
        lambda row: estimate_travel(row, durations_df, distance_df), axis=1
    )

    travel_day_count = travel_days.groupby('Primary Surgeon NPI').size().reset_index(name='Days Containing Travel')
    total_miles_df = travel_days.groupby('Primary Surgeon NPI')['Estimated Windshield Distance'].sum().reset_index()
    total_hours_df = travel_days.groupby('Primary Surgeon NPI')['Estimated Windshield Time'].sum().reset_index()
    total_hours_df['Estimated Windshield Time'] = total_hours_df['Estimated Windshield Time'] / 60

    surgeon_work_count = pd.merge(work_days, travel_day_count, on='Primary Surgeon NPI', how='outer')
    surgeon_work_count = pd.merge(surgeon_work_count, total_miles_df, on='Primary Surgeon NPI', how='outer')
    surgeon_work_count = pd.merge(surgeon_work_count, total_hours_df, on='Primary Surgeon NPI', how='outer')
    surgeon_work_count = surgeon_work_count.fillna(0)

    print("\nWindshield Time Baseline:", travel_days['Estimated Windshield Time'].sum() / 60, "hours")
    print("Windshield Distance Baseline:", travel_days['Estimated Windshield Distance'].sum(), "miles")
    travel_days.to_csv(output_file1)
    surgeon_work_count.to_csv(output_file2)
    print("\nWindshield time baseline files successfully placed in data directory")

    return travel_days