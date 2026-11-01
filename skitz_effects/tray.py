"""The tray icon: a StatusNotifierItem with a com.canonical.dbusmenu menu, served on the app's own bus connection.

The item registers with org.kde.StatusNotifierWatcher by object path, so the watcher talks to the
app's unique name and no well-known name has to be owned, which suits the Flatpak sandbox.
"""

from gi.repository import Gio, GLib

from .config import ICON_NAME

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/StatusNotifierItem/Menu"
WATCHER = "org.kde.StatusNotifierWatcher"

INTERFACES = Gio.DBusNodeInfo.new_for_xml("""
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <method name="ProvideXdgActivationToken"><arg type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
    <method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
  </interface>
</node>""")

OPEN, EFFECTS, QUIT = 1, 2, 4


def menu_items(effects_on):
    """Returns {id: properties} for the menu; id 0 is the root and the rest are its children in order."""
    return {
        0: {"children-display": GLib.Variant("s", "submenu")},
        OPEN: {"label": GLib.Variant("s", "Open Skitz Effects")},
        EFFECTS: {"label": GLib.Variant("s", "Effects"), "toggle-type": GLib.Variant("s", "checkmark"),
                  "toggle-state": GLib.Variant("i", int(effects_on))},
        3: {"type": GLib.Variant("s", "separator")},
        QUIT: {"label": GLib.Variant("s", "Quit")},
    }


def menu_layout(effects_on, parent=0, names=()):
    """The (ia{sv}av) layout GetLayout returns below `parent`, keeping only `names` when any are asked for."""
    items = menu_items(effects_on)

    def node(item_id, children):
        props = {k: v for k, v in items[item_id].items() if not names or k in names}
        return GLib.Variant("(ia{sv}av)", (item_id, props, children))

    if parent != 0:
        return node(parent, []) if parent in items else None
    return node(0, [node(i, []) for i in items if i != 0])


def item_properties(icon_name, icon_theme_path):
    return {
        "Category": GLib.Variant("s", "ApplicationStatus"),
        "Id": GLib.Variant("s", ICON_NAME),
        "Title": GLib.Variant("s", "Skitz Effects"),
        "Status": GLib.Variant("s", "Active"),
        "IconName": GLib.Variant("s", icon_name),
        "IconThemePath": GLib.Variant("s", icon_theme_path),
        "ToolTip": GLib.Variant("(sa(iiay)ss)", (icon_name, [], "Skitz Effects", "")),
        "ItemIsMenu": GLib.Variant("b", False),
        "Menu": GLib.Variant("o", MENU_PATH),
    }


MENU_PROPERTIES = {
    "Version": GLib.Variant("u", 3),
    "TextDirection": GLib.Variant("s", "ltr"),
    "Status": GLib.Variant("s", "normal"),
    "IconThemePath": GLib.Variant("as", []),
}


class Tray:
    """Shows the app in the tray whenever a StatusNotifierWatcher is on the bus, until close() is called."""

    def __init__(self, app, icon_theme_path=""):
        self.app = app
        self.bus = app.get_dbus_connection()
        self.revision = 1
        self._token = None
        self.properties = item_properties(f"{ICON_NAME}-symbolic", icon_theme_path)
        item, menu = INTERFACES.interfaces
        self._registrations = [
            self.bus.register_object(ITEM_PATH, item, self._on_item_call, self._on_item_property, None),
            self.bus.register_object(MENU_PATH, menu, self._on_menu_call, self._on_menu_property, None),
        ]
        self._effects = app.lookup_action("effects")
        self._notify = self._effects.connect("notify::state", self._on_effects_changed)
        # Called again each time the watcher appears, which is how a restarted gnome-shell finds the item.
        self._watch = Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                                       self._register, None)

    def close(self):
        Gio.bus_unwatch_name(self._watch)
        self._effects.disconnect(self._notify)
        for registration in self._registrations:
            self.bus.unregister_object(registration)

    def _register(self, bus, name, owner):
        bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                 GLib.Variant("(s)", (ITEM_PATH,)), None, Gio.DBusCallFlags.NONE, -1, None, None)

    def _effects_on(self):
        return self._effects.get_state().get_boolean()

    def _on_effects_changed(self, *_):
        self.revision += 1
        self.bus.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                             GLib.Variant("(ui)", (self.revision, 0)))

    def _on_item_property(self, bus, sender, path, interface, name):
        return self.properties.get(name)

    def _on_menu_property(self, bus, sender, path, interface, name):
        return MENU_PROPERTIES.get(name)

    def _on_item_call(self, bus, sender, path, interface, method, params, invocation):
        # Hosts send a token before Activate and menu clicks; without one, Wayland will not raise the window.
        if method == "ProvideXdgActivationToken":
            (self._token,) = params.unpack()
        elif method in ("Activate", "SecondaryActivate"):
            self._show()
        invocation.return_value(None)

    def _on_menu_call(self, bus, sender, path, interface, method, params, invocation):
        effects_on = self._effects_on()
        items = menu_items(effects_on)
        if method == "GetLayout":
            parent, _depth, names = params.unpack()
            layout = menu_layout(effects_on, parent, names)
            if layout is None:
                invocation.return_dbus_error("com.canonical.dbusmenu.Error.UnknownItem", f"No item {parent}")
                return
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", self.revision), layout))
        elif method == "GetGroupProperties":
            ids, names = params.unpack()
            reply = [(i, {k: v for k, v in items[i].items() if not names or k in names})
                     for i in (ids or items) if i in items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (reply,)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            value = items.get(item_id, {}).get(name)
            if value is None:
                invocation.return_dbus_error("com.canonical.dbusmenu.Error.UnknownProperty", name)
                return
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event, _data, _time = params.unpack()
            if event == "clicked":
                self._clicked(item_id)
            invocation.return_value(None)
        elif method == "EventGroup":
            (events,) = params.unpack()
            for item_id, event, _data, _time in events:
                if event == "clicked":
                    self._clicked(item_id)
            invocation.return_value(GLib.Variant("(ai)", ([e[0] for e in events if e[0] not in items],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            (ids,) = params.unpack()
            invocation.return_value(GLib.Variant("(aiai)", ([], [i for i in ids if i not in items])))

    def _clicked(self, item_id):
        if item_id == OPEN:
            self._show()
        elif item_id == EFFECTS:
            self.app.change_action_state("effects", GLib.Variant("b", not self._effects_on()))
        elif item_id == QUIT:
            self.app.activate_action("quit", None)

    def _show(self):
        if self._token:
            self.app.window().set_startup_id(self._token)
            self._token = None
        self.app.activate_action("show", None)
