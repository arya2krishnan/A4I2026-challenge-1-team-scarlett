"""Check network restrictions and disconnected routes, without live OSM calls."""
import pytest

from load_chicago_walkability import cooling_walks, normalize_network, shortest_paths


def test_vehicle_oneway_does_not_restrict_pedestrians_but_foot_oneway_does():
    payload = b'''<osm><node id="1" lat="41.878" lon="-87.630"/>
      <node id="2" lat="41.879" lon="-87.630"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/>
      <tag k="oneway" v="yes"/></way></osm>'''
    nodes, edges = normalize_network(payload)
    assert len(nodes) == 2
    assert 1 in shortest_paths(edges, 2)
    _, restricted = normalize_network(payload.replace(b'k="oneway"', b'k="oneway:foot"'))
    assert 1 not in shortest_paths(restricted, 2)


def test_motorway_and_private_ways_excluded_unless_foot_permission_overrides_access():
    payload = b'''<osm><node id="1" lat="41.878" lon="-87.630"/>
      <node id="2" lat="41.879" lon="-87.630"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="motorway"/></way>
      <way id="11"><nd ref="1"/><nd ref="2"/><tag k="highway" v="service"/><tag k="access" v="private"/></way>
      <way id="12"><nd ref="1"/><nd ref="2"/><tag k="highway" v="service"/>
      <tag k="access" v="private"/><tag k="foot" v="yes"/></way></osm>'''
    _, edges = normalize_network(payload)
    assert [edge["way_id"] for edge in edges] == [12]


def test_restricted_gate_breaks_connectivity():
    payload = b'''<osm><node id="1" lat="41.878" lon="-87.630"/>
      <node id="2" lat="41.879" lon="-87.630"><tag k="foot" v="no"/></node>
      <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way></osm>'''
    assert normalize_network(payload) == ([], [])


def test_disconnected_cooling_site_returns_unknown_walk_and_unknown_opening():
    nodes = [{"node_id": 1, "latitude": 41.878, "longitude": -87.630},
             {"node_id": 2, "latitude": 41.879, "longitude": -87.630}]
    facility = {"site_name": "Library", "latitude": 41.879, "longitude": -87.630, "is_indoor": True}
    rows = cooling_walks(nodes, [], [facility], (41.878, -87.630), (-87.64, 41.87, -87.62, 41.89))
    assert rows[0]["estimated_walk_minutes"] is None
    assert rows[0]["status"] == "disconnected_in_pilot_extract"
    assert rows[0]["open_for_event"] is None
    with pytest.raises(ValueError):
        cooling_walks(nodes, [], [facility], (41.878, -87.630), (-87.64, 41.87, -87.62, 41.89), speed=0)
