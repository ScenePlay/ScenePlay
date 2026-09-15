"""The music capture graph must survive a restart UNTOUCHED.

A vdo.ninja push tab on this machine captures the remapped source
(ScenePlay-Music). If that source is unloaded — even for the milliseconds it
takes to recreate it — PipeWire's session manager moves the browser's
capture stream onto the default input, i.e. the DM's real microphone, and
leaves it there when the source comes back. The tab still labels the track
"ScenePlay-Music", so nothing looks wrong: the music feed simply carries the
mic from then on. Measured on the appliance with a throwaway sink.

So a healthy graph left by a previous run is ADOPTED, not swept and rebuilt.
Only an incomplete one (a crash mid-build) is torn down and recreated.
"""
import subprocess

import pytest

import integrations.relay_audio_stream as ras


def _cp(stdout='', rc=0):
    return subprocess.CompletedProcess(args=(), returncode=rc, stdout=stdout, stderr='')


def _module_lines(*kinds):
    """`pactl list modules short` for a graph with the given parts present."""
    lines = {
        'sink':   f'536870918\tmodule-null-sink\tsink_name={ras.SINK_NAME} '
                  'sink_properties=device.description=ScenePlay-Stream\t',
        'loop':   f'536870917\tmodule-loopback\tsource={ras.SINK_NAME}.monitor '
                  f'sink=@DEFAULT_SINK@ sink_input_properties=media.name={ras._LOOPBACK_TAG}\t',
        'remap':  f'536870916\tmodule-remap-source\tmaster={ras.SINK_NAME}.monitor '
                  f'source_name={ras.SOURCE_NAME} '
                  f'source_properties=device.description={ras.SOURCE_LABEL}\t',
    }
    other = '536870912\tmodule-native-protocol-tcp\t\t'
    return '\n'.join([other] + [lines[k] for k in kinds]) + '\n'


@pytest.fixture()
def graph(monkeypatch):
    """A Linux box with pactl, a fresh process (no graph known yet), and a
    recorder in place of every pactl call."""
    calls = []
    state = {'modules': ''}
    counter = iter(range(900, 999))

    def run_cmd(*args):
        calls.append(args)
        if args[:3] == ('pactl', 'list', 'modules'):
            return _cp(state['modules'])
        if args[:2] == ('pactl', 'load-module'):
            return _cp(str(next(counter)) + '\n')
        return _cp()

    monkeypatch.setattr(ras, '_IS_WIN', False)
    monkeypatch.setattr(ras, '_run_cmd', run_cmd)
    monkeypatch.setattr(ras.shutil if hasattr(ras, 'shutil') else __import__('shutil'),
                        'which', lambda name: '/usr/bin/pactl' if name == 'pactl' else None)
    monkeypatch.setattr(ras, '_graph_ready', False)
    monkeypatch.setattr(ras, '_graph_failed', False)
    monkeypatch.setattr(ras, '_graph_modules', [])
    stamps = []
    monkeypatch.setattr(ras, '_stamp_sink_epoch', lambda: stamps.append(1))
    state['calls'] = calls
    state['stamps'] = stamps
    return state


def _loads(calls):
    return [c for c in calls if c[:2] == ('pactl', 'load-module')]


def _unloads(calls):
    return [c for c in calls if c[:2] == ('pactl', 'unload-module')]


class TestAdoptExistingGraph:
    def test_a_complete_graph_is_left_alone(self, graph):
        graph['modules'] = _module_lines('sink', 'loop', 'remap')
        assert ras._ensure_graph() is True
        assert _unloads(graph['calls']) == [], 'unloading the source moves the browser onto the mic'
        assert _loads(graph['calls']) == []
        assert ras._graph_ready is True
        assert ras.sink_name() == ras.SINK_NAME

    def test_adopted_modules_are_still_ours_to_tear_down(self, graph):
        graph['modules'] = _module_lines('sink', 'loop', 'remap')
        ras._ensure_graph()
        assert sorted(ras._graph_modules) == ['536870916', '536870917', '536870918']

    def test_adopting_does_not_announce_a_new_sink(self, graph):
        """The epoch stamp makes OBS drop and re-bind its capture source —
        wanted only when the sink instance actually changed."""
        graph['modules'] = _module_lines('sink', 'loop', 'remap')
        ras._ensure_graph()
        assert graph['stamps'] == []

    def test_adopted_sink_is_still_pinned_to_unity_gain(self, graph):
        graph['modules'] = _module_lines('sink', 'loop', 'remap')
        ras._ensure_graph()
        assert ('pactl', 'set-sink-volume', ras.SINK_NAME, '100%') in graph['calls']
        assert ('pactl', 'set-sink-mute', ras.SINK_NAME, '0') in graph['calls']


class TestRebuildBrokenGraph:
    @pytest.mark.parametrize('present', [('sink',), ('sink', 'loop'), ('loop', 'remap')])
    def test_a_partial_graph_is_swept_and_rebuilt(self, graph, present):
        graph['modules'] = _module_lines(*present)
        assert ras._ensure_graph() is True
        assert len(_unloads(graph['calls'])) == len(present)
        assert [c[2] for c in _loads(graph['calls'])] == [
            'module-null-sink', 'module-loopback', 'module-remap-source']
        assert graph['stamps'] == [1]

    def test_no_graph_is_built_from_scratch(self, graph):
        graph['modules'] = _module_lines()
        assert ras._ensure_graph() is True
        assert _unloads(graph['calls']) == []
        assert len(_loads(graph['calls'])) == 3
        assert graph['stamps'] == [1]
        assert ras._graph_modules == ['900', '901', '902']
