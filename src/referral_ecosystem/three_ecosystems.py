import os
import folium
import pandas as pd
import json
from utils import SPECIALTY_COLORS, MAP_TILES, add_select_all_button, add_specialty_legend

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
maps_dir = os.path.join(base_dir, "maps")
north_file = os.path.join(maps_dir, "Cranberry-Butler Map.html")
southwest_file = os.path.join(maps_dir, "Southwest Map.html")
east_file = os.path.join(maps_dir, "Irwin-Latrobe Map.html")

MAP_ZOOM = 10

NORTH_ZIPS = {str(z).zfill(5) for z in [16001, 16002, 16053, 16045,
                                          16029, 16027, 16033, 16063,
                                          16024, 16046, 16066]}

SOUTHWEST_ZIPS = {str(z).zfill(5) for z in [15136, 15205, 15220, 15071, 15106,
                                              15216, 15226, 15243, 15228, 15234,
                                              15142, 15057, 15064, 15017, 15241,
                                              15102, 15055, 15031, 15321, 15361,
                                              15350, 15317, 15363, 15342, 15082]}

EAST_ZIPS = {str(z).zfill(5) for z in [15650, 15676, 15693, 15638, 15696,
                                         15601, 15619, 15662, 15633, 15635,
                                         15644, 15623, 15675, 15636, 15634,
                                         15692, 15611, 15691, 15678,
                                         15647, 15642]}


def add_missing_specialties_box(m, specialties_present, qualifying_specialties):
    """
    Add a legend box listing specialties that have qualifying routing data
    system-wide but no presence in the current region.

    Parameters
    ----------
    m : folium.Map
        Map instance to add the box to.
    specialties_present : iterable of str
        Specialties that have routing lines in this region.
    qualifying_specialties : set of str
        All specialties present in the full routing tables.
    """

    missing = sorted(qualifying_specialties - set(specialties_present))

    if not missing:
        return

    box_html = '<div style="position:fixed;bottom:30px;left:10px;z-index:9999;background:white;padding:10px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,0.4);font-size:12px;max-width:220px;">'
    box_html += '<b>Specialties Not in Region</b><br>'
    for s in missing:
        box_html += f'• {s}<br>'
    box_html += '</div>'
    m.get_root().html.add_child(folium.Element(box_html))


def filter_routing_by_zips(routing_df, patients_df, urgent_cares, target_zips, origin_col):
    """
    Filter a routing table to rows where both the origin and destination
    fall within a target set of zip codes.

    For UC routing, origin zip is derived from the urgent care location data.
    For PC routing, origin zip is derived from the patient visit data.

    Parameters
    ----------
    routing_df : pd.DataFrame
        UC or PC routing table.
    patients_df : pd.DataFrame
        Cleaned patient visit data; used to map office addresses to zips.
    urgent_cares : pd.DataFrame
        Urgent care locations with Address and Zip columns.
    target_zips : set of str
        Zip codes defining the region.
    origin_col : str
        Column name for the origin address: 'UC Address' or 'PC Address'.

    Returns
    -------
    pd.DataFrame
        Filtered routing table.
    """

    zip_lookup = patients_df[['Normalized Address', 'Dept Zip']].drop_duplicates()
    zip_lookup['Dept Zip'] = zip_lookup['Dept Zip'].astype(str).str.zfill(5)
    valid_addresses = set(zip_lookup[zip_lookup['Dept Zip'].isin(target_zips)]['Normalized Address'])

    if origin_col == 'UC Address':
        uc_zip_lookup = urgent_cares[['Address', 'Zip']].copy()
        uc_zip_lookup['Zip'] = uc_zip_lookup['Zip'].astype(str).str.zfill(5)
        valid_uc_addresses = set(uc_zip_lookup[uc_zip_lookup['Zip'].isin(target_zips)]['Address'])
        return routing_df[
            routing_df[origin_col].isin(valid_uc_addresses) &
            routing_df['Primary Clinic'].isin(valid_addresses)
        ]
    else:
        return routing_df[
            routing_df[origin_col].isin(valid_addresses) &
            routing_df['Primary Clinic'].isin(valid_addresses)
        ]


def add_zip_boundaries(m, zip_geojson, region_zips):
    """
    Add a toggleable zip code boundary layer to a Folium map, filtered
    to a specific set of zip codes.

    Parameters
    ----------
    m : folium.Map
        Map instance to add the layer to.
    zip_geojson : dict
        Full GeoJSON FeatureCollection for all zip codes.
    region_zips : set of str
        Zip codes to include in this layer.
    """

    geojson = json.loads(json.dumps(zip_geojson))  # deep copy
    geojson['features'] = [
        f for f in geojson['features']
        if f['properties']['ZCTA5CE20'] in region_zips
    ]

    fg_zips = folium.FeatureGroup(name='Zip Code Boundaries', show=True)
    folium.GeoJson(
        geojson,
        style_function=lambda f: {
            'fillColor': 'transparent',
            'color': '#888888',
            'weight': 1,
            'fillOpacity': 0
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['ZCTA5CE20'],
            aliases=['Zip Code:']
        )
    ).add_to(fg_zips)
    fg_zips.add_to(m)


