"""Tests for _get_cardinal_sides() — pure geometry math."""

from shapely.geometry import LineString

from segment_processor.main import _get_cardinal_sides


class TestCardinalSides:
    def test_east_heading(self):
        """East-heading road (0,0)→(1,0): left=N, right=S."""
        line = LineString([(0, 0), (1, 0)])
        assert _get_cardinal_sides(line) == ("N", "S")

    def test_west_heading(self):
        """West-heading road (1,0)→(0,0): left=S, right=N."""
        line = LineString([(1, 0), (0, 0)])
        assert _get_cardinal_sides(line) == ("S", "N")

    def test_north_heading(self):
        """North-heading road (0,0)→(0,1): left=W, right=E."""
        line = LineString([(0, 0), (0, 1)])
        assert _get_cardinal_sides(line) == ("W", "E")

    def test_south_heading(self):
        """South-heading road (0,1)→(0,0): left=E, right=W."""
        line = LineString([(0, 1), (0, 0)])
        assert _get_cardinal_sides(line) == ("E", "W")

    def test_ne_diagonal(self):
        """NE diagonal bearing ~45° → E-W bucket → (N, S)."""
        line = LineString([(0, 0), (1, 1)])
        assert _get_cardinal_sides(line) == ("N", "S")

    def test_nw_diagonal(self):
        """NW diagonal bearing ~315° → N-S bucket → (W, E)."""
        line = LineString([(0, 0), (-1, 1)])
        assert _get_cardinal_sides(line) == ("W", "E")

    def test_se_diagonal(self):
        """SE diagonal bearing ~135° → N-S bucket → (E, W)."""
        line = LineString([(0, 0), (1, -1)])
        assert _get_cardinal_sides(line) == ("E", "W")

    def test_sw_diagonal(self):
        """SW diagonal bearing ~225° → E-W bucket → (S, N)."""
        line = LineString([(0, 0), (-1, -1)])
        assert _get_cardinal_sides(line) == ("S", "N")

    def test_mostly_east(self):
        """Mostly east with slight slope: left=N, right=S."""
        line = LineString([(0, 0), (10, 1)])
        assert _get_cardinal_sides(line) == ("N", "S")

    def test_mostly_north(self):
        """Mostly north with slight drift: left=W, right=E."""
        line = LineString([(0, 0), (1, 10)])
        assert _get_cardinal_sides(line) == ("W", "E")

    def test_curvy_road_uses_endpoints(self):
        """Sinuous line — only first/last coords matter."""
        line = LineString([(0, 0), (0.5, 0.5), (1, -0.5), (2, 0)])
        # Endpoints: (0,0)→(2,0) = east heading
        expected = _get_cardinal_sides(LineString([(0, 0), (2, 0)]))
        assert _get_cardinal_sides(line) == expected
