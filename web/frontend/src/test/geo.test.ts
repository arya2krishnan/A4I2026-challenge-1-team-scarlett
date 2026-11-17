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
});
