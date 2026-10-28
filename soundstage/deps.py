"""What Soundstage needs installed, and the other audio apps it replaces."""

import configparser
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gi.repository import GLib

from .plugins import LV2_DIRS

FILTER_GRAPH_DIRS = (Path("/usr/lib64/spa-0.2/filter-graph"), Path("/usr/lib/spa-0.2/filter-graph"))


@dataclass
class Component:
    title: str
    description: str
    package: str
    files: tuple = ()
    commands: tuple = ()
    bundles: tuple = ()

    def installed(self):
        return (
            all(any((d / f).exists() for d in FILTER_GRAPH_DIRS) for f in self.files)
            and all(shutil.which(c) for c in self.commands)
            and all(any((d / b).is_dir() for d in LV2_DIRS) for b in self.bundles)
        )


COMPONENTS = (
    Component("PipeWire tools", "Lets Soundstage watch and control audio devices", "pipewire-utils",
              commands=("pw-dump", "pw-cli")),
    Component("WirePlumber", "Chooses the default output device", "wireplumber", commands=("wpctl",)),
    Component("PipeWire plugin host", "Runs LV2 effect plugins inside PipeWire", "pipewire-module-filter-chain-lv2",
              files=("libspa-filter-graph-plugin-lv2.so",)),
    Component("LSP plugins", "Equalizer, compressor, limiter, gate, loudness and autogain", "lsp-plugins-lv2",
              bundles=("lsp-plugins.lv2",)),
    Component("ZAM plugins", "Maximizer", "lv2-zam-plugins", bundles=("ZaMaximX2.lv2",)),
)


def missing():
    return [c for c in COMPONENTS if not c.installed()]


def install_command(packages):
    if shutil.which("dnf"):
        return ["pkexec", "dnf", "install", "-y", *packages]
    if shutil.which("rpm-ostree"):
        return ["pkexec", "rpm-ostree", "install", "--idempotent", "--apply-live", *packages]
    return None


@dataclass
class Conflict:
    title: str
    description: str
    flatpak: str = ""
    process: str = ""
    autostart: tuple = ()

    def autostart_files(self):
        folder = Path(GLib.get_user_config_dir()) / "autostart"
        return [folder / name for name in self.autostart if (folder / name).exists() and not _hidden(folder / name)]

    def running(self):
        if self.flatpak:
            out = subprocess.run(["flatpak", "ps", "--columns=application"], capture_output=True, text=True).stdout
            if self.flatpak in out.split():
                return True
        return bool(self.process) and subprocess.run(["pgrep", "-x", self.process],
                                                     capture_output=True).returncode == 0

    def active(self):
        return self.running() or bool(self.autostart_files())

    def turn_off(self):
        """Stops the app and hides its autostart entry; Hidden=true is the XDG way to disable one."""
        for path in self.autostart_files():
            entry = configparser.ConfigParser(interpolation=None, strict=False)
            entry.optionxform = str
            entry.read(path)
            if "Desktop Entry" in entry:
                entry["Desktop Entry"]["Hidden"] = "true"
                with open(path, "w") as f:
                    entry.write(f, space_around_delimiters=False)
        if self.flatpak:
            subprocess.run(["flatpak", "kill", self.flatpak], capture_output=True)
        if self.process:
            subprocess.run(["pkill", "-x", self.process], capture_output=True)


def _hidden(path):
    entry = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        entry.read(path)
        return entry.get("Desktop Entry", "Hidden", fallback="false").lower() == "true"
    except configparser.Error:
        return False


CONFLICTS = (
    Conflict("Easy Effects", "Soundstage uses its presets, but both cannot process audio at once",
             flatpak="com.github.wwmm.easyeffects", process="easyeffects",
             autostart=("com.github.wwmm.easyeffects.desktop", "easyeffects-service.desktop")),
    Conflict("Virtual Surround", "Soundstage does the surround downmixing itself",
             flatpak="de.berny23.virtual_surround_manager",
             autostart=("de.berny23.virtual_surround_manager.desktop",)),
)


def active_conflicts():
    return [c for c in CONFLICTS if c.active()]


AUTOSTART = Path(GLib.get_user_config_dir()) / "autostart" / "uk.co.solarflareit.Soundstage.desktop"


def set_autostart(on, command):
    if not on:
        AUTOSTART.unlink(missing_ok=True)
        return
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text(
        "[Desktop Entry]\nType=Application\nName=Soundstage\nIcon=uk.co.solarflareit.Soundstage\n"
        f"Exec={command} --background\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
    )
