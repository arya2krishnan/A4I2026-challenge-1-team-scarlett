import type { TractFeature } from './types';

type Ring = number[][];
const area = (r: Ring) => { let a = 0; for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] - r[i][0]) * (r[j][1] + r[i][1]); return a / 2; };
// area < 0 means clockwise in (lon, lat) with lat up.
const orient = (r: Ring, clockwise: boolean) => ((area(r) < 0) === clockwise ? r : [...r].reverse());
const polygon = (rings: Ring[]) => rings.map((r, i) => orient(r, i === 0));

/** BigQuery's ST_ASGEOJSON follows RFC 7946 (exterior rings counter-clockwise). d3-geo is spherical and reads a
 *  counter-clockwise exterior as "the whole globe minus this tract", so rewind: exterior clockwise, holes CCW. */
export function rewind<F extends TractFeature>(f: F): F {
  const g = f.geometry as GeoJSON.Geometry;
  if (g.type === 'Polygon') return { ...f, geometry: { ...g, coordinates: polygon(g.coordinates as Ring[]) } };
  if (g.type === 'MultiPolygon') return { ...f, geometry: { ...g, coordinates: (g.coordinates as Ring[][]).map(polygon) } };
  return f;
}
