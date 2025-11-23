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

import osmnx as ox
import geopandas as gpd
import json
import sys
from pathlib import Path
from shapely.geometry import LineString, Point
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

        elif len(intersecting_wards) == 1:
            # Segment is entirely in one ward
            ward_row = intersecting_wards.iloc[0]
            ward_name = ward_row[ward_name_col]
            lad_name = ward_row[lad_name_col]
            postcodes = find_postcodes_for_geometry(geometry)
            segment = {
                'type': 'Feature',
                'properties': {
                    'id': f'segment_{segment_id}',
                    'color': '#FF0000',
                    'osm_id': data.get('osmid', None),
                    'name': data.get('name', 'Unnamed'),
                    'highway': data.get('highway', 'unknown'),
                    'lad': lad_name,
                    'ward': ward_name,
                    'postcodes': postcodes,
                },
                'geometry': {
                    'type': 'LineString',
                    'coordinates': list(geometry.coords)
                }
            }
            segments.append(segment)
            segment_id += 1

        else:
            # Segment crosses multiple wards - split it
            for _, ward in intersecting_wards.iterrows():
                ward_geom = ward['geometry']
                ward_name = ward[ward_name_col]
                lad_name = ward[lad_name_col]

                # Get the portion of the segment that's in this ward
                try:
                    intersection = geometry.intersection(ward_geom)

                    # Only process if intersection is a LineString
                    if intersection.is_empty:
                        continue

                    # Handle MultiLineString results
                    if intersection.geom_type == 'LineString':
                        lines_to_add = [intersection]
                    elif intersection.geom_type == 'MultiLineString':
                        lines_to_add = list(intersection.geoms)
                    else:
                        # Skip points or other geometry types
                        continue

                    for line in lines_to_add:
                        if line.length > 0:  # Only add non-zero length segments
                            postcodes = find_postcodes_for_geometry(line)
                            segment = {
                                'type': 'Feature',
                                'properties': {
                                    'id': f'segment_{segment_id}',
                                    'color': '#FF0000',
                                    'osm_id': data.get('osmid', None),
                                    'name': data.get('name', 'Unnamed'),
                                    'highway': data.get('highway', 'unknown'),
                                    'lad': lad_name,
                                    'ward': ward_name,
                                    'postcodes': postcodes,
                                },
                                'geometry': {
                                    'type': 'LineString',
                                    'coordinates': list(line.coords)
                                }
                            }
                            segments.append(segment)
                            segment_id += 1

                except Exception as e:
                    # If intersection fails, skip this ward
                    print(f"Warning: Failed to split segment at ward boundary: {e}")
                    continue

        processed += 1
        if processed % 5000 == 0:
            print(f"Processed {processed}/{total_edges} edges, created {len(segments)} segments")

    print(f"Created {len(segments)} segments from {total_edges} edges")
    return segments


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

    # Step 5: Save to file
    output_filename = f"{lad_name.lower().replace(' ', '_')}_segments.geojson"
    output_path = Path(__file__).parent.parent / 'output' / output_filename
    save_geojson(segments, output_path)

    print("=" * 60)
    print("Processing complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
