# Segment Processor

This produces the geojson file(s) used by https://github.com/elanorigby/mapperino.

Street segments are based on data from OpenStreetMap. Segments are calculated as being the stretch of road between one intersection and the next, rather than based on street name.

Ward and postcode data is collected from The Office of National Statistics:

Wards (December 2021) Boundaries UK BGC
https://open-geography-portalx-ons.hub.arcgis.com/datasets/231221d2134643a99a9abd41f565645c/explore

Ward to Local Authority District (May 2025) Lookup in the UK v2
https://geoportal.statistics.gov.uk/datasets/d1668e9ac81743ac9fc99244e6e56b99_0/explore

Online ONS Postcode Directory (Live)
https://www.data.gov.uk/dataset/4c105644-6071-45af-878c-6094a42df866/online-ons-postcode-directory-live1

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


