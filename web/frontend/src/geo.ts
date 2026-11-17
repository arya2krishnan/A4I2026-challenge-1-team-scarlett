import { geoArea } from 'd3-geo';
import type { TractFeature } from './types';

type Ring = number[][];

function fixGeometry(g: GeoJSON.Geometry | null): GeoJSON.Geometry | null {
  if (!g) return null;
  if (g.type === 'GeometryCollection') {
    const polys = (g.geometries || []).filter(sub => sub.type === 'Polygon' || sub.type === 'MultiPolygon') as (GeoJSON.Polygon | GeoJSON.MultiPolygon)[];
    if (polys.length === 1) return fixGeometry(polys[0]);
    if (polys.length > 1) {
      const all: Ring[][] = [];
      for (const p of polys) {
        if (p.type === 'Polygon') all.push(p.coordinates as Ring[]);
        else if (p.type === 'MultiPolygon') all.push(...(p.coordinates as Ring[][]));
      }
      return fixGeometry({ type: 'MultiPolygon', coordinates: all });
    }
    return polys[0] || null;
  }
  if (g.type === 'Polygon') {
    let coords = g.coordinates as Ring[];
    if (geoArea({ type: 'Polygon', coordinates: coords }) > 2 * Math.PI) {
      coords = coords.map(r => [...r].reverse());
    }
    return { type: 'Polygon', coordinates: coords };
  }
  if (g.type === 'MultiPolygon') {
    const coords = (g.coordinates as Ring[][]).map(poly => {
      if (geoArea({ type: 'Polygon', coordinates: poly }) > 2 * Math.PI) {
        return poly.map(r => [...r].reverse());
      }
      return poly;
    });
    return { type: 'MultiPolygon', coordinates: coords };
  }
  return g;
}

/** BigQuery's ST_ASGEOJSON follows RFC 7946 (exterior rings counter-clockwise). d3-geo is spherical and reads a
 *  counter-clockwise exterior as "the whole globe minus this tract", so rewind to valid spherical bounds and
 *  flatten any GeometryCollections into standard Polygons. */
export function rewind<F extends TractFeature>(f: F): F {
  const fixed = fixGeometry(f.geometry as GeoJSON.Geometry);
  return fixed ? { ...f, geometry: fixed } : f;
}

