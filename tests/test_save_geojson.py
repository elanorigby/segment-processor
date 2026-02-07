"""Tests for save_geojson() — file I/O."""

import json
from pathlib import Path

from segment_processor.main import save_geojson


class TestSaveGeojson:
    def test_creates_valid_json(self, tmp_path):
        """Output is parseable JSON with type FeatureCollection."""
        out = tmp_path / "test.geojson"
        save_geojson([{"type": "Feature", "properties": {}, "geometry": {}}], out)
        with open(out) as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection"

    def test_features_match_input(self, tmp_path):
        """Written features match input list."""
        features = [
            {"type": "Feature", "properties": {"id": "a"}, "geometry": {}},
            {"type": "Feature", "properties": {"id": "b"}, "geometry": {}},
        ]
        out = tmp_path / "test.geojson"
        save_geojson(features, out)
        with open(out) as f:
            data = json.load(f)
        assert data["features"] == features

    def test_creates_parent_dirs(self, tmp_path):
        """Non-existent parent directories are created."""
        out = tmp_path / "nested" / "dirs" / "test.geojson"
        save_geojson([], out)
        assert out.exists()

    def test_empty_segments(self, tmp_path):
        """Empty list → valid FeatureCollection with 0 features."""
        out = tmp_path / "empty.geojson"
        save_geojson([], out)
        with open(out) as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection"
        assert data["features"] == []
