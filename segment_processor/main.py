#!/usr/bin/env python3
"""
Extract street segments for the London Borough of Brent from OpenStreetMap.

This script:
1. Downloads road network data from OSM for Brent
2. Downloads ward boundary data for London
3. Identifies all intersection nodes
4. Splits roads into segments between intersections
5. Assigns each segment to a ward via spatial join
6. Exports segments as GeoJSON with ward information
"""

import math
from datetime import datetime

import osmnx as ox
import geopandas as gpd
import json
import sys
from pathlib import Path
from shapely.geometry import LineString, Point
from shapely import offset_curve
from shapely.ops import linemerge
from shapely.strtree import STRtree
import networkx as nx
import urllib.request
import zipfile
import tempfile
from pyproj import Transformer


def get_postcode_centroids(lad_code: str):
    """
    Load postcode centroids for a specific Local Authority District.

    Args:
        lad_code: LAD code to filter by (e.g., "E09000005" for Brent)

    Returns:
        GeoDataFrame of postcode centroids in WGS84 (EPSG:4326)
    """
    print(f"Loading postcode centroids for LAD {lad_code}...")

    data_path = Path(__file__).parent.parent / 'input' / 'Online_ONS_Postcode_Directory_Live_-48057019277614511.gpkg'

    if not data_path.exists():
        print(f"Warning: Postcode file not found at {data_path}. Postcodes will not be included.")
        return None

    # Load postcodes and filter to LAD
    postcodes_gdf = gpd.read_file(data_path)
    postcodes_gdf = postcodes_gdf[postcodes_gdf['LAD25CD'] == lad_code].copy()

    print(f"Loaded {len(postcodes_gdf)} postcodes for LAD {lad_code}")

    # Convert from British National Grid (EPSG:27700) to WGS84 (EPSG:4326)
    if postcodes_gdf.crs != 'EPSG:4326':
        postcodes_gdf = postcodes_gdf.to_crs('EPSG:4326')

    return postcodes_gdf


def get_ward_boundaries(lad_name: str):
    """
    Load ward boundaries for a specific Local Authority District (LAD).

    Uses the May 2023 ward boundaries which include LAD information.

    Args:
        lad_name: Name of the LAD to filter by (e.g., "Brent")

    Returns:
        GeoDataFrame of ward boundaries filtered to the specified LAD.
    """
    print(f"Loading ward boundaries for {lad_name}...")

    # Path to the May 2023 ward boundaries file (includes LAD column)
    data_path = Path(__file__).parent.parent / 'input' / 'WD_MAY_2023_UK_BGC_932649178890735580.geojson'

    if not data_path.exists():
        raise FileNotFoundError(
            f"Ward boundaries file not found at {data_path}. "
            "Please download from ONS Open Geography Portal."
        )

    # Load the GeoJSON
    wards_gdf = gpd.read_file(data_path)

    print(f"Loaded {len(wards_gdf)} wards total")
    print(f"Available columns: {list(wards_gdf.columns)}")

    # Find the LAD name column (LAD23NM for May 2023 data)
    lad_col = None
    for col in wards_gdf.columns:
        if 'LAD' in col and 'NM' in col and 'NMW' not in col:
            lad_col = col
            break

    if not lad_col:
        raise ValueError("Could not find LAD name column (LAD*NM) in the data")

    # Filter to the specified LAD
    filtered_wards = wards_gdf[wards_gdf[lad_col] == lad_name].copy()
    print(f"Filtered to {len(filtered_wards)} wards in {lad_name} using column '{lad_col}'")

    if len(filtered_wards) == 0:
        raise ValueError(f"No wards found for LAD '{lad_name}'. Check the name is correct.")

    # Ensure CRS is WGS84 (EPSG:4326) to match OSM data
    if filtered_wards.crs != 'EPSG:4326':
        filtered_wards = filtered_wards.to_crs('EPSG:4326')

    return filtered_wards


