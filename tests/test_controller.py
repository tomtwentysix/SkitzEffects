from skitz_effects.controller import input_variants, routable

UMC22 = [
    (0, "off"),
    (1, "output:analog-stereo-output+input:analog-stereo-input"),
    (2, "output:analog-stereo-output+input:analog-mono-left"),
    (3, "output:analog-stereo-output+input:analog-mono-right"),
    (4, "output:analog-stereo-output+input:analog-mono"),
    (5, "output:analog-stereo-output"),
    (6, "input:analog-stereo-input"),
    (7, "input:analog-mono-left"),
    (8, "input:analog-mono-right"),
    (9, "input:analog-mono"),
    (10, "pro-audio"),
]


def test_input_variants_keep_the_output_side():
    current = "output:analog-stereo-output+input:analog-mono"
    assert input_variants(UMC22, current) == [
        (1, "analog-stereo-input"), (2, "analog-mono-left"), (3, "analog-mono-right"), (4, "analog-mono")]
    assert [i for i, _p in input_variants(UMC22, "input:analog-mono")] == [6, 7, 8, 9]
    assert input_variants(UMC22, "pro-audio") == []


def test_routable_streams():
    assert routable({"node.name": "Firefox"})
    assert not routable({"node.name": "skitz_tap_output_after"})
    assert not routable({"node.name": "output.pw-loopback-1", "node.link-group": "loopback-1-20"})
    assert not routable({"node.name": "obs", "stream.capture.sink": "true"})
    assert not routable({"node.name": "peak", "stream.monitor": True})
    assert not routable({"node.name": "pw-play", "target.object": "alsa_output.x"})


def test_app_key_matches_easy_effects_blocklist_names():
    from skitz_effects.controller import app_key
    assert app_key({"application.id": "org.gnome.Rhythmbox3", "application.name": "Rhythmbox"}) == "org.gnome.Rhythmbox3"
    assert app_key({"application.name": "Firefox", "node.name": "Firefox"}) == "Firefox"
    assert app_key({"node.name": "mpv"}) == "mpv"


def test_streams_aimed_at_easy_effects_come_through_skitz_effects():
    loopback = {"node.name": "output.pw-loopback-1", "node.link-group": "loopback-1-20",
                "node.target": "easyeffects_sink"}
    assert routable(loopback)
    assert routable({"node.name": "obs-mic", "target.object": "easyeffects_source"})
    assert not routable({"node.name": "skitz_output", "target.object": "easyeffects_sink"})
