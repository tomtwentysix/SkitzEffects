from gi.repository import Adw, Gio, GLib, Gtk

from .. import presets


def import_ir(widget, title, fits, wrong, on_imported):
    """Asks for a WAV, checks it with fits(channels), copies it into the IR folder and calls
    on_imported(path, replaced); wrong is the toast shown for a file that does not fit."""
    wavs = Gtk.FileFilter(name="WAV files")
    wavs.add_suffix("wav")
    wavs.add_suffix("irs")
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(wavs)
    root = widget.get_root()

    def copy(path, replace=False):
        try:
            on_imported(presets.import_ir(path, replace), replace)
        except FileExistsError as e:
            ask_replace(path, e.args[0])
        except OSError as e:
            root.toast(f"Could not import the file: {e.strerror}")

    def ask_replace(path, existing):
        dialog = Adw.AlertDialog(heading="Replace Impulse Response?",
                                 body=f"“{existing.name}” is already in the impulse response folder.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("replace", "Replace")
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _d, r: r == "replace" and copy(path, True))
        dialog.present(root)

    def chosen(dialog, result):
        try:
            path = dialog.open_finish(result).get_path()
        except GLib.Error:
            return
        if not fits(presets.wav_channels(path)):
            root.toast(wrong)
            return
        copy(path)

    Gtk.FileDialog(title=title, filters=filters).open(root, None, chosen)
