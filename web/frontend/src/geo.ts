import type { TractFeature } from './types';

type Ring = number[][];
const area = (r: Ring) => { let a = 0; for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] - r[i][0]) * (r[j][1] + r[i][1]); return a / 2; };
// area < 0 means clockwise in (lon, lat) with lat up.
const orient = (r: Ring, clockwise: boolean) => ((area(r) < 0) === clockwise ? r : [...r].reverse());
const polygon = (rings: Ring[]) => rings.map((r, i) => orient(r, i === 0));

/** Polygons only, wound for d3: exterior clockwise, holes counter-clockwise. Lines/points are dropped. */
function polygons(g: GeoJSON.Geometry): Ring[][] {
  switch (g.type) {
    case 'Polygon': return [polygon(g.coordinates as Ring[])];
    case 'MultiPolygon': return (g.coordinates as Ring[][]).map(polygon);
    case 'GeometryCollection': return g.geometries.flatMap(polygons);
    default: return [];
  }
}

/** BigQuery's ST_ASGEOJSON follows RFC 7946 (exterior rings counter-clockwise), and ST_SIMPLIFY can return a
 *  GeometryCollection (polygon + stray line/point). d3-geo is spherical and reads a counter-clockwise exterior as
 *  "the whole globe minus this tract", so normalise every tract to a clockwise (Multi)Polygon. */
export function rewind<F extends TractFeature>(f: F): F {
  const ps = polygons(f.geometry as GeoJSON.Geometry);
  const geometry: GeoJSON.Geometry = ps.length === 1 ? { type: 'Polygon', coordinates: ps[0] } : { type: 'MultiPolygon', coordinates: ps };
  return { ...f, geometry };
}
