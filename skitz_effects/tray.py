"""The tray icon, in a process of its own: the indicator library is GTK 3 and the app is GTK 4.

Run as `python3 -m skitz_effects.tray <application id> [icon]`, where the icon is a themed
name or, from a checkout, the path of an SVG. The menu works the app through the actions it
exports on D-Bus.
"""

import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3 as AppIndicator, Gio, GLib, Gtk  # noqa: E402

from .config import ICON_NAME  # noqa: E402


def main(app_id, icon=f"{ICON_NAME}-symbolic"):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    actions = Gio.DBusActionGroup.get(bus, app_id, "/" + app_id.replace(".", "/"))

    indicator = AppIndicator.Indicator.new(app_id, icon, AppIndicator.IndicatorCategory.APPLICATION_STATUS)
    indicator.set_title("Skitz Effects")

    menu = Gtk.Menu()
    open_item = Gtk.MenuItem(label="Open Skitz Effects")
    open_item.connect("activate", lambda _i: actions.activate_action("show", None))
    effects = Gtk.CheckMenuItem(label="Effects")
    toggled = effects.connect(
        "toggled", lambda item: actions.change_action_state("effects", GLib.Variant("b", item.get_active())))
    quit_item = Gtk.MenuItem(label="Quit")
    quit_item.connect("activate", lambda _i: actions.activate_action("quit", None))
    for item in (open_item, effects, Gtk.SeparatorMenuItem(), quit_item):
        menu.append(item)
    menu.show_all()
    indicator.set_menu(menu)
    indicator.set_secondary_activate_target(open_item)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    def show_state(*_):
        state = actions.get_action_state("effects")
        if state is not None and effects.get_active() != state.get_boolean():
            effects.handler_block(toggled)
            effects.set_active(state.get_boolean())
            effects.handler_unblock(toggled)

    # The action group fills in lazily, so the switch follows it as actions arrive and change.
    actions.connect("action-added", show_state)
    actions.connect("action-state-changed", show_state)
    actions.list_actions()
    Gtk.main()


if __name__ == "__main__":
    main(*sys.argv[1:])
