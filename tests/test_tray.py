from skitz_effects import tray
from skitz_effects.config import ICON_NAME


def test_menu_layout_lists_every_item_under_the_root():
    root_id, root_props, children = tray.menu_layout(True).unpack()
    assert root_id == 0
    assert root_props == {"children-display": "submenu"}
    assert [c[0] for c in children] == [tray.OPEN, tray.EFFECTS, 3, tray.QUIT]
    assert [c[1].get("label") for c in children] == ["Open Skitz Effects", "Effects", None, "Quit"]
    assert children[2][1] == {"type": "separator"}
    assert all(c[2] == [] for c in children)


def test_menu_layout_has_the_dbus_signature_hosts_expect():
    assert tray.menu_layout(False).get_type_string() == "(ia{sv}av)"


def test_effects_item_follows_the_effects_state():
    def effects(on):
        return tray.menu_layout(on).unpack()[2][1][1]

    assert effects(True) == {"label": "Effects", "toggle-type": "checkmark", "toggle-state": 1}
    assert effects(False)["toggle-state"] == 0


def test_menu_layout_keeps_only_the_properties_asked_for():
    children = tray.menu_layout(True, names=["label"]).unpack()[2]
    assert [c[1] for c in children] == [{"label": "Open Skitz Effects"}, {"label": "Effects"}, {}, {"label": "Quit"}]


def test_menu_layout_below_one_item():
    assert tray.menu_layout(True, parent=tray.QUIT).unpack() == (tray.QUIT, {"label": "Quit"}, [])
    assert tray.menu_layout(True, parent=99) is None


def test_item_properties_match_the_interface():
    props = tray.item_properties(f"{ICON_NAME}-symbolic", "/checkout/data/icons")
    item = tray.INTERFACES.lookup_interface("org.kde.StatusNotifierItem")
    assert set(props) == {p.name for p in item.properties}
    for p in item.properties:
        assert props[p.name].get_type_string() == p.signature
    assert props["IconName"].unpack() == f"{ICON_NAME}-symbolic"
    assert props["IconThemePath"].unpack() == "/checkout/data/icons"
    assert props["Menu"].unpack() == tray.MENU_PATH
    assert props["ItemIsMenu"].unpack() is False


def test_menu_properties_match_the_interface():
    menu = tray.INTERFACES.lookup_interface("com.canonical.dbusmenu")
    assert {p.name: p.signature for p in menu.properties} == {
        name: value.get_type_string() for name, value in tray.MENU_PROPERTIES.items()}
