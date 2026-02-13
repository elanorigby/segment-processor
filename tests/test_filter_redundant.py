"""Tests for filter_redundant_footways deduplication."""

from shapely.geometry import LineString

from segment_processor.main import filter_redundant_footways


def _make_segment(segment_id, name, highway, lat, side="N"):
    """Build a minimal GeoJSON feature for testing.

    Creates an east-west line at the given latitude, roughly 100m long.
    """
    coords = [(-0.28, lat), (-0.27, lat)]
    return {
        "type": "Feature",
        "properties": {
            "id": f"segment_{segment_id}_{side}",
            "pair_id": f"segment_{segment_id}",
            "side": side,
            "name": name,
            "highway": highway,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        },
    }


def _make_pair(segment_id, name, highway, lat):
    """Build N and S side features for one segment."""
    return [
        _make_segment(segment_id, name, highway, lat, "N"),
        _make_segment(segment_id, name, highway, lat, "S"),
    ]


class TestFilterRedundantFootways:
    """Footway segments that duplicate a nearby road should be removed."""

    def test_drops_footway_parallel_to_road_same_name(self):
        """A footway ~5m from a tertiary road with the same name is redundant."""
        # Tertiary road at lat 51.55
        road = _make_pair(0, "Brondesbury Park", "tertiary", 51.55)
        # Footway ~5m north (0.00005 degrees ≈ 5.5m)
        footway = _make_pair(1, "Brondesbury Park", "footway", 51.55005)

        result = filter_redundant_footways(road + footway)

        pair_ids = [f["properties"]["pair_id"] for f in result]
        assert "segment_0" in pair_ids, "road should be kept"
        assert "segment_1" not in pair_ids, "footway should be dropped"
        assert len(result) == 2

    def test_keeps_standalone_footway(self):
        """A footway with no nearby road of the same name should be kept."""
        road = _make_pair(0, "High Street", "residential", 51.55)
        footway = _make_pair(1, "Garden Path", "footway", 51.55005)

        result = filter_redundant_footways(road + footway)

        assert len(result) == 4, "all segments should be kept"

    def test_keeps_footway_far_from_road(self):
        """A footway > 15m from a same-named road should be kept."""
        road = _make_pair(0, "Long Lane", "tertiary", 51.55)
        # ~25m away (0.00023 degrees ≈ 25m)
        footway = _make_pair(1, "Long Lane", "footway", 51.55023)

        result = filter_redundant_footways(road + footway)

        assert len(result) == 4

    def test_handles_list_name(self):
        """Names can be lists — any shared name should trigger dedup."""
        road = _make_pair(0, ["Acton Lane", "B4492"], "primary", 51.55)
        footway = _make_pair(1, "Acton Lane", "footway", 51.55005)

        result = filter_redundant_footways(road + footway)

        pair_ids = [f["properties"]["pair_id"] for f in result]
        assert "segment_1" not in pair_ids, "footway should be dropped"

    def test_handles_list_highway(self):
        """Highway can be a list — footway in list should be detected."""
        road = _make_pair(0, "Chambers Lane", "secondary", 51.55)
        footway = _make_pair(1, "Chambers Lane", ["footway", "crossing"], 51.55005)

        result = filter_redundant_footways(road + footway)

        pair_ids = [f["properties"]["pair_id"] for f in result]
        assert "segment_1" not in pair_ids

    def test_never_drops_road(self):
        """Even if two road types overlap, neither should be dropped."""
        road1 = _make_pair(0, "Shared Road", "tertiary", 51.55)
        road2 = _make_pair(1, "Shared Road", "unclassified", 51.55005)

        result = filter_redundant_footways(road1 + road2)

        assert len(result) == 4, "both roads should be kept"

    def test_drops_path_same_as_footway(self):
        """highway=path should also be dropped when near a road."""
        road = _make_pair(0, "Park Avenue", "residential", 51.55)
        path = _make_pair(1, "Park Avenue", "path", 51.55005)

        result = filter_redundant_footways(road + path)

        assert len(result) == 2
