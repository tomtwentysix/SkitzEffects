from math import log10

from gi.repository import Adw, Gtk

from .. import check, monitor

CUT_LABELS = {"output-gain": "Output gain", "surround": "Surround levels", "ceiling": "Ceiling", "volume": "Volume"}
LIVE_INTERVAL = 0.25


def _db(value):
    return f"{abs(value) if round(value, 1) == 0 else value:.1f} dB"


def overs_text(reading):
    if not reading.overs:
        return "No overs"
    times = "time" if reading.overs == 1 else "times"
    return f"Over by up to {_db(20 * log10(reading.peak))}, {reading.overs} {times}"


def change_text(stage, change, layout):
    if change is None:
        return None
    if check.drop_flagged(stage, change, layout):
        return f"Drops {_db(-change)}"
    if stage.kind == "surround":
        return f"{_db(change)}, headroom, expected"
    return f"{change:+.1f} dB"


def cut_text(cut):
    if cut.control == "target":
        return f"Target lowered by {-cut.db:.1f} LU, applied gradually"
    return f"{CUT_LABELS[cut.control]} lowered by {_db(-cut.db)}"


def input_text(before):
    return "Apps are sending audio over 0 dB" if before.overs else None


def leftover_text(db):
    return f"Could not lower the preset by a further {_db(db)}" if db >= 0.05 else None


def nothing_measured(before, readings):
    return all(r.frames == 0 and r.overs == 0 for r in (before, *readings.values()))


def elapsed_text(seconds):
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class CheckDialog(Adw.Dialog):
    def __init__(self, pipeline):
        super().__init__(title="Distortion Check", content_width=520, content_height=560)
        self.pipeline = pipeline
        self.check = None
        self.cuts = []
        self.rows = {}
        self._relabelled = 0.0
        self._watch = []

        self.heading = Adw.WindowTitle(title="Distortion Check", subtitle=pipeline.preset.name)
        self.header = Adw.HeaderBar(title_widget=self.heading, show_start_title_buttons=False,
                                    show_end_title_buttons=False)
        self.body = Adw.Bin(vexpand=True)
        self.buttons = Gtk.Box(spacing=6, homogeneous=True, margin_start=12, margin_end=12, margin_top=12,
                               margin_bottom=12, halign=Gtk.Align.CENTER)
        view = Adw.ToolbarView(content=self.body)
        view.add_top_bar(self.header)
        view.add_bottom_bar(self.buttons)
        self.set_child(view)
        self.connect("closed", lambda _d: self._stop())
        self._run()

    def _stop(self):
        self._unwatch()
        if self.check:
            self.check.stop()

    def _unwatch(self):
        for handler in self._watch:
            self.pipeline.disconnect(handler)
        self._watch = []

    def _button(self, label, callback, suggested=False):
        button = Gtk.Button(label=label, css_classes=["suggested-action"] if suggested else [])
        button.connect("clicked", lambda _b: callback())
        self.buttons.append(button)

    def _set_buttons(self, *buttons):
        while child := self.buttons.get_first_child():
            self.buttons.remove(child)
        for button in buttons:
            self._button(*button)

    def _run(self):
        self._stop()
        self.check = monitor.Check(self.pipeline)
        self.cuts = []
        self._relabelled = 0.0
        if self.pipeline.preset:
            self.heading.set_subtitle(self.pipeline.preset.name)
        self.check.connect("updated", self._on_updated)
        self.check.connect("aborted", self._on_aborted)
        self.rows = {}
        group = Adw.PreferencesGroup(description="Play audio while the check runs")
        for stage in self.check.stages:
            row = Adw.ActionRow(title=stage.title, subtitle=overs_text(self.check.readings[stage.key]))
            self.rows[stage.key] = row
            group.add(row)
        self.monitoring = group
        page = Adw.PreferencesPage()
        page.add(group)
        self.body.set_child(page)
        self._set_buttons(("Stop", self._summarise, True))
        self.check.start()

    def _on_updated(self, check_):
        if check_.elapsed - self._relabelled < LIVE_INTERVAL:
            return
        self._relabelled = check_.elapsed
        self.monitoring.set_title(f"Elapsed {elapsed_text(check_.elapsed)}")
        for key, row in self.rows.items():
            row.set_subtitle(overs_text(check_.readings[key]))

    def _on_aborted(self, _check, reason):
        self._show_stopped(reason)

    def _show_stopped(self, reason):
        self._unwatch()
        self.cuts = []
        self.body.set_child(Adw.StatusPage(icon_name="dialog-warning-symbolic", title="Check Stopped",
                                           description=reason))
        self._set_buttons(("Run Again", self._run, True), ("Close", self.close))

    def _on_pipeline_changed(self, *_):
        if self.pipeline.stages() != self.check.stages:
            self._show_stopped("The effects changed during the check")

    def _summarise(self):
        check_ = self.check
        check_.stop()
        if nothing_measured(check_.before, check_.readings):
            self.body.set_child(Adw.StatusPage(
                icon_name="audio-volume-muted-symbolic", title="Nothing Measured",
                description="Nothing was measured. Play some audio while the check runs."))
            self._set_buttons(("Run Again", self._run, True), ("Close", self.close))
            return

        pipeline = self.pipeline
        settings = pipeline.controller.settings
        trimmed = check.trimmed(pipeline.preset, pipeline.trims)
        levels = check.trimmed_levels(settings.layout, pipeline.levels, pipeline.trims)
        room = check.room(trimmed, check_.stages, settings.layout, levels)
        self.cuts, leftover = check.plan_cuts(check_.stages, check_.readings, room)
        planned = {cut.key: cut for cut in self.cuts}

        group = Adw.PreferencesGroup()
        for text in (input_text(check_.before), leftover_text(leftover)):
            if text:
                group.add(Adw.ActionRow(title=text))
        before = check_.before
        for stage in check_.stages:
            reading = check_.readings[stage.key]
            change = check.level_change(before, reading)
            before = reading
            lines = [overs_text(reading), change_text(stage, change, settings.layout)]
            if stage.key in planned:
                lines.append(cut_text(planned[stage.key]))
            row = Adw.ActionRow(title=stage.title, subtitle="\n".join(line for line in lines if line))
            if change is not None and check.drop_flagged(stage, change, settings.layout):
                row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            group.add(row)
        page = Adw.PreferencesPage()
        page.add(group)
        self.body.set_child(page)
        self.summary = group
        if self.cuts:
            self._watch = [self.pipeline.connect(name, self._on_pipeline_changed)
                           for name in ("state-changed", "preset-changed")]
            self._set_buttons(("Fix Settings", lambda: self._fix(False), True),
                              ("Fix and Save Preset", lambda: self._fix(True)), ("Cancel", self.close))
        else:
            self._set_buttons(("Run Again", self._run, True), ("Close", self.close))

    def _fix(self, save):
        self._unwatch()
        self.pipeline.fix(self.cuts, save)
        self.summary.set_description("The settings have been lowered. Run the check again to confirm.")
        self._set_buttons(("Run Again", self._run, True), ("Close", self.close))
