from types import SimpleNamespace

from skitz_effects.controller import Pipeline
from skitz_effects.pipewire import PipeWire

META = 353


def model():
    pw = PipeWire.__new__(PipeWire)
    PipeWire.__bases__[0].__init__(pw)
    pw.objects, pw.metadata, pw._pending, pw._reloading = {}, {}, {}, set()
    pw.reloaded = []
    pw._reload_metadata = pw.reloaded.append
    pw._apply([{"id": META, "type": "PipeWire:Interface:Metadata", "props": {"metadata.name": "default"},
                "metadata": [{"subject": 0, "key": "default.audio.sink", "value": {"name": "dac"}}]}])
    return pw


def stream(oid, name):
    return {"id": oid, "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": "Stream/Output/Audio", "node.name": name, "application.name": name}}}


def target(oid, value):
    return {"id": META, "metadata": [{"subject": oid, "key": "target.object", "type": "Spa:String", "value": value}]}


def test_an_empty_metadata_update_rereads_the_object():
    pw = model()
    pw._apply([stream(215, "Gears"), target(215, "skitz_sink")])
    assert pw.stream_target(215) == "skitz_sink"
    pw._apply([{"id": META, "metadata": []}])
    assert pw.reloaded == [META]


def test_a_closed_stream_leaves_nothing_for_the_next_one_with_its_id():
    pw = model()
    pw._apply([stream(347, "Cider"), target(347, "skitz_sink")])
    pw._apply([{"id": 347, "info": None}])
    pw._apply([stream(347, "Gears")])
    assert pw.stream_target(347) == ""


def route(streams, targets, blocked=(), running=True):
    moves = []
    pw = SimpleNamespace(streams=lambda _cls: streams.items(), stream_target=lambda oid: targets.get(oid, ""),
                         move=lambda oid, to: moves.append((oid, to)))
    pipeline = SimpleNamespace(pw=pw, stream_class="Stream/Output/Audio", virtual="skitz_sink",
                               chain_running=running, blocked=lambda props: props["application.name"] in blocked,
                               _target=lambda oid: "skitz_sink")
    Pipeline._route_streams(pipeline)
    return moves


def test_every_stream_goes_through_skitz_effects_even_with_a_restored_target():
    streams = {1: {"application.name": "mpv", "node.name": "mpv"},
               2: {"application.name": "Whatsie", "node.name": "Whatsie"},
               3: {"application.name": "Gears", "node.name": "Gears"}}
    moves = route(streams, {1: "easyeffects_sink", 3: "skitz_sink"})
    assert moves == [(1, "skitz_sink"), (2, "skitz_sink")]


def test_streams_left_out_in_the_mixer_return_to_the_device():
    streams = {1: {"application.name": "Discord", "node.name": "Discord"},
               2: {"application.name": "Chat", "node.name": "Chat"}}
    assert route(streams, {1: "skitz_sink", 2: "headset"}, blocked=("Discord", "Chat")) == [(1, "")]


def test_streams_wait_on_the_device_while_the_chain_is_down():
    streams = {1: {"application.name": "mpv", "node.name": "mpv"}}
    assert route(streams, {1: "skitz_sink"}, running=False) == [(1, "")]


def test_streams_take_the_stereo_path_once_they_turn_out_stereo():
    channels = {1: 2, 2: 8, 3: 0, 4: 1}
    pw = SimpleNamespace(stream_channels=lambda oid: channels[oid], node_id=lambda name: 7)
    pipeline = SimpleNamespace(pw=pw, virtual="skitz_sink", has_stereo_sink=lambda: True)
    targets = {oid: Pipeline._target(pipeline, oid) for oid in channels}
    assert targets == {1: "skitz_stereo", 2: "skitz_sink", 3: "skitz_sink", 4: "skitz_stereo"}
    pipeline.has_stereo_sink = lambda: False
    assert Pipeline._target(pipeline, 1) == "skitz_sink"
