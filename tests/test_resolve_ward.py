"""Tests for _resolve_ward() — spatial index queries."""

from shapely.geometry import LineString

from segment_processor.main import _resolve_ward


class TestResolveWard:
    def test_line_entirely_in_alpha(self, ward_spatial_index):
        """Line fully inside Alpha → 'Alpha'."""
        geoms, names, tree = ward_spatial_index
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        assert _resolve_ward(line, geoms, names, tree) == "Alpha"

    def test_line_entirely_in_beta(self, ward_spatial_index):
        """Line fully inside Beta → 'Beta'."""
        geoms, names, tree = ward_spatial_index
        line = LineString([(-0.23, 51.55), (-0.22, 51.55)])
        assert _resolve_ward(line, geoms, names, tree) == "Beta"

    def test_majority_in_alpha(self, ward_spatial_index):
        """70% Alpha / 30% Beta → 'Alpha'."""
        geoms, names, tree = ward_spatial_index
        # Line from x=-0.28 to x=-0.22: total 0.06 degrees
        # Alpha portion: -0.28 to -0.25 = 0.03 (50%)
        # Use a line that's 70% in Alpha:
        # From x=-0.285 to x=-0.235: Alpha portion 0.035/0.05 = 70%
        line = LineString([(-0.285, 51.55), (-0.235, 51.55)])
        assert _resolve_ward(line, geoms, names, tree) == "Alpha"

    def test_majority_in_beta(self, ward_spatial_index):
        """30% Alpha / 70% Beta → 'Beta'."""
        geoms, names, tree = ward_spatial_index
        line = LineString([(-0.265, 51.55), (-0.215, 51.55)])
        assert _resolve_ward(line, geoms, names, tree) == "Beta"

    def test_outside_all_wards(self, ward_spatial_index):
        """Line far from all wards → None."""
        geoms, names, tree = ward_spatial_index
        line = LineString([(0.0, 52.0), (0.1, 52.0)])
        assert _resolve_ward(line, geoms, names, tree) is None

    def test_single_ward_hit_fast_path(self, ward_spatial_index):
        """Line fully in one ward, STRtree returns exactly 1 hit → fast path."""
        geoms, names, tree = ward_spatial_index
        line = LineString([(-0.29, 51.55), (-0.28, 51.55)])
        result = _resolve_ward(line, geoms, names, tree)
        assert result == "Alpha"

    def test_three_wards_picks_majority(self, three_ward_spatial_index):
        """Line crossing all three wards → longest intersection wins."""
        geoms, names, tree = three_ward_spatial_index
        # Line runs from Alpha (top-left) down through Gamma (bottom), mostly in Gamma
        # Gamma: y=51.52 to 51.54, Alpha: y=51.54 to 51.56
        # Line from (-0.28, 51.56) to (-0.28, 51.52) — 50% Alpha, 50% Gamma
        # Shift to favor Gamma: (-0.28, 51.55) to (-0.28, 51.52) — 1/3 Alpha, 2/3 Gamma
        line = LineString([(-0.28, 51.55), (-0.28, 51.52)])
        result = _resolve_ward(line, geoms, names, tree)
        assert result == "Gamma"
