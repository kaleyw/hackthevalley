# TTC geographic data

Contains information licensed under the Open Government Licence – Toronto.
Credit: City of Toronto / Toronto Transit Commission.

- Stations: City of Toronto GIS, `cot_geospatial7/MapServer/8` (Public Transit).
  https://gis.toronto.ca/arcgis/rest/services/cot_geospatial7/MapServer/8
- Lines: City of Toronto GIS, `cot_geospatial7/MapServer/11` (TTC Subway Route).
  https://gis.toronto.ca/arcgis/rest/services/cot_geospatial7/MapServer/11
- Licence: https://open.toronto.ca/open-data-license/
- Retrieved 2026-10-17, using `query?where=1%3D1&outFields=...&outSR=4326&f=json`.
  ArcGIS points and paths were converted to WGS84 GeoJSON. Station fields retained:
  PT_ID, PT_NAME. Route fields: ROUTE_ID, ROUTE_SHORT_NAME, ROUTE_LONG_NAME,
  ROUTE_COLOR. No station/line geometry was invented or simplified.

The snapshot contains 73 station points and five route features, as supplied by
those layers on retrieval. It is not a statement of current service, closures,
completeness, platform layouts, entrances, accessibility, or emergency access.
Official station points are treated as **approximate station locations**, not
surveyed platform or entrance positions. Older/renamed station labels may remain.

There is no remote tile dependency. Leaflet renders the locally stored vectors
on a plain geographic canvas. The textual briefing works even if these files fail.

**DEMO-T1 is synthetic:** movement is interpolated on straight segments between
the official Union, King, Queen, and Dundas station points, not surveyed tracks.
Its timing, direction, car identifier, and position are not live TTC telemetry.
The provider can be replaced; no compatible live subway feed is configured.
