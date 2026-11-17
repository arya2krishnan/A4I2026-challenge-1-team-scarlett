-- 00  Pull the built-environment slice of OpenStreetMap that covers Chicago (one-off; ~minutes).
--
-- Heat in a city is mostly the built environment: rooftops and pavement hold heat, parks and trees do not. The loaded
-- tables carry none of that, so this brings it in from `bigquery-public-data.geo_openstreetmap` (ODbL, (c) OpenStreetMap
-- contributors: attribute it). planet_features is clustered by geometry, so the bounding-box filter prunes most of the
-- 352 GB. We keep only the tags we turn into features, classified once here.
--
--   building      roof area
--   green         parks, grass, forest, wood, cemeteries, recreation: cooler
--   paved_use     industrial, commercial, retail, railway, parking: hot, mostly impervious
--   road          street length (highways that cars drive on)

CREATE OR REPLACE TABLE `{{PROJECT}}.{{DATASET}}.osm_chicago` AS
WITH f AS (
  SELECT
    feature_type, geometry,
    (SELECT t.value FROM UNNEST(all_tags) AS t WHERE t.key = 'building')  AS building,
    (SELECT t.value FROM UNNEST(all_tags) AS t WHERE t.key = 'landuse')   AS landuse,
    (SELECT t.value FROM UNNEST(all_tags) AS t WHERE t.key = 'leisure')   AS leisure,
    (SELECT t.value FROM UNNEST(all_tags) AS t WHERE t.key = 'natural')   AS nat,
    (SELECT t.value FROM UNNEST(all_tags) AS t WHERE t.key = 'amenity')   AS amenity,
    (SELECT t.value FROM UNNEST(all_tags) AS t WHERE t.key = 'highway')   AS highway
  FROM `bigquery-public-data.geo_openstreetmap.planet_features`
  WHERE ST_INTERSECTS(geometry, ST_GEOGFROMTEXT('{{OSM_BBOX_WKT}}'))
)
SELECT kind, centroid, size_m
FROM (
SELECT
  CASE
    WHEN building IS NOT NULL AND feature_type IN ('multipolygons', 'polygons') THEN 'building'
    WHEN feature_type = 'lines' AND highway IN ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified',
                                                 'residential', 'service', 'motorway_link', 'trunk_link', 'primary_link',
                                                 'secondary_link', 'tertiary_link', 'living_street') THEN 'road'
    WHEN feature_type IN ('multipolygons', 'polygons') AND (
           leisure IN ('park', 'garden', 'playground', 'pitch', 'golf_course', 'recreation_ground', 'nature_reserve', 'common')
        OR landuse IN ('grass', 'forest', 'meadow', 'recreation_ground', 'cemetery', 'village_green', 'orchard', 'greenfield')
        OR nat IN ('wood', 'scrub', 'grassland', 'heath', 'wetland')) THEN 'green'
    WHEN feature_type IN ('multipolygons', 'polygons') AND (
           landuse IN ('industrial', 'commercial', 'retail', 'railway', 'garages', 'construction', 'brownfield')
        OR amenity = 'parking') THEN 'paved_use'
  END AS kind,
  ST_CENTROID(geometry) AS centroid,
  IF(feature_type = 'lines', ST_LENGTH(geometry), ST_AREA(geometry)) AS size_m   -- metres for roads, m2 for areas
FROM f
WHERE building IS NOT NULL OR highway IS NOT NULL OR leisure IS NOT NULL OR landuse IS NOT NULL
   OR nat IS NOT NULL OR amenity = 'parking'
)
WHERE kind IS NOT NULL;
