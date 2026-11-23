from types import SimpleNamespace

from skitz_effects.ui import unsaved as ui


def pipeline(direction="output", preset=None, levels=None, owner="alsa.dali", replaces=(True, True)):
    return SimpleNamespace(
        preset_replaced=bool(preset) and replaces[0],
        levels_replaced=bool(levels) and replaces[1],
        direction=direction,
        preset=SimpleNamespace(name=preset) if preset else None,
        unsaved=bool(preset),
        levels_unsaved=bool(levels),
        levels_owner=owner,
        state={"device_names": {"alsa.dali": "Dali IO6 Analog Stereo"}},
    )


def test_preset_only():
    heading, body = ui.prompt_text([pipeline(preset="Dali iO6")], False)
    assert heading == "Save Changes Before Switching?"
    assert body == 'The output preset "Dali iO6" has unsaved changes.'


def test_levels_only_names_the_device():
    _heading, body = ui.prompt_text([pipeline(levels=True)], False)
    assert body == 'The surround levels of "Dali IO6 Analog Stereo" have unsaved changes.'


def test_unnamed_device_falls_back_to_its_node_name():
    _heading, body = ui.prompt_text([pipeline(levels=True, owner="alsa.other")], False)
    assert body == 'The surround levels of "alsa.other" have unsaved changes.'


def test_preset_and_levels():
    _heading, body = ui.prompt_text([pipeline(preset="Dali iO6", levels=True)], False)
    assert body == ('The output preset "Dali iO6" has unsaved changes.\n'
                    'The surround levels of "Dali IO6 Analog Stereo" have unsaved changes.')


def test_both_directions():
    output = pipeline(preset="Dali iO6")
    mic = pipeline("input", preset="Podcast")
    _heading, body = ui.prompt_text([output, mic], False)
    assert body == ('The output preset "Dali iO6" has unsaved changes.\n'
                    'The input preset "Podcast" has unsaved changes.')


def test_saved_pipelines_are_left_out():
    _heading, body = ui.prompt_text([pipeline(), pipeline("input", preset="Podcast")], False)
    assert body == 'The input preset "Podcast" has unsaved changes.'


def test_quitting_wording():
    heading, body = ui.prompt_text([pipeline(preset="Dali iO6")], True)
    assert heading == "Save Changes Before Quitting?"
    assert body == 'The output preset "Dali iO6" has unsaved changes.'


def test_unsaved_ones_are_picked_out():
    saved, edited = pipeline(), pipeline("input", preset="Podcast")
    assert ui.unsaved_pipelines([saved, edited]) == [edited]


def test_a_switch_lists_only_what_it_replaces():
    edited = pipeline(preset="Dali iO6", levels=True, replaces=(True, False))
    _heading, body = ui.prompt_text([edited], False)
    assert body == 'The output preset "Dali iO6" has unsaved changes.'
    _heading, body = ui.prompt_text([edited], True)
    assert "surround levels" in body
