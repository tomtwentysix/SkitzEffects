from gi.repository import Adw


def unsaved_pipelines(pipelines):
    return [p for p in pipelines if p.unsaved or p.levels_unsaved]


def prompt_text(pipelines, quitting):
    lines = []
    for pipeline in unsaved_pipelines(pipelines):
        if pipeline.unsaved:
            lines.append(f'The {pipeline.direction} preset "{pipeline.preset.name}" has unsaved changes.')
        if pipeline.levels_unsaved:
            names = pipeline.state["device_names"]
            device = names.get(pipeline.levels_owner, pipeline.levels_owner)
            lines.append(f'The surround levels of "{device}" have unsaved changes.')
    action = "Quitting" if quitting else "Switching"
    return f"Save Changes Before {action}?", "\n".join(lines)


def ask(window, pipelines, quitting, done):
    heading, body = prompt_text(pipelines, quitting)
    verb = "Quit" if quitting else "Switch"
    dialog = Adw.AlertDialog(heading=heading, body=body, close_response="cancel", default_response="save")
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("discard", f"Discard and {verb}")
    dialog.add_response("save", f"Save and {verb}")
    dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.connect("response", lambda _d, response: done(response))
    dialog.present(window)
    return dialog
