"""Shared fixtures for segment_processor tests."""

import json

import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree


# ---------------------------------------------------------------------------
# CLI option for output validation tests
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--geojson",
        default="output/brent_segments.geojson",
        help="Path to GeoJSON output file for validation tests",
    )


# ---------------------------------------------------------------------------
# Synthetic ward layout
#
#  51.56 +--------+--------+
#        |        |        |
#        | Alpha  |  Beta  |
#        |        |        |
#  51.54 +--------+--------+
#      -0.30   -0.25    -0.20
#
# Boundary between Alpha and Beta is at x = -0.25
# ---------------------------------------------------------------------------

@pytest.fixture
def two_adjacent_wards():
    """GeoDataFrame with two adjacent ward polygons sharing boundary at x=-0.25."""
    alpha = box(-0.30, 51.54, -0.25, 51.56)
    beta = box(-0.25, 51.54, -0.20, 51.56)
    gdf = gpd.GeoDataFrame(
        {
            "WD23NM": ["Alpha", "Beta"],
            "LAD23NM": ["TestLAD", "TestLAD"],
            "geometry": [alpha, beta],
        },
        crs="EPSG:4326",
    )
    return gdf


@pytest.fixture
def three_wards(two_adjacent_wards):
    """Extends two_adjacent_wards with Gamma below (y=51.52 to 51.54)."""
    gamma = box(-0.30, 51.52, -0.20, 51.54)
    gamma_row = gpd.GeoDataFrame(
        {
            "WD23NM": ["Gamma"],
            "LAD23NM": ["TestLAD"],
            "geometry": [gamma],
        },
        crs="EPSG:4326",
    )
    return gpd.GeoDataFrame(
        pd.concat([two_adjacent_wards, gamma_row], ignore_index=True),
        crs="EPSG:4326",
    )


@pytest.fixture
def ward_spatial_index(two_adjacent_wards):
    """Return (ward_geoms, ward_names, ward_tree) tuple from two_adjacent_wards."""
    ward_geoms = list(two_adjacent_wards.geometry)
    ward_names = list(two_adjacent_wards["WD23NM"])
    ward_tree = STRtree(ward_geoms)
    return ward_geoms, ward_names, ward_tree


@pytest.fixture
def three_ward_spatial_index(three_wards):
    """Return (ward_geoms, ward_names, ward_tree) from three_wards."""
    ward_geoms = list(three_wards.geometry)
    ward_names = list(three_wards["WD23NM"])
    ward_tree = STRtree(ward_geoms)
    return ward_geoms, ward_names, ward_tree


@pytest.fixture
def offset_degrees():
    """Same offset as production code (~4m at London latitude)."""
    return 4.0 / 111000


@pytest.fixture
def postcodes_gdf():
    """Four synthetic postcode points, 2 in each ward."""
    points = [
        Point(-0.28, 51.55),  # in Alpha
        Point(-0.27, 51.55),  # in Alpha
        Point(-0.23, 51.55),  # in Beta
        Point(-0.22, 51.55),  # in Beta
    ]
    return gpd.GeoDataFrame(
        {"PCDS": ["AA1 1AA", "AA1 1AB", "BB1 1BA", "BB1 1BB"], "geometry": points},
        crs="EPSG:4326",
    )


