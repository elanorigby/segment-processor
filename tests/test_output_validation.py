"""Structural validation against a real generated GeoJSON output file.

Skipped automatically if the output file doesn't exist.
Path configurable via --geojson CLI option (default: output/brent_segments.geojson).
"""

import re

import pytest


class TestOutputValidation:
    def test_valid_geojson_structure(self, geojson_data):
        assert geojson_data["type"] == "FeatureCollection"
        assert isinstance(geojson_data["features"], list)

    def test_features_not_empty(self, geojson_data):
        assert len(geojson_data["features"]) > 0

    def test_all_features_have_required_keys(self, geojson_data):
        for f in geojson_data["features"]:
            assert "type" in f
            assert "properties" in f
            assert "geometry" in f

    def test_required_properties(self, geojson_data):
        required = {"id", "pair_id", "side", "color", "osm_id", "name", "highway", "lad", "ward", "postcodes"}
        for f in geojson_data["features"]:
            missing = required - set(f["properties"].keys())
            assert not missing, f"Feature {f['properties'].get('id')} missing: {missing}"

    def test_ids_unique(self, geojson_data):
        ids = [f["properties"]["id"] for f in geojson_data["features"]]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found"

    def test_id_format(self, geojson_data):
        """All features: segment_\\d+_[NSEW]."""
        for f in geojson_data["features"]:
            props = f["properties"]
            assert re.match(r"^segment_\d+_[NSEW]$", props["id"]), (
                f"Bad ID: {props['id']}"
            )

    def test_pairs_valid(self, geojson_data):
        """Every pair_id appears exactly 2x, with different side."""
        pairs = {}
        for f in geojson_data["features"]:
            props = f["properties"]
            pid = props["pair_id"]
            pairs.setdefault(pid, []).append(props)

        for pid, members in pairs.items():
            assert len(members) == 2, f"pair_id {pid} has {len(members)} members"
            sides = {m["side"] for m in members}
            assert len(sides) == 2, f"pair_id {pid} has duplicate sides: {sides}"

    def test_sides_valid(self, geojson_data):
        """All side values in {'N','S','E','W'}."""
        valid_sides = {"N", "S", "E", "W"}
        for f in geojson_data["features"]:
            props = f["properties"]
            assert props["side"] in valid_sides, f"Invalid side: {props['side']}"

    def test_geometry_types_valid(self, geojson_data):
        """All geometries are LineString or MultiLineString."""
        valid = {"LineString", "MultiLineString"}
        for f in geojson_data["features"]:
            assert f["geometry"]["type"] in valid, (
                f"Feature {f['properties']['id']} has type {f['geometry']['type']}"
            )

    def test_coordinates_wgs84(self, geojson_data):
        """Longitudes in [-1, 1], latitudes in [51, 52] (London)."""
        for f in geojson_data["features"]:
            geom = f["geometry"]
            if geom["type"] == "LineString":
                coords_list = [geom["coordinates"]]
            else:
                coords_list = geom["coordinates"]
            for coords in coords_list:
                for lon, lat in coords:
                    assert -1 <= lon <= 1, f"Longitude {lon} out of range"
                    assert 51 <= lat <= 52, f"Latitude {lat} out of range"

    def test_no_empty_coordinates(self, geojson_data):
        """No empty coordinate arrays."""
        for f in geojson_data["features"]:
            geom = f["geometry"]
            if geom["type"] == "LineString":
                assert len(geom["coordinates"]) > 0
            else:
                for part in geom["coordinates"]:
                    assert len(part) > 0

    def test_no_degenerate_linestrings(self, geojson_data):
        """Every LineString has >=2 points."""
        for f in geojson_data["features"]:
            geom = f["geometry"]
            if geom["type"] == "LineString":
                assert len(geom["coordinates"]) >= 2, (
                    f"Degenerate LineString in {f['properties']['id']}"
                )
            else:
                for part in geom["coordinates"]:
                    assert len(part) >= 2

    def test_postcodes_is_list_of_strings(self, geojson_data):
        """postcodes is always list[str]."""
        for f in geojson_data["features"]:
            pc = f["properties"]["postcodes"]
            assert isinstance(pc, list)
            for p in pc:
                assert isinstance(p, str)

    def test_color_hex_format(self, geojson_data):
        """color matches #[0-9A-Fa-f]{6}."""
        for f in geojson_data["features"]:
            assert re.match(r"^#[0-9A-Fa-f]{6}$", f["properties"]["color"]), (
                f"Bad color: {f['properties']['color']}"
            )

    def test_ward_and_lad_not_empty(self, geojson_data):
        """ward and lad are non-empty strings."""
        for f in geojson_data["features"]:
            assert isinstance(f["properties"]["ward"], str) and f["properties"]["ward"]
            assert isinstance(f["properties"]["lad"], str) and f["properties"]["lad"]
