import pytest

from soundstage import names

from .conftest import FIXTURES

DALI = "alsa_output.usb-0a12_DALI_IO_100306010587-00.analog-stereo"


@pytest.fixture
def conf_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(names, "CONF_DIR", tmp_path)
    monkeypatch.setattr(names, "OWN", tmp_path / "60-soundstage-devices.conf")
    return tmp_path


def test_parse_relaxed_syntax():
    text = """
    # comment
    context.properties = { log.level = 0 }
    rules = [
      { matches = [ { node.name = "a b" } ] actions: { update-props = { x = 1, y = true z = 2.5 } } }
      { list = [ 1 2, "three" ] }   # trailing comment
    ]
    """
    data = names.parse(text)
    assert data["context.properties"] == {"log.level": 0}
    first, second = data["rules"]
    assert first["matches"] == [{"node.name": "a b"}]
    assert first["actions"]["update-props"] == {"x": 1, "y": True, "z": 2.5}
    assert second["list"] == [1, 2, "three"]


def test_parse_escaped_quotes_and_hashes_in_strings():
    data = names.parse('a = "say \\"hi\\" # not a comment"')
    assert data["a"] == 'say "hi" # not a comment'


def test_read_the_real_rename_file():
    rules = names.read(FIXTURES / "52-SWG-rename-devices.conf")
    assert rules[("card", "alsa_card.usb-0a12_DALI_IO_100306010587-00")]["device.description"] == "Dali IO6"
    assert rules[("card", "bluez_card.D0_C8_57_18_25_1D")]["device.nick"] == "DALI IO-6 Wireless"
    assert len(rules) == 6


def test_read_refuses_files_with_other_rules(tmp_path):
    other = tmp_path / "other.conf"
    other.write_text('monitor.alsa.rules = [ { matches = [ { node.name = "~alsa_output.*" } ] '
                     'actions = { update-props = { node.description = "x" } } } ]')
    assert names.read(other) is None
    other.write_text("context.properties = { default.clock.rate = 96000 }")
    assert names.read(other) is None


def test_update_takes_over_old_files_and_round_trips(conf_dir):
    (conf_dir / "52-SWG-rename-devices.conf").write_text((FIXTURES / "52-SWG-rename-devices.conf").read_text())
    names.update(DALI, {names.AWAKE: 0, names.RATE: 96000})
    names.rename(DALI, "Dali Headphones")
    assert (conf_dir / "52-SWG-rename-devices.conf.disabled").exists()
    assert not (conf_dir / "52-SWG-rename-devices.conf").exists()
    assert names.node_props(DALI) == {names.AWAKE: 0, names.RATE: 96000,
                                      "node.description": "Dali Headphones", "node.nick": "Dali Headphones"}
    assert names.custom()[("node", DALI)] == "Dali Headphones"
    assert names.custom()[("card", "alsa_card.pci-0000_01_00.1")] == "Built In Audio"
    names.rename(DALI, "")
    names.update(DALI, {names.AWAKE: None, names.RATE: None})
    assert ("node", DALI) not in names.rules()
    assert len(names.rules()) == 6


def test_bluetooth_rules_go_to_the_bluez_monitor(conf_dir):
    names.rename("bluez_output.D0_C8_57_18_25_1D.1", "Wireless")
    names.rename("v4l2_input.camera", "Ignored")
    data = names.parse(names.OWN.read_text())
    assert list(data) == ["monitor.bluez.rules"]
