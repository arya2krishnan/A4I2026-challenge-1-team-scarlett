import { geoArea } from 'd3-geo';
import { describe, expect, it } from 'vitest';
import { rewind } from '../geo';
import type { TractFeature } from '../types';

const square = (ccw: boolean): TractFeature => {
  const r = [[-87.65, 41.8], [-87.64, 41.8], [-87.64, 41.81], [-87.65, 41.81], [-87.65, 41.8]];
  return { type: 'Feature', properties: {} as never, geometry: { type: 'Polygon', coordinates: [ccw ? r : [...r].reverse()] } };
};

describe('rewind', () => {
  it('turns an RFC 7946 (counter-clockwise) tract into a small d3 polygon, not the whole globe', () => {
    const before = geoArea(square(true) as never), after = geoArea(rewind(square(true)) as never);
    expect(before).toBeGreaterThan(12);          // ~4π steradians: d3 reads it inside-out
    expect(after).toBeLessThan(1e-6);
    expect(geoArea(rewind(square(false)) as never)).toBeCloseTo(after, 12);   // already-clockwise stays put
  });

  it('unwraps a GeometryCollection (ST_SIMPLIFY output) into clockwise polygons and drops stray lines', () => {
    const sq = square(true).geometry as GeoJSON.Polygon;
    const f = { ...square(true), geometry: { type: 'GeometryCollection', geometries: [sq, { type: 'LineString', coordinates: [[-87.6, 41.8], [-87.5, 41.9]] }] } } as unknown as TractFeature;
    const out = rewind(f);
    expect(out.geometry.type).toBe('Polygon');
    expect(geoArea(out as never)).toBeLessThan(1e-6);
  });
});
