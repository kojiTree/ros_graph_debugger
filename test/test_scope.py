"""Profile scope parsing and node allowlist matching."""

import pytest

from ros_graph_debugger.profile import load_profile
from ros_graph_debugger.scope import ScopeConfig, filter_snapshot


def test_profile_parses_node_allowlist(tmp_path):
    profile = tmp_path / 'scoped.yaml'
    profile.write_text(
        'name: scoped\n'
        'scope:\n'
        '  node_allowlist:\n'
        "    - '^/camera/.*'\n"
        "    - '^/planner$'\n")

    data, name = load_profile(str(profile))

    assert name == 'scoped'
    assert isinstance(data['_scope'], ScopeConfig)
    assert data['_scope'].node_allowlist == ['^/camera/.*', '^/planner$']
    assert data['_scope'].active


@pytest.mark.parametrize('contents', [
    'name: missing\n',
    'name: empty\nscope: {}\n',
    "name: invalid\nscope:\n  node_allowlist: ['[']\n",
    'name: list\nscope: []\n',
    'name: scalar\nscope: not-a-mapping\n',
    'name: null-allowlist\nscope:\n  node_allowlist:\n',
    "name: scalar-allowlist\nscope:\n  node_allowlist: '^/node$'\n",
])
def test_missing_empty_or_invalid_scope_is_inactive(tmp_path, contents):
    profile = tmp_path / 'profile.yaml'
    profile.write_text(contents)

    data, _ = load_profile(str(profile))
    scope = data['_scope']

    assert not scope.active
    assert scope.matches_node('/any/fully_qualified_node')


def test_scope_matches_fully_qualified_node_ids_and_skips_invalid_patterns():
    scope = ScopeConfig(node_allowlist=[
        '[', b'^/camera', '^/camera/.*', '^/planner$'])

    assert scope.active
    assert scope.matches_node('/camera/front')
    assert scope.matches_node('/planner')
    assert not scope.matches_node('/camera_driver')
    assert not scope.matches_node('/planner/helper')


def test_set_node_allowlist_rebuilds_compiled_patterns():
    scope = ScopeConfig(node_allowlist=['^/before$'])

    scope.set_node_allowlist(['^/after$'])

    assert not scope.matches_node('/before')
    assert scope.matches_node('/after')


def _snapshot():
    return {
        'timestamp': 123.0,
        'profile': 'test',
        'nodes': [
            {'id': '/camera', 'publishers': ['/image'], 'subscribers': []},
            {'id': '/detector', 'publishers': ['/objects'],
             'subscribers': ['/image']},
            {'id': '/viewer', 'publishers': [], 'subscribers': ['/objects']},
        ],
        'topics': [
            {'name': '/image', 'publishers': ['/camera'],
             'subscribers': ['/detector'], 'publisher_count': 1,
             'subscriber_count': 1,
             'qos_endpoints': [{'node': '/camera'}, {'node': '/detector'}]},
            {'name': '/objects', 'publishers': ['/detector'],
             'subscribers': ['/viewer'], 'publisher_count': 1,
             'subscriber_count': 1,
             'qos_endpoints': [{'node': '/detector'}, {'node': '/viewer'}]},
            {'name': '/unrelated', 'publishers': ['/viewer'],
             'subscribers': [], 'publisher_count': 1,
             'subscriber_count': 0},
        ],
        'edges': [
            {'from_node': '/camera', 'to_node': '/detector',
             'topic': '/image'},
            {'from_node': '/detector', 'to_node': '/viewer',
             'topic': '/objects'},
        ],
        'tf_edges': [{'parent': 'map', 'child': 'base_link'}],
        'diagnostics': [{'name': 'camera temperature', 'level': 0}],
        'callbacks': [
            {'node': '/detector', 'callback': 'image', 'topic': '/image'},
            {'node': '/detector', 'callback': 'timer', 'topic': ''},
            {'node': '/viewer', 'callback': 'objects', 'topic': '/objects'},
        ],
        'issues': [
            {'id': 'mixed', 'related_nodes': ['/detector', '/viewer'],
             'related_topics': ['/objects', '/unrelated']},
            {'id': 'viewer', 'related_nodes': ['/viewer'],
             'related_topics': []},
            {'id': 'tf', 'related_nodes': [], 'related_topics': [],
             'related_frames': ['map']},
        ],
        'extension': {'preserved': True},
    }


def test_filter_snapshot_derives_topics_edges_and_related_categories():
    snapshot = _snapshot()
    original = _snapshot()
    narrowed = filter_snapshot(
        snapshot, ScopeConfig(node_allowlist=['^/(camera|detector)$']))

    assert [node['id'] for node in narrowed['nodes']] == ['/camera', '/detector']
    assert [topic['name'] for topic in narrowed['topics']] == ['/image', '/objects']
    assert narrowed['edges'] == [{
        'from_node': '/camera', 'to_node': '/detector', 'topic': '/image'}]
    assert [callback['callback'] for callback in narrowed['callbacks']] == [
        'image', 'timer']
    assert [issue['id'] for issue in narrowed['issues']] == ['mixed', 'tf']
    assert narrowed['issues'][0]['related_nodes'] == ['/detector']
    assert narrowed['issues'][0]['related_topics'] == ['/objects']
    assert narrowed['tf_edges'] == [{'parent': 'map', 'child': 'base_link'}]
    assert narrowed['diagnostics'] == [
        {'name': 'camera temperature', 'level': 0}]
    assert narrowed['extension'] == {'preserved': True}
    assert snapshot == original


def test_filter_snapshot_has_no_dangling_references_and_consistent_counts():
    narrowed = filter_snapshot(
        _snapshot(), ScopeConfig(node_allowlist=['^/detector$']))

    node_ids = {node['id'] for node in narrowed['nodes']}
    topic_names = {topic['name'] for topic in narrowed['topics']}
    for topic in narrowed['topics']:
        assert set(topic['publishers']) <= node_ids
        assert set(topic['subscribers']) <= node_ids
        assert topic['publisher_count'] == len(topic['publishers'])
        assert topic['subscriber_count'] == len(topic['subscribers'])
        assert {endpoint['node'] for endpoint in topic['qos_endpoints']} <= node_ids
    for edge in narrowed['edges']:
        assert {edge['from_node'], edge['to_node']} <= node_ids
        assert edge['topic'] in topic_names
    for node in narrowed['nodes']:
        assert set(node['publishers']) <= topic_names
        assert set(node['subscribers']) <= topic_names


def test_filter_snapshot_returns_snapshot_unchanged_when_scope_is_inactive():
    snapshot = _snapshot()

    narrowed = filter_snapshot(snapshot, ScopeConfig())

    assert narrowed is snapshot
