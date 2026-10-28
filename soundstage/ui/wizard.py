from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .. import config, deps, presets
from .surround import LAYOUTS, hrir_choices


def autostart_command():
    if config.DEVEL:
        return str(Path(__file__).resolve().parents[2] / "run-dev.sh")
    return "soundstage"


class SetupWizard(Adw.Dialog):
    def __init__(self, application, first_run):
        super().__init__(title="Set Up Soundstage", content_width=560, content_height=640,
                         can_close=not first_run)
        self.app = application
        self.settings = application.settings
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self.nav.add(self._page("welcome", "Welcome", self._welcome(), "Get Started", "components"))

    def _page(self, tag, title, content, next_label, next_tag, on_next=None):
        button = Gtk.Button(label=next_label, css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER,
                            margin_top=12, margin_bottom=18)

        def go(_b):
            if on_next:
                on_next()
            if next_tag:
                self.nav.push(self._build(next_tag))

        button.connect("clicked", go)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(Adw.HeaderBar())
        view.add_bottom_bar(button)
        return Adw.NavigationPage(title=title, tag=tag, child=view)

    def _build(self, tag):
        if tag == "components":
            return self._page("components", "Components", self._components(), "Continue", "easyeffects")
        if tag == "easyeffects":
            return self._page("easyeffects", "Easy Effects", self._easyeffects(), "Continue", "surround")
        if tag == "surround":
            return self._page("surround", "Surround", self._surround(), "Continue", "finish")
        return self._page("finish", "Finish", self._finish(), "Finish", None, self._on_finish)

    def _welcome(self):
        return Adw.StatusPage(
            icon_name=config.ICON_NAME, title="Welcome to Soundstage",
            description="Soundstage applies your Easy Effects presets to everything you play, "
                        "switches presets when you change device, and plays 5.1 and 7.1 sound on any "
                        "speakers or headphones.")

    def _components(self):
        page = Adw.PreferencesPage()
        self.components_group = Adw.PreferencesGroup(
            title="Required Software",
            description="The effects themselves come from these packages. Installing asks for your password.")
        page.add(self.components_group)
        self._component_rows = []
        self._fill_components()
        return page

    def _fill_components(self):
        for row in self._component_rows:
            self.components_group.remove(row)
        self._component_rows = []
        missing = deps.missing()
        for c in deps.COMPONENTS:
            row = Adw.ActionRow(title=c.title, subtitle=c.description)
            icon = "emblem-ok-symbolic" if c not in missing else "dialog-warning-symbolic"
            row.add_suffix(Gtk.Image(icon_name=icon, css_classes=["success" if c not in missing else "warning"]))
            self._component_rows.append(row)
            self.components_group.add(row)
        if missing:
            command = deps.install_command([c.package for c in missing])
            row = Adw.ActionRow(title="Install missing software",
                                subtitle=" ".join(c.package for c in missing))
            if command:
                button = Gtk.Button(label="Install", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
                button.connect("clicked", self._on_install, command, row)
                row.add_suffix(button)
            else:
                row.set_subtitle("Install these packages with your system's package manager: "
                                 + " ".join(c.package for c in missing))
            self._component_rows.append(row)
            self.components_group.add(row)

    def _on_install(self, button, command, row):
        button.set_sensitive(False)
        row.add_suffix(Adw.Spinner())
        try:
            proc = Gio.Subprocess.new(command, Gio.SubprocessFlags.NONE)
        except GLib.Error as e:
            row.set_subtitle(e.message)
            return
        proc.wait_check_async(None, self._on_installed)

    def _on_installed(self, proc, result):
        try:
            proc.wait_check_finish(result)
        except GLib.Error:
            pass
        self._fill_components()

    def _easyeffects(self):
        page = Adw.PreferencesPage()
        found = Adw.PreferencesGroup(title="Your Presets")
        outputs, inputs = len(presets.list_presets("output")), len(presets.list_presets("input"))
        found.add(Adw.ActionRow(
            title=f"{outputs} output and {inputs} input presets found",
            subtitle="Soundstage edits them in place, so Easy Effects keeps working with them"))
        self.rules = {d: presets.autoload_rules(d) for d in ("output", "input")}
        count = sum(len(r) for r in self.rules.values())
        self.import_rules = Adw.SwitchRow(
            title="Use Easy Effects' device presets",
            subtitle=f"{count} device{'s' if count != 1 else ''} with a preset of their own",
            active=bool(count), sensitive=bool(count))
        found.add(self.import_rules)
        page.add(found)

        group = Adw.PreferencesGroup(
            title="Apps Soundstage Replaces",
            description="Turning these off stops them now and at login. You can turn them back on in "
                        "their own settings.")
        conflicts = deps.active_conflicts()
        for c in conflicts:
            row = Adw.ActionRow(title=c.title, subtitle=c.description)
            button = Gtk.Button(label="Turn Off", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            button.connect("clicked", self._on_turn_off, c, row)
            row.add_suffix(button)
            group.add(row)
        if not conflicts:
            group.add(Adw.ActionRow(title="No other audio effects apps are running"))
        page.add(group)
        return page

    def _on_turn_off(self, button, conflict, row):
        conflict.turn_off()
        button.set_visible(False)
        row.set_subtitle("Turned off")

    def _surround(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Surround Sound",
            description="Apps can send Soundstage up to 7.1 channels. Surround devices get every channel; on "
                        "stereo devices an HRIR places each one around you.")
        self.layout_row = Adw.ComboRow(title="Channels", model=Gtk.StringList.new([t for _k, t in LAYOUTS]))
        self.layout_row.set_selected([k for k, _t in LAYOUTS].index(self.settings.layout))
        group.add(self.layout_row)
        self.hrirs = hrir_choices(self.settings.hrir)
        names = ["None", *self.hrirs]
        self.hrir_row = Adw.ComboRow(title="HRIR", subtitle="14-channel HeSuVi WAV files from your Easy Effects "
                                     "impulse responses", model=Gtk.StringList.new(names))
        paths = list(self.hrirs.values())
        if self.settings.hrir in paths:
            self.hrir_row.set_selected(paths.index(self.settings.hrir) + 1)
        elif paths:
            self.hrir_row.set_selected(1)
        group.add(self.hrir_row)
        page.add(group)
        return page

    def _finish(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Running")
        self.autostart_row = Adw.SwitchRow(title="Start at login", active=True)
        self.background_row = Adw.SwitchRow(
            title="Keep running when the window is closed",
            subtitle="Effects only apply while Soundstage is running", active=self.settings.run_in_background)
        group.add(self.autostart_row)
        group.add(self.background_row)
        page.add(group)
        return page

    def _on_finish(self):
        s = self.settings
        if self.import_rules.get_active():
            for direction, rules in self.rules.items():
                for device, preset in rules.items():
                    getattr(s, direction)["device_presets"].setdefault(device, preset)
        s.layout = LAYOUTS[self.layout_row.get_selected()][0]
        i = self.hrir_row.get_selected()
        s.hrir = list(self.hrirs.values())[i - 1] if i > 0 else ""
        s.run_in_background = self.background_row.get_active()
        s.setup_done = True
        s.save()
        deps.set_autostart(self.autostart_row.get_active(), autostart_command())
        controller = self.app.controller
        for pipeline in controller.pipelines:
            if pipeline.preset is None:
                first = next(iter(presets.list_presets(pipeline.direction)), "")
                if first:
                    pipeline.load_preset(first)
        controller.start()
        self.app.hold_in_background()
        self.force_close()