def get_brent_road_network():
    """Download the road network for London Borough of Brent."""
    print("Downloading road network for London Borough of Brent...")

    # Download the street network for Brent
    # network_type='all' gets all road types including residential
    graph = ox.graph_from_place(
        "London Borough of Brent, United Kingdom",
        network_type='all'
    )

    print(f"Downloaded graph with {len(graph.nodes)} nodes and {len(graph.edges)} edges")
    return graph


# Highway types to exclude — not relevant for doorknocking canvassers.
# Includes footways, cycleways, paths, and slip-road links.
EXCLUDED_HIGHWAY_TYPES = {
    "footway", "cycleway", "path", "steps",
    "bridleway", "corridor", "track",
    "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
}


def _resolve_ward(line_geom, ward_geoms, ward_names, ward_tree):
    """Return the ward name covering the majority of line_geom by intersection length."""
    hits = ward_tree.query(line_geom, predicate='intersects')
    if len(hits) == 0:
        return None
    if len(hits) == 1:
        return ward_names[hits[0]]
    best_name = None
    best_length = 0
    for idx in hits:
        try:
            piece = line_geom.intersection(ward_geoms[idx])
            if piece.length > best_length:
                best_length = piece.length
                best_name = ward_names[idx]
        except Exception:
            continue
    return best_name


def _get_cardinal_sides(geometry):
    """Return (positive_offset_label, negative_offset_label) cardinal directions.

    For an east-west road the sides are N/S; for north-south they are E/W.
    Positive offset_curve distance offsets to the *left* of the line direction.
    """
    coords = list(geometry.coords)
    dx = coords[-1][0] - coords[0][0]
    dy = coords[-1][1] - coords[0][1]
    bearing = math.degrees(math.atan2(dx, dy)) % 360  # 0=N, 90=E
    # Normalize to 0-180 (direction-agnostic orientation)
    orientation = bearing % 180

    if 45 <= orientation < 135:
        # Road runs mostly east-west
        # Heading east (bearing ~90): left=N, right=S
        # Heading west (bearing ~270): left=S, right=N
        if 0 <= bearing < 180:
            return ("N", "S")
        else:
            return ("S", "N")
    else:
        # Road runs mostly north-south
        # Heading north (bearing ~0): left=W, right=E
        # Heading south (bearing ~180): left=E, right=W
        if 90 <= bearing < 270:
            return ("E", "W")
        else:
            return ("W", "E")


def _make_side_features(segment_id, geometry, data, ward_geoms, ward_names, ward_tree,
                        ward_to_lad, fallback_ward, fallback_lad, offset_degrees, find_postcodes_fn):
    """Build two GeoJSON features (one per side) for any road segment.

    Offsets the geometry left and right, resolves each side's ward independently,
    and falls back to *fallback_ward* when a side can't be resolved.
    """
    pos_label, neg_label = _get_cardinal_sides(geometry)

    # Try to compute offset curves for each side
    try:
        left_line = offset_curve(geometry, offset_degrees)
        right_line = offset_curve(geometry, -offset_degrees)

        if left_line.is_empty or right_line.is_empty:
            raise ValueError("empty offset")

        if left_line.geom_type == 'MultiLineString':
            left_line = linemerge(left_line)
        if right_line.geom_type == 'MultiLineString':
            right_line = linemerge(right_line)

        left_ward = _resolve_ward(left_line, ward_geoms, ward_names, ward_tree) or fallback_ward
        right_ward = _resolve_ward(right_line, ward_geoms, ward_names, ward_tree) or fallback_ward
    except Exception:
        # Offset failed — use original geometry for both sides
        left_line = geometry
        right_line = geometry
        left_ward = fallback_ward
        right_ward = fallback_ward

    pair_id = f'segment_{segment_id}'
    features = []

    for cardinal, ward_name, line_geom in [
        (pos_label, left_ward, left_line),
        (neg_label, right_ward, right_line),
    ]:
        lad = ward_to_lad.get(ward_name, fallback_lad)
        postcodes = find_postcodes_fn(line_geom)
        geom_type = 'MultiLineString' if line_geom.geom_type == 'MultiLineString' else 'LineString'
        if geom_type == 'MultiLineString':
            coords = [list(part.coords) for part in line_geom.geoms]
        else:
            coords = list(line_geom.coords)
        feature = {
            'type': 'Feature',
            'properties': {
                'id': f'segment_{segment_id}_{cardinal}',
                'pair_id': pair_id,
                'side': cardinal,
                'color': '#FF0000',
                'osm_id': data.get('osmid', None),
                'name': data.get('name', 'Unnamed'),
                'highway': data.get('highway', 'unknown'),
                'lad': lad,
                'ward': ward_name,
                'postcodes': postcodes,
            },
            'geometry': {
                'type': geom_type,
                'coordinates': coords,
            }
        }
        features.append(feature)
    return features


