# Segment Processor

## Input

Data collected from The Office of National Statistics

Wards (December 2021) Boundaries UK BGC
https://open-geography-portalx-ons.hub.arcgis.com/datasets/231221d2134643a99a9abd41f565645c/explore

Ward to Local Authority District (May 2025) Lookup in the UK v2
https://geoportal.statistics.gov.uk/datasets/d1668e9ac81743ac9fc99244e6e56b99_0/explore

## Output

The generated GeoJSON file can be copied to the Svelte app and loaded directly into Leaflet.

## Setup

```bash
poetry install
```

## Usage

Run the processor to generate the GeoJSON file:

```bash
poetry run python segment_processor/main.py
```

This will create `output/brent_segments.geojson` containing all street segments with:
- Unique segment IDs
- Default red color (#FF0000)
- OSM metadata (road name, type, etc.)
- Geometry as LineString coordinates




