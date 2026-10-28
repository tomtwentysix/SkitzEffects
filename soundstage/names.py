"""System-wide device names, kept as WirePlumber rules in a file Soundstage owns.

Node rules rename one output or input exactly as GNOME shows it; card rules
rename a whole sound card, and GNOME adds the profile ("Analog Stereo").
Other files in the folder that hold nothing but renames are taken over on the
first rename and disabled, so every name lives in one place.
"""

import json
import re
from pathlib import Path

from gi.repository import Gio, GLib

CONF_DIR = Path(GLib.get_user_config_dir()) / "wireplumber" / "wireplumber.conf.d"
OWN = CONF_DIR / "60-soundstage-device-names.conf"
MONITORS = {"alsa_": "monitor.alsa.rules", "bluez_": "monitor.bluez.rules"}
KEYS = {"node": ("node.name", "node.description", "node.nick"),
        "card": ("device.name", "device.description", "device.nick")}

TOKEN = re.compile(r'\s+|#[^\n]*|"(?:\\.|[^"\\])*"|[{}\[\]=:,]|[^\s{}\[\]=:,"#]+')


def parse(text):
    """Reads PipeWire's relaxed JSON: bare keys, = or : separators, optional commas, # comments."""
    tokens = [t for t in TOKEN.findall(text) if t.strip() and not t.startswith("#")]
    value, _ = _object(tokens, 0, None)
    return value


def _scalar(token):
    try:
        return json.loads(token)
    except ValueError:
        return token


def _value(tokens, i):
    if tokens[i] == "{":
        return _object(tokens, i + 1, "}")
    if tokens[i] == "[":
        items, i = [], i + 1
        while tokens[i] != "]":
            if tokens[i] == ",":
                i += 1
                continue
            item, i = _value(tokens, i)
            items.append(item)
        return items, i + 1
    return _scalar(tokens[i]), i + 1


def _object(tokens, i, end):
    out = {}
    while i < len(tokens) and tokens[i] != end:
        if tokens[i] == ",":
            i += 1
            continue
        key = _scalar(tokens[i])
        i += 1
        if tokens[i] in ("=", ":"):
            i += 1
        out[str(key)], i = _value(tokens, i)
    return out, i + 1


def monitor(name):
    return next((section for prefix, section in MONITORS.items() if name.startswith(prefix)), None)


def renamable(name):
    return monitor(name) is not None


def read(path):
    """Rename rules in a file as {(kind, name): description}, or None if it holds anything else."""
    try:
        data = parse(path.read_text())
    except (OSError, IndexError, ValueError):
        return None
    names = {}
    for section, rules in data.items():
        if section not in MONITORS.values() or not isinstance(rules, list):
            return None
        for rule in rules:
            props = rule.get("actions", {}).get("update-props", {})
            matches = rule.get("matches", [])
            if set(rule) - {"matches", "actions"} or set(rule.get("actions", {})) - {"update-props"}:
                return None
            for kind, (match_key, desc_key, nick_key) in KEYS.items():
                if desc_key in props and set(props) <= {desc_key, nick_key}:
                    break
            else:
                return None
            for match in matches:
                name = match.get(match_key)
                if len(match) != 1 or not isinstance(name, str) or name.startswith("~"):
                    return None
                names[(kind, name)] = props[desc_key]
    return names


def custom():
    return read(OWN) or {}


def _take_over():
    names = {}
    for path in sorted(CONF_DIR.glob("*.conf")):
        if path == OWN:
            continue
        found = read(path)
        if found:
            names.update(found)
            path.rename(path.with_name(path.name + ".disabled"))
    return names


def write(names):
    sections = {}
    for (kind, name), description in sorted(names.items()):
        section = monitor(name)
        if section is None:
            continue
        match_key, desc_key, nick_key = KEYS[kind]
        text = json.dumps(description)
        sections.setdefault(section, []).append(
            f"  {{\n    matches = [ {{ {match_key} = {json.dumps(name)} }} ]\n"
            f"    actions = {{ update-props = {{ {desc_key} = {text} {nick_key} = {text} }} }}\n  }}"
        )
    body = "\n".join(f"{section} = [\n" + "\n".join(rules) + "\n]\n" for section, rules in sections.items())
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OWN.with_suffix(".tmp")
    tmp.write_text("# Written by Soundstage; rename devices from its Devices page.\n" + body)
    tmp.replace(OWN)


def rename(node_name, description):
    """Sets or, with an empty description, removes a node's name; returns once the file is written."""
    names = {**_take_over(), **custom()}
    if description:
        names[("node", node_name)] = description
    else:
        names.pop(("node", node_name), None)
    write(names)


def restart_wireplumber(done):
    """WirePlumber reads rules only at startup, so names apply after a restart."""
    proc = Gio.Subprocess.new(["systemctl", "--user", "restart", "wireplumber.service"], Gio.SubprocessFlags.NONE)
    proc.wait_async(None, lambda p, result: (p.wait_finish(result), done()))