@pytest.fixture
def simple_graph():
    """NetworkX MultiDiGraph with 4 edges for testing graph_to_segments.

    Nodes:
        1: (-0.28, 51.55)  in Alpha
        2: (-0.27, 51.55)  in Alpha
        3: (-0.23, 51.55)  in Beta
        4: (-0.22, 51.55)  in Beta
        5: (-0.25, 51.545) on boundary (Alpha side bottom)
        6: (-0.25, 51.555) on boundary (Alpha side top)
        7: (-0.10, 52.00)  far outside all wards

    Edges:
        1→2 : Interior edge (fully in Alpha, no explicit geometry)
        1→3 : Crossing edge (Alpha→Beta, explicit geometry)
        5→6 : Boundary edge (runs along x=-0.25)
        4→7 : Outside edge (starts in Beta, ends far away)
    """
    G = nx.MultiDiGraph()

    G.add_node(1, x=-0.28, y=51.55)
    G.add_node(2, x=-0.27, y=51.55)
    G.add_node(3, x=-0.23, y=51.55)
    G.add_node(4, x=-0.22, y=51.55)
    G.add_node(5, x=-0.25, y=51.545)
    G.add_node(6, x=-0.25, y=51.555)
    G.add_node(7, x=-0.10, y=52.00)

    # Interior edge: fully in Alpha, no explicit geometry (uses node coords)
    G.add_edge(1, 2, key=0, osmid=101, name="Alpha Street", highway="residential")

    # Crossing edge: Alpha → Beta with explicit geometry
    G.add_edge(
        1, 3, key=0,
        osmid=102,
        name="Cross Road",
        highway="secondary",
        geometry=LineString([(-0.28, 51.55), (-0.25, 51.55), (-0.23, 51.55)]),
    )

    # Boundary edge: runs along the Alpha/Beta boundary at x=-0.25
    G.add_edge(
        5, 6, key=0,
        osmid=103,
        name="Boundary Lane",
        highway="tertiary",
        geometry=LineString([(-0.25, 51.545), (-0.25, 51.555)]),
    )

    # Outside edge: starts in Beta, ends far outside
    G.add_edge(
        4, 7, key=0,
        osmid=104,
        name="Faraway Road",
        highway="trunk",
        geometry=LineString([(-0.22, 51.55), (-0.10, 52.00)]),
    )

    # Unnamed footway edge: should be filtered out
    G.add_edge(
        1, 2, key=1,
        osmid=105,
        highway="footway",
        geometry=LineString([(-0.28, 51.5505), (-0.27, 51.5505)]),
    )

    # Named footway edge: should be KEPT (residential access path)
    G.add_edge(
        1, 2, key=4,
        osmid=110,
        name="Doyle Gardens",
        highway="footway",
        geometry=LineString([(-0.28, 51.5510), (-0.27, 51.5510)]),
    )

    # Cycleway edge: should be filtered out
    G.add_edge(
        3, 4, key=1,
        osmid=106,
        name="Beta Cycle Path",
        highway="cycleway",
        geometry=LineString([(-0.23, 51.5495), (-0.22, 51.5495)]),
    )

    # Link road edge: should be filtered out
    G.add_edge(
        2, 3, key=1,
        osmid=107,
        name="Trunk Slip Road",
        highway="trunk_link",
        geometry=LineString([(-0.27, 51.551), (-0.23, 51.551)]),
    )

    # Unnamed service road: should be filtered out
    G.add_edge(
        1, 2, key=5,
        osmid=111,
        highway="service",
        geometry=LineString([(-0.28, 51.5515), (-0.27, 51.5515)]),
    )

    # Named service road: should be kept
    G.add_edge(
        1, 2, key=6,
        osmid=112,
        name="Alpha Mews",
        highway="service",
        geometry=LineString([(-0.28, 51.5520), (-0.27, 51.5520)]),
    )

    return G


@pytest.fixture(scope="session")
def geojson_data(request):
    """Load real output GeoJSON file. Skip if not found.

    If --geojson is not specified, uses the most recent brent_segments_*.geojson
    file in the output/ directory.
    """
    from pathlib import Path

    path = request.config.getoption("--geojson")
    if path == "output/brent_segments.geojson":
        # Default value — look for the most recent timestamped file instead
        candidates = sorted(Path("output").glob("brent_segments_*.geojson"))
        if candidates:
            path = str(candidates[-1])
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        pytest.skip(f"GeoJSON file not found: {path}")
    return data


# Need pandas for three_wards fixture
import pandas as pd
