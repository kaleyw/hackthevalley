# TTC geographic data

Contains information licensed under the Open Government Licence – Toronto.
Credit: City of Toronto / Toronto Transit Commission.

- Stations: City of Toronto GIS, `cot_geospatial7/MapServer/8` (Public Transit).
  https://gis.toronto.ca/arcgis/rest/services/cot_geospatial7/MapServer/8
- Lines: City of Toronto GIS, `cot_geospatial7/MapServer/11` (TTC Subway Route).
  https://gis.toronto.ca/arcgis/rest/services/cot_geospatial7/MapServer/11
- Licence: https://open.toronto.ca/open-data-licence/
- Retrieved 2026-10-17, using `query?where=1%3D1&outFields=...&outSR=4326&f=json`.
  ArcGIS points and paths were converted to WGS84 GeoJSON. Station fields retained:
  PT_ID, PT_NAME. Route fields: ROUTE_ID, ROUTE_SHORT_NAME, ROUTE_LONG_NAME,
  ROUTE_COLOR. No station/line geometry was invented or simplified.

The snapshot contains 68 station points and five route features. The five Line 3
Scarborough RT stations (McCowan, Scarborough Centre, Midland, Ellesmere, Lawrence East)
were removed because the line closed in 2023 and has no route geometry in the data.
Lines 5 (Eglinton) and 6 (Finch West) are in the route data but hidden on the map,
because the station layer has no stops for these light-rail lines. It is not a statement of current service, closures,
completeness, platform layouts, entrances, accessibility, or emergency access.
Official station points are treated as **approximate station locations**, not
surveyed platform or entrance positions. Older/renamed station labels may remain.

## Street map background

When online, the map shows OpenStreetMap's standard tiles (faded) behind the TTC lines
(© OpenStreetMap contributors, used under the OSM tile usage policy for light use).
Loading tiles tells OpenStreetMap which area of the map is being viewed and this
site's origin, not anything about an alert. Without internet the map falls back to the locally stored TTC lines and
stations on a plain canvas, and the textual briefing works even if all map data fails.
