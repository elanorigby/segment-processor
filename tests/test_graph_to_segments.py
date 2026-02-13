"""Integration tests for graph_to_segments()."""

import pytest
from shapely.geometry import LineString

from segment_processor.main import graph_to_segments


class TestGraphToSegments:
    def _run(self, simple_graph, two_adjacent_wards, postcodes_gdf=None):
        return graph_to_segments(simple_graph, two_adjacent_wards, postcodes_gdf)

    def test_interior_edge_two_sides(self, simple_graph, two_adjacent_wards):
        """Edge fully in Alpha → 2 side features, both ward='Alpha'."""
        segments = self._run(simple_graph, two_adjacent_wards)
        interior = [s for s in segments if s["properties"]["osm_id"] == 101]
        assert len(interior) == 2
        assert interior[0]["properties"]["pair_id"] == interior[1]["properties"]["pair_id"]
        assert interior[0]["properties"]["side"] != interior[1]["properties"]["side"]
        for s in interior:
            assert s["properties"]["ward"] == "Alpha"

    def test_crossing_edge_splits(self, simple_graph, two_adjacent_wards):
        """Edge across Alpha+Beta → 2+ side features per piece, both wards present."""
        segments = self._run(simple_graph, two_adjacent_wards)
        crossing = [s for s in segments if s["properties"]["osm_id"] == 102]
        # Each ward piece produces 2 side features, so at least 4
        assert len(crossing) >= 4
        wards = {s["properties"]["ward"] for s in crossing}
        assert "Alpha" in wards
        assert "Beta" in wards
        # All crossing features have pair_id and side
        for s in crossing:
            assert "pair_id" in s["properties"]
            assert "side" in s["properties"]

    def test_boundary_edge_pair(self, simple_graph, two_adjacent_wards):
        """Boundary edge → side features with pair_id and side."""
        segments = self._run(simple_graph, two_adjacent_wards)
        boundary = [s for s in segments if s["properties"]["osm_id"] == 103]
        # Boundary edge sits on the ward border — may intersect both wards
        # and get split, producing 2 side features per piece
        assert len(boundary) >= 2
        # All features have pair_id and side
        for s in boundary:
            assert "pair_id" in s["properties"]
            assert "side" in s["properties"]
        # Each pair_id appears exactly twice with different sides
        pairs = {}
        for s in boundary:
            pid = s["properties"]["pair_id"]
            pairs.setdefault(pid, []).append(s)
        for pid, members in pairs.items():
            assert len(members) == 2
            assert members[0]["properties"]["side"] != members[1]["properties"]["side"]

    def test_outside_edge_skipped(self, simple_graph, two_adjacent_wards):
        """Edge mostly outside wards → side features only in known wards."""
        segments = self._run(simple_graph, two_adjacent_wards)
        outside = [s for s in segments if s["properties"]["osm_id"] == 104]
        for s in outside:
            assert s["properties"]["ward"] in ("Alpha", "Beta")

    def test_all_ids_unique(self, simple_graph, two_adjacent_wards):
        """No duplicate IDs across all features."""
        segments = self._run(simple_graph, two_adjacent_wards)
        ids = [s["properties"]["id"] for s in segments]
        assert len(ids) == len(set(ids))

    def test_required_properties_present(self, simple_graph, two_adjacent_wards):
        """Every feature has required properties including pair_id and side."""
        segments = self._run(simple_graph, two_adjacent_wards)
        required = {"id", "pair_id", "side", "color", "osm_id", "name", "highway", "lad", "ward", "postcodes"}
        for s in segments:
            assert required.issubset(set(s["properties"].keys())), (
                f"Missing keys in {s['properties']['id']}: "
                f"{required - set(s['properties'].keys())}"
            )

    def test_postcodes_when_nearby(self, simple_graph, two_adjacent_wards, postcodes_gdf):
        """With postcodes_gdf, nearby features get non-empty postcodes."""
        segments = self._run(simple_graph, two_adjacent_wards, postcodes_gdf)
        has_postcodes = [s for s in segments if s["properties"]["postcodes"]]
        assert len(has_postcodes) > 0

    def test_no_postcodes_when_none(self, simple_graph, two_adjacent_wards):
        """postcodes_gdf=None → all postcodes == []."""
        segments = self._run(simple_graph, two_adjacent_wards, None)
        for s in segments:
            assert s["properties"]["postcodes"] == []

    def test_edge_without_geometry_uses_nodes(self, simple_graph, two_adjacent_wards):
        """Edge with no geometry attr → straight line from node coords."""
        segments = self._run(simple_graph, two_adjacent_wards)
        # Edge 1→2 (osmid=101) has no geometry attribute — produces 2 side features
        interior = [s for s in segments if s["properties"]["osm_id"] == 101]
        assert len(interior) == 2

    def test_unnamed_footway_filtered_out(self, simple_graph, two_adjacent_wards):
        """Unnamed footway edges are excluded from output."""
        segments = self._run(simple_graph, two_adjacent_wards)
        footway = [s for s in segments if s["properties"]["osm_id"] == 105]
        assert len(footway) == 0

    def test_named_footway_kept(self, simple_graph, two_adjacent_wards):
        """Named footway edges are kept (residential access paths)."""
        segments = self._run(simple_graph, two_adjacent_wards)
        named_footway = [s for s in segments if s["properties"]["osm_id"] == 110]
        assert len(named_footway) >= 2  # kept and split into sides

    def test_cycleway_filtered_out(self, simple_graph, two_adjacent_wards):
        """Cycleway edges are excluded from output."""
        segments = self._run(simple_graph, two_adjacent_wards)
        cycleway = [s for s in segments if s["properties"]["osm_id"] == 106]
        assert len(cycleway) == 0

    def test_unnamed_service_filtered_out(self, simple_graph, two_adjacent_wards):
        """Unnamed service roads are excluded from output."""
        segments = self._run(simple_graph, two_adjacent_wards)
        unnamed_svc = [s for s in segments if s["properties"]["osm_id"] == 111]
        assert len(unnamed_svc) == 0

    def test_named_service_kept(self, simple_graph, two_adjacent_wards):
        """Named service roads are kept."""
        segments = self._run(simple_graph, two_adjacent_wards)
        named_svc = [s for s in segments if s["properties"]["osm_id"] == 112]
        assert len(named_svc) >= 2  # kept and split into sides

    def test_link_road_filtered_out(self, simple_graph, two_adjacent_wards):
        """Link road edges (e.g. trunk_link) are excluded from output."""
        segments = self._run(simple_graph, two_adjacent_wards)
        link = [s for s in segments if s["properties"]["osm_id"] == 107]
        assert len(link) == 0

    def test_list_highway_all_excluded(self, simple_graph, two_adjacent_wards):
        """Unnamed edge with highway=['footway','path'] (all excluded) is filtered out."""
        simple_graph.add_edge(
            1, 2, key=2,
            osmid=108,
            highway=["footway", "path"],
            geometry=LineString([(-0.28, 51.549), (-0.27, 51.549)]),
        )
        segments = self._run(simple_graph, two_adjacent_wards)
        multi = [s for s in segments if s["properties"]["osm_id"] == 108]
        assert len(multi) == 0

    def test_list_highway_partially_excluded(self, simple_graph, two_adjacent_wards):
        """Edge with highway=['footway','residential'] (not all excluded) is kept."""
        simple_graph.add_edge(
            1, 2, key=3,
            osmid=109,
            name="Mixed Tag Road",
            highway=["footway", "residential"],
            geometry=LineString([(-0.28, 51.548), (-0.27, 51.548)]),
        )
        segments = self._run(simple_graph, two_adjacent_wards)
        mixed = [s for s in segments if s["properties"]["osm_id"] == 109]
        assert len(mixed) >= 2  # kept and split into sides

    def test_missing_lad_col_raises(self, simple_graph):
        """Ward GDF without LAD*NM column → ValueError."""
        import geopandas as gpd
        from shapely.geometry import box
        gdf = gpd.GeoDataFrame(
            {"WD23NM": ["A"], "geometry": [box(0, 0, 1, 1)]},
            crs="EPSG:4326",
        )
        with pytest.raises(ValueError, match="LAD name column"):
            graph_to_segments(simple_graph, gdf)
