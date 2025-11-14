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
import networkx as nx
import urllib.request
import zipfile
import tempfile


def get_ward_boundaries():
    """
    Download and load ward boundaries for the UK (December 2021).

    Returns a GeoDataFrame filtered to Brent wards only.
    """
    print("Loading ward boundaries...")

    cache_dir = Path(__file__).parent.parent / 'cache'
    cache_dir.mkdir(parents=True, exist_ok=True)

    gpkg_path = cache_dir / 'wards_dec_2021_uk.gpkg'

    # Download if not cached
    if not gpkg_path.exists():
        print("Downloading ward boundaries from ONS...")
        url = "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/231221d2134643a99a9abd41f565645c/geoPackage?layers=0"

        urllib.request.urlretrieve(url, gpkg_path)
        print(f"Ward boundaries downloaded to {gpkg_path}")
    else:
        print("Using cached ward boundaries")

    # Load the geopackage
    wards_gdf = gpd.read_file(gpkg_path)

    print(f"Loaded {len(wards_gdf)} wards total")

    # Filter to Brent wards only
    # The data should have a LAD21NM (Local Authority District Name) or similar field
    print(f"Available columns: {list(wards_gdf.columns)}")

    # Try to filter by Brent - need to check the column name
    brent_column = None
    for col in wards_gdf.columns:
        if 'LAD' in col and 'NM' in col:  # Looking for LAD name column
            brent_column = col
            break

    if brent_column:
        brent_wards = wards_gdf[wards_gdf[brent_column] == 'Brent'].copy()
        print(f"Filtered to {len(brent_wards)} wards in Brent using column '{brent_column}'")
    else:
        print("Warning: Could not find LAD name column, using all wards")
        brent_wards = wards_gdf.copy()

    # Ensure CRS is WGS84 (EPSG:4326) to match OSM data
    if brent_wards.crs != 'EPSG:4326':
        brent_wards = brent_wards.to_crs('EPSG:4326')

    return brent_wards


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


def graph_to_segments(graph, wards_gdf):
    """
    Convert the OSMnx graph into individual segments and split at ward boundaries.

    Each segment is a portion of road between two intersection nodes.
    If a segment crosses ward boundaries, it will be split at those boundaries.

    Args:
        graph: OSMnx graph
        wards_gdf: GeoDataFrame of ward boundaries

    Returns:
        List of segment features with ward assignments
    """
    print("Converting graph to segments...")

    # Find the ward name column
    ward_name_col = None
    for col in wards_gdf.columns:
        if 'WD' in col and 'NM' in col:  # Looking for Ward Name column
            ward_name_col = col
            break

    if not ward_name_col:
        print("Warning: Could not find ward name column, using first non-geometry column")
        ward_name_col = [col for col in wards_gdf.columns if col != 'geometry'][0]

    print(f"Using ward name column: {ward_name_col}")

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
            # No ward found - create segment without ward
            segment = {
                'type': 'Feature',
                'properties': {
                    'id': f'segment_{segment_id}',
                    'color': '#FF0000',
                    'osm_id': data.get('osmid', None),
                    'name': data.get('name', 'Unnamed'),
                    'highway': data.get('highway', 'unknown'),
                    'ward': None,
                },
                'geometry': {
                    'type': 'LineString',
                    'coordinates': list(geometry.coords)
                }
            }
            segments.append(segment)
            segment_id += 1

        elif len(intersecting_wards) == 1:
            # Segment is entirely in one ward
            ward_name = intersecting_wards.iloc[0][ward_name_col]
            segment = {
                'type': 'Feature',
                'properties': {
                    'id': f'segment_{segment_id}',
                    'color': '#FF0000',
                    'osm_id': data.get('osmid', None),
                    'name': data.get('name', 'Unnamed'),
                    'highway': data.get('highway', 'unknown'),
                    'ward': ward_name,
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
                            segment = {
                                'type': 'Feature',
                                'properties': {
                                    'id': f'segment_{segment_id}',
                                    'color': '#FF0000',
                                    'osm_id': data.get('osmid', None),
                                    'name': data.get('name', 'Unnamed'),
                                    'highway': data.get('highway', 'unknown'),
                                    'ward': ward_name,
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
    print("=" * 60)
    print("Brent Street Segment Processor")
    print("=" * 60)

    # Step 1: Get ward boundaries
    wards_gdf = get_ward_boundaries()

    # Step 2: Get the road network
    graph = get_brent_road_network()

    # Step 3: Convert to segments and assign wards (splitting at boundaries)
    segments = graph_to_segments(graph, wards_gdf)

    # Step 4: Save to file
    output_path = Path(__file__).parent.parent / 'output' / 'brent_segments.geojson'
    save_geojson(segments, output_path)

    print("=" * 60)
    print("Processing complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