def graph_to_segments(graph, wards_gdf, postcodes_gdf=None, buffer_meters=30):
    """
    Convert the OSMnx graph into individual segments and split at ward boundaries.

    Each segment is a portion of road between two intersection nodes.
    If a segment crosses ward boundaries, it will be split at those boundaries.

    Args:
        graph: OSMnx graph
        wards_gdf: GeoDataFrame of ward boundaries (must include LAD column)
        postcodes_gdf: Optional GeoDataFrame of postcode centroids
        buffer_meters: Buffer distance in meters for postcode matching

    Returns:
        List of segment features with ward, LAD, and postcode assignments
    """
    print("Converting graph to segments...")

    # Find the ward name column
    ward_name_col = None
    for col in wards_gdf.columns:
        if 'WD' in col and 'NM' in col and 'NMW' not in col:
            ward_name_col = col
            break

    if not ward_name_col:
        print("Warning: Could not find ward name column, using first non-geometry column")
        ward_name_col = [col for col in wards_gdf.columns if col != 'geometry'][0]

    # Find the LAD name column
    lad_name_col = None
    for col in wards_gdf.columns:
        if 'LAD' in col and 'NM' in col and 'NMW' not in col:
            lad_name_col = col
            break

    if not lad_name_col:
        raise ValueError("Could not find LAD name column (LAD*NM) in the data")

    print(f"Using ward name column: {ward_name_col}")
    print(f"Using LAD name column: {lad_name_col}")

    # Ward data structures for boundary-road detection
    ward_geom_list = list(wards_gdf.geometry)
    ward_name_list = list(wards_gdf[ward_name_col])
    ward_spatial_tree = STRtree(ward_geom_list)
    ward_to_lad = dict(zip(wards_gdf[ward_name_col], wards_gdf[lad_name_col]))
    offset_degrees = 4.0 / 111000  # ~4 meters at London latitude

    # Set up postcode spatial index if postcodes are provided
    postcode_tree = None
    postcode_points = None
    postcode_codes = None
    # Buffer in degrees (approximate: 30m ~ 0.00027 degrees at London's latitude)
    buffer_degrees = buffer_meters / 111000

    if postcodes_gdf is not None and len(postcodes_gdf) > 0:
        print(f"Building spatial index for {len(postcodes_gdf)} postcodes...")
        postcode_points = list(postcodes_gdf.geometry)
        postcode_codes = list(postcodes_gdf['PCDS'])
        postcode_tree = STRtree(postcode_points)
        print("Spatial index built.")

    def find_postcodes_for_geometry(geom):
        """Find all postcodes within buffer distance of a geometry."""
        if postcode_tree is None:
            return []
        # Buffer the geometry to find nearby postcodes
        buffered = geom.buffer(buffer_degrees)
        # Query the spatial index
        candidate_indices = postcode_tree.query(buffered)
        # Get the postcodes for matching points
        postcodes = sorted(set(postcode_codes[i] for i in candidate_indices))
        return postcodes

    segments = []
    segment_id = 0

    total_edges = len(graph.edges)
    processed = 0

    for u, v, key, data in graph.edges(keys=True, data=True):
        # Skip highway types not relevant for doorknocking
        highway = data.get('highway', '')
        # osmnx may return a list when an edge has multiple highway tags
        if isinstance(highway, list):
            highway_types = set(highway)
        else:
            highway_types = {highway}
        if highway_types and highway_types <= EXCLUDED_HIGHWAY_TYPES:
            # Keep named footways — they're often residential access paths
            name = data.get('name', '')
            is_named = bool(name) if not isinstance(name, list) else bool(name[0])
            if not (is_named and 'footway' in highway_types):
                processed += 1
                continue

        # Skip unnamed service roads (parking aisles, driveways, cemetery paths, etc.)
        if 'service' in highway_types:
            name = data.get('name', '')
            is_named = bool(name) if not isinstance(name, list) else bool(name[0])
            if not is_named:
                processed += 1
                continue

        # Get the geometry of this edge
        if 'geometry' in data:
            geometry = data['geometry']
        else:
            # Otherwise create a straight line between the two nodes
            start_node = graph.nodes[u]
            end_node = graph.nodes[v]
            geometry = LineString([
                (start_node['x'], start_node['y']),
                (end_node['x'], end_node['y'])
            ])

        # Find all wards that intersect this segment
        intersecting_wards = wards_gdf[wards_gdf.intersects(geometry)]

        if len(intersecting_wards) == 0:
            # No ward found - skip this segment (it's outside our LAD)
            pass

        elif len(intersecting_wards) <= 1:
            # Segment is in one ward — produce two side features
            ward_row = intersecting_wards.iloc[0]
            fallback_ward = ward_row[ward_name_col]
            fallback_lad = ward_row[lad_name_col]
            features = _make_side_features(
                segment_id, geometry, data,
                ward_geom_list, ward_name_list, ward_spatial_tree,
                ward_to_lad, fallback_ward, fallback_lad,
                offset_degrees, find_postcodes_for_geometry,
            )
            segments.extend(features)
            segment_id += 1

        else:
            # Segment crosses multiple wards — split at ward boundaries,
            # then produce two side features for each piece
            for _, ward in intersecting_wards.iterrows():
                ward_geom = ward['geometry']
                ward_name = ward[ward_name_col]
                lad_name = ward[lad_name_col]

                try:
                    intersection = geometry.intersection(ward_geom)

                    if intersection.is_empty:
                        continue

                    if intersection.geom_type == 'LineString':
                        lines_to_add = [intersection]
                    elif intersection.geom_type == 'MultiLineString':
                        lines_to_add = list(intersection.geoms)
                    else:
                        continue

                    for line in lines_to_add:
                        if line.length > 0:
                            features = _make_side_features(
                                segment_id, line, data,
                                ward_geom_list, ward_name_list, ward_spatial_tree,
                                ward_to_lad, ward_name, lad_name,
                                offset_degrees, find_postcodes_for_geometry,
                            )
                            segments.extend(features)
                            segment_id += 1

                except Exception as e:
                    print(f"Warning: Failed to split segment at ward boundary: {e}")
                    continue

        processed += 1
        if processed % 5000 == 0:
            print(f"Processed {processed}/{total_edges} edges, created {len(segments)} segments")

    print(f"Created {len(segments)} segments from {total_edges} edges")
    return segments


