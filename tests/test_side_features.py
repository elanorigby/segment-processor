"""Tests for _make_side_features() — feature construction for all roads."""

from unittest.mock import MagicMock

from shapely.geometry import LineString, MultiLineString

from segment_processor.main import _make_side_features


def _make_ward_index():
    """Build simple ward spatial index with Alpha (left) and Beta (right)."""
    from shapely.geometry import box
    from shapely.strtree import STRtree

    alpha = box(-0.30, 51.54, -0.25, 51.56)
    beta = box(-0.25, 51.54, -0.20, 51.56)
    ward_geoms = [alpha, beta]
    ward_names = ["Alpha", "Beta"]
    ward_tree = STRtree(ward_geoms)
    return ward_geoms, ward_names, ward_tree


def _make_data(**overrides):
    """Helper to build edge data dict."""
    d = {"osmid": 42, "name": "Test Road", "highway": "residential"}
    d.update(overrides)
    return d


def _make_ward_to_lad():
    return {"Alpha": "TestLAD", "Beta": "TestLAD"}


OFFSET = 4.0 / 111000  # ~4m at London latitude


class TestMakeSideFeatures:
    def test_returns_two_features(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        assert len(features) == 2

    def test_ids_include_cardinal(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        ids = {f["properties"]["id"] for f in features}
        # East-west road → N/S sides
        assert ids == {"segment_7_N", "segment_7_S"}

    def test_pair_id_matches(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        for f in features:
            assert f["properties"]["pair_id"] == "segment_7"

    def test_side_property_set(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        sides = {f["properties"]["side"] for f in features}
        assert sides == {"N", "S"}

    def test_interior_road_same_ward_both_sides(self):
        """Road well inside Alpha → both sides get ward Alpha."""
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.29, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            0, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        assert len(features) == 2
        for f in features:
            assert f["properties"]["ward"] == "Alpha"

    def test_boundary_road_different_wards(self):
        """Road along x=-0.25 boundary → different wards per side."""
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.25, 51.545), (-0.25, 51.555)])
        features = _make_side_features(
            0, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        assert len(features) == 2
        wards = {f["properties"]["ward"] for f in features}
        assert wards == {"Alpha", "Beta"}

    def test_lad_from_lookup(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        for f in features:
            assert f["properties"]["lad"] == "TestLAD"

    def test_lad_fallback(self):
        """Ward not in lookup → uses fallback_lad."""
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            {}, "Alpha", "FallbackLAD", OFFSET, lambda g: [],
        )
        for f in features:
            assert f["properties"]["lad"] == "FallbackLAD"

    def test_postcodes_called_per_side(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        mock_fn = MagicMock(return_value=["PC1 1AA"])
        features = _make_side_features(
            7, line, _make_data(), geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, mock_fn,
        )
        assert mock_fn.call_count == 2

    def test_data_propagated(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        data = _make_data(osmid=99, name="Main St", highway="primary")
        features = _make_side_features(
            7, line, data, geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        for f in features:
            assert f["properties"]["osm_id"] == 99
            assert f["properties"]["name"] == "Main St"
            assert f["properties"]["highway"] == "primary"

    def test_missing_data_defaults(self):
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        features = _make_side_features(
            7, line, {}, geoms, names, tree,
            _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
        )
        for f in features:
            assert f["properties"]["name"] == "Unnamed"
            assert f["properties"]["highway"] == "unknown"
            assert f["properties"]["osm_id"] is None

    def test_offset_failure_uses_original_geometry(self):
        """When offset_curve fails, both sides use the original geometry."""
        from unittest.mock import patch
        geoms, names, tree = _make_ward_index()
        line = LineString([(-0.28, 51.55), (-0.27, 51.55)])
        with patch("segment_processor.main.offset_curve", side_effect=RuntimeError("boom")):
            features = _make_side_features(
                7, line, _make_data(), geoms, names, tree,
                _make_ward_to_lad(), "Alpha", "TestLAD", OFFSET, lambda g: [],
            )
        assert len(features) == 2
        # Both sides should fall back to the fallback ward
        for f in features:
            assert f["properties"]["ward"] == "Alpha"
