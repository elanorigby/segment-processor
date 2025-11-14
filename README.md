# Segment Processor

Extracts street segments from OpenStreetMap for the London Borough of Brent.

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

## Output

The generated GeoJSON file can be copied to the Svelte app and loaded directly into Leaflet.