# Highway types considered low-priority pedestrian ways for deduplication.
_FOOTWAY_TYPES = {"footway", "path"}

# Highway types considered carriageways (roads with houses).
_ROAD_TYPES = {"tertiary", "secondary", "primary", "residential", "unclassified", "trunk"}


def filter_redundant_footways(segments, threshold_m=15):
    """Remove footway/path segments that duplicate a nearby road segment.

    Sidewalk footways mapped parallel to a carriageway with the same street
    name produce redundant overlapping features. This drops the footway and
    keeps the road.
    """
    # Rough conversion at London latitude
    meters_per_degree = 111_000

    # --- 1. Index segments by pair_id, pick one side per pair for midpoint ---
    pair_segments = {}  # pair_id → list of features
    pair_midpoints = {}  # pair_id → (mid_x, mid_y)
    pair_info = {}  # pair_id → {name, highway}

    for feat in segments:
        props = feat["properties"]
        pid = props["pair_id"]
        pair_segments.setdefault(pid, []).append(feat)

        if pid not in pair_midpoints:
            coords = feat["geometry"]["coordinates"]
            if feat["geometry"]["type"] == "MultiLineString":
                # Flatten to get rough midpoint
                flat = [c for part in coords for c in part]
            else:
                flat = coords
            mid_idx = len(flat) // 2
            pair_midpoints[pid] = flat[mid_idx]
            pair_info[pid] = {"name": props.get("name"), "highway": props.get("highway")}

    # --- 2. Classify each pair as footway or road ---
    def _to_set(val):
        if isinstance(val, list):
            return set(val)
        return {val} if val else set()

    def _names(val):
        if isinstance(val, list):
            return set(val)
        return {val} if val else set()

    footway_pids = []
    road_pids_by_name = {}  # name → [pid, ...]

    for pid, info in pair_info.items():
        hw_types = _to_set(info["highway"])
        names = _names(info["name"])

        if hw_types & _FOOTWAY_TYPES:
            footway_pids.append(pid)
        if hw_types & _ROAD_TYPES:
            for n in names:
                road_pids_by_name.setdefault(n, []).append(pid)

    # --- 3. Check each footway against same-name roads ---
    drop_pids = set()

    for pid in footway_pids:
        names = _names(pair_info[pid]["name"])
        fx, fy = pair_midpoints[pid]

        for name in names:
            if name not in road_pids_by_name:
                continue
            for road_pid in road_pids_by_name[name]:
                rx, ry = pair_midpoints[road_pid]
                dx = (fx - rx) * meters_per_degree
                dy = (fy - ry) * meters_per_degree
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < threshold_m:
                    drop_pids.add(pid)
                    break
            if pid in drop_pids:
                break

    # --- 4. Rebuild list without dropped pairs ---
    if drop_pids:
        dropped_count = sum(len(pair_segments[pid]) for pid in drop_pids)
        print(f"Filtered {len(drop_pids)} redundant footway pairs ({dropped_count} features)")

    return [f for f in segments if f["properties"]["pair_id"] not in drop_pids]


