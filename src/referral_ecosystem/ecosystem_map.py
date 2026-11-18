import os
import folium
import pandas as pd
from utils import SPECIALTY_COLORS, MAP_TILES, add_select_all_button, add_specialty_legend

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
maps_dir = os.path.join(base_dir, "maps")
ecosystem_map_file = os.path.join(maps_dir, "Ecosystem Map.html")

MAP_ZOOM = 9

# Line weight by distance tier — thicker = closer
TIER_WEIGHTS = {
    '≤15 min': 4,
    '15-30 min': 3,
    '30-45 min': 2,
    '>45 min': 1
}


def get_tier(drive_time: float) -> str:
    """
    Classify a drive time in minutes into one of four distance tiers.

    Tiers: '≤15 min', '15-30 min', '30-45 min', '>45 min'.

    Parameters
    ----------
    drive_time : float
        Drive time in minutes.

    Returns
    -------
    str
        Tier label.
    """

    if drive_time <= 15:
        return '≤15 min'
    elif drive_time <= 30:
        return '15-30 min'
    elif drive_time <= 45:
        return '30-45 min'
    else:
        return '>45 min'


def make_ecosystem_routing_map(
    uc_routing: pd.DataFrame,
    pc_routing: pd.DataFrame,
    map_center: list,
    output_path: str = None
):
    """
    Build the full-region ecosystem routing map showing UC and PC anchor
    connections to specialty clinics across the entire service area.

    Lines are colored by specialty and weighted by drive time tier (thicker
    = closer). Eight global toggleable layers: UC and PC each split into
    four distance tiers. Saves to HTML.

    Parameters
    ----------
    uc_routing : pd.DataFrame
        UC routing table from analysis.uc_routing_table(); must contain
        UC Address, UC lat, UC lng, Specialty, Primary Clinic,
        Primary lat, Primary lng, Primary Drive Time (min).
    pc_routing : pd.DataFrame
        PC routing table from analysis.pc_to_specialty_routing_table();
        must contain PC Address, PC lat, PC lng, Specialty, Primary Clinic,
        Primary lat, Primary lng, Primary Drive Time (min).
    map_center : list of float
        [lat, lng] center for the map.
    output_path : str, optional
        File path to save the HTML map. Defaults to maps/Ecosystem Map.html.
    """

    if output_path is None:
        output_path = ecosystem_map_file

    os.makedirs(maps_dir, exist_ok=True)

    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)

    # 8 global feature groups
    fg_uc = {tier: folium.FeatureGroup(name=f'UC — {tier}', show=True) for tier in TIER_WEIGHTS}
    fg_pc = {tier: folium.FeatureGroup(name=f'PC — {tier}', show=True) for tier in TIER_WEIGHTS}

    specialties = sorted(set(uc_routing['Specialty'].unique()) | set(pc_routing['Specialty'].unique()))

    for specialty in specialties:
        color = SPECIALTY_COLORS.get(specialty, 'gray')
        uc_spec = uc_routing[uc_routing['Specialty'] == specialty]
        pc_spec = pc_routing[pc_routing['Specialty'] == specialty]

        # UC routing lines
        for _, row in uc_spec.iterrows():
            if pd.isna(row['UC lat']) or pd.isna(row['Primary lat']):
                continue

            drive_time = row['Primary Drive Time (min)']
            tier = get_tier(drive_time)
            fg = fg_uc[tier]
            weight = TIER_WEIGHTS[tier]

            folium.PolyLine(
                locations=[[row['UC lat'], row['UC lng']], [row['Primary lat'], row['Primary lng']]],
                color=color,
                weight=weight,
                opacity=0.8,
                tooltip=f"UC → {specialty}<br>Clinic: {row['Primary Clinic']}<br>Drive Time: {drive_time} min ({tier})"
            ).add_to(fg)

            folium.CircleMarker(
                location=[row['UC lat'], row['UC lng']],
                radius=6,
                color='#444444',  # fixed dark gray
                fill=True,
                fill_color='#444444',
                fill_opacity=0.9,
                tooltip=f"UC: {row['UC Address']}"
            ).add_to(fg)

            folium.CircleMarker(
                location=[row['Primary lat'], row['Primary lng']],
                radius=4,
                color=color,
                fill=True,
                fill_color='white',
                fill_opacity=1.0,
                weight=2,
                tooltip=f"{row['Primary Clinic']}<br>{specialty}"
            ).add_to(fg)

        # PC routing lines
        for _, row in pc_spec.iterrows():
            if pd.isna(row['PC lat']) or pd.isna(row['Primary lat']):
                continue

            drive_time = row['Primary Drive Time (min)']
            tier = get_tier(drive_time)
            fg = fg_pc[tier]
            weight = TIER_WEIGHTS[tier]

            folium.PolyLine(
                locations=[[row['PC lat'], row['PC lng']], [row['Primary lat'], row['Primary lng']]],
                color=color,
                weight=weight,
                opacity=0.8,
                tooltip=f"PC → {specialty}<br>Clinic: {row['Primary Clinic']}<br>Drive Time: {drive_time} min ({tier})"
            ).add_to(fg)

            # PC marker — fixed dark purple
            folium.CircleMarker(
                location=[row['PC lat'], row['PC lng']],
                radius=6,
                color='#6a0dad',
                fill=True,
                fill_color='#6a0dad',
                fill_opacity=0.9,
                tooltip=f"PC Anchor: {row['PC Address']}"
            ).add_to(fg)

            folium.CircleMarker(
                location=[row['Primary lat'], row['Primary lng']],
                radius=4,
                color=color,
                fill=True,
                fill_color='white',
                fill_opacity=1.0,
                weight=2,
                tooltip=f"{row['Primary Clinic']}<br>{specialty}"
            ).add_to(fg)

    # Add all groups after iterating all specialties
    for tier in TIER_WEIGHTS:
        fg_uc[tier].add_to(m)
    for tier in TIER_WEIGHTS:
        fg_pc[tier].add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    add_specialty_legend(m, specialties)
    add_select_all_button(m)
    m.save(output_path)
    print(f"\nEcosystem routing map saved to {output_path}")