def make_region_map(uc_routing, pc_routing, output_path, zip_geojson, region_zips, qualifying_specialties):
    """
    Build a single regional ecosystem routing map for one of the three
    sub-regions (North, Southwest, East).

    Layers are organized by specialty with both UC and PC routing lines.
    Includes zip boundaries, specialty legend, and missing specialties box.
    Saves to HTML.

    Parameters
    ----------
    uc_routing : pd.DataFrame
        Region-filtered UC routing table.
    pc_routing : pd.DataFrame
        Region-filtered PC routing table.
    output_path : str
        File path to save the HTML map.
    zip_geojson : dict
        Full GeoJSON for zip code boundaries.
    region_zips : set of str
        Zip codes defining this region.
    qualifying_specialties : set of str
        All specialties present in the full routing tables.
    """

    all_lats = pd.concat([uc_routing['UC lat'], pc_routing['PC lat']]).dropna()
    all_lngs = pd.concat([uc_routing['UC lng'], pc_routing['PC lng']]).dropna()

    if all_lats.empty:
        print(f"No data for map {output_path}, skipping.")
        return

    map_center = [all_lats.mean(), all_lngs.mean()]
    m = folium.Map(location=map_center, zoom_start=MAP_ZOOM, tiles=MAP_TILES)

    add_zip_boundaries(m, zip_geojson, region_zips)  # after m is created

    specialties = sorted(set(uc_routing['Specialty'].unique()) | set(pc_routing['Specialty'].unique()))

    for specialty in specialties:
        color = SPECIALTY_COLORS.get(specialty, 'gray')
        fg = folium.FeatureGroup(name=specialty, show=True)
        uc_spec = uc_routing[uc_routing['Specialty'] == specialty]
        pc_spec = pc_routing[pc_routing['Specialty'] == specialty]

        for _, row in uc_spec.iterrows():
            if pd.isna(row['UC lat']) or pd.isna(row['Primary lat']):
                continue
            folium.PolyLine(
                locations=[[row['UC lat'], row['UC lng']], [row['Primary lat'], row['Primary lng']]],
                color=color, weight=2.5, opacity=0.8,
                tooltip=f"UC → {specialty}<br>Clinic: {row['Primary Clinic']}<br>Drive Time: {row['Primary Drive Time (min)']} min"
            ).add_to(fg)
            folium.CircleMarker(
                location=[row['UC lat'], row['UC lng']],
                radius=5, color='#444444', fill=True, fill_color='#444444', fill_opacity=0.9,
                tooltip=f"UC: {row['UC Address']}"
            ).add_to(fg)
            folium.CircleMarker(
                location=[row['Primary lat'], row['Primary lng']],
                radius=4, color=color, fill=True, fill_color='white', fill_opacity=1.0, weight=2,
                tooltip=f"{row['Primary Clinic']}<br>{specialty}"
            ).add_to(fg)

        for _, row in pc_spec.iterrows():
            if pd.isna(row['PC lat']) or pd.isna(row['Primary lat']):
                continue
            folium.PolyLine(
                locations=[[row['PC lat'], row['PC lng']], [row['Primary lat'], row['Primary lng']]],
                color=color, weight=2.5, opacity=0.8,
                tooltip=f"PC → {specialty}<br>Clinic: {row['Primary Clinic']}<br>Drive Time: {row['Primary Drive Time (min)']} min"
            ).add_to(fg)
            folium.CircleMarker(
                location=[row['PC lat'], row['PC lng']],
                radius=5, color='#6a0dad', fill=True, fill_color='#6a0dad', fill_opacity=0.9,
                tooltip=f"PC Anchor: {row['PC Address']}"
            ).add_to(fg)
            folium.CircleMarker(
                location=[row['Primary lat'], row['Primary lng']],
                radius=4, color=color, fill=True, fill_color='white', fill_opacity=1.0, weight=2,
                tooltip=f"{row['Primary Clinic']}<br>{specialty}"
            ).add_to(fg)

        fg.add_to(m)

    add_specialty_legend(m, specialties)
    add_missing_specialties_box(m, specialties, qualifying_specialties)
    folium.LayerControl(collapsed=False).add_to(m)
    add_select_all_button(m)
    m.save(output_path)
    print(f"  Saved: {output_path}")


def make_three_maps(uc_routing, pc_routing, patients_df, urgent_cares, zip_geojson):
    """
    Build all three regional ecosystem routing maps: North (Cranberry-Butler),
    Southwest, and East (Irwin-Latrobe).

    Each map is filtered to its predefined zip code set and saved to the
    maps directory.

    Parameters
    ----------
    uc_routing : pd.DataFrame
        Full UC routing table from analysis.uc_routing_table().
    pc_routing : pd.DataFrame
        Full PC routing table from analysis.pc_to_specialty_routing_table().
    patients_df : pd.DataFrame
        Cleaned patient visit data; used for zip filtering.
    urgent_cares : pd.DataFrame
        Filtered urgent care locations.
    zip_geojson : dict
        GeoJSON for zip code boundaries.
    """

    qualifying_specialties = set(uc_routing['Specialty'].unique()) | set(pc_routing['Specialty'].unique())

    regions = {
        'North': (NORTH_ZIPS, north_file),
        'Southwest': (SOUTHWEST_ZIPS, southwest_file),
        'East': (EAST_ZIPS, east_file)
    }

    for region_name, (zips, output_path) in regions.items():
        print(f"\nBuilding {region_name} map...")
        uc_region = filter_routing_by_zips(uc_routing, patients_df, urgent_cares, zips, 'UC Address')
        pc_region = filter_routing_by_zips(pc_routing, patients_df, urgent_cares, zips, 'PC Address')
        make_region_map(uc_region, pc_region, output_path, zip_geojson, zips, qualifying_specialties)

    print("\nAll three regional maps saved.")