def save_geojson(segments, output_path):
    """Save segments to a GeoJSON file."""
    print(f"Saving to {output_path}...")

    geojson = {
        'type': 'FeatureCollection',
        'features': segments
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)

    print(f"Successfully saved {len(segments)} segments to {output_path}")


def main():
    """Main processing pipeline."""
    # Configuration
    lad_name = "Brent"
    lad_code = "E09000005"  # ONS code for Brent

    print("=" * 60)
    print(f"{lad_name} Street Segment Processor")
    print("=" * 60)

    # Step 1: Get ward boundaries for the LAD
    wards_gdf = get_ward_boundaries(lad_name)

    # Step 2: Get postcode centroids for the LAD
    postcodes_gdf = get_postcode_centroids(lad_code)

    # Step 3: Get the road network
    graph = get_brent_road_network()

    # Step 4: Convert to segments and assign wards (splitting at boundaries)
    segments = graph_to_segments(graph, wards_gdf, postcodes_gdf)

    # Step 5: Remove sidewalk footways that duplicate carriageway segments
    segments = filter_redundant_footways(segments)

    # Step 6: Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{lad_name.lower().replace(' ', '_')}_segments_{timestamp}.geojson"
    output_path = Path(__file__).parent.parent / 'output' / output_filename
    save_geojson(segments, output_path)

    print("=" * 60)
    print("Processing complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
