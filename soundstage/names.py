"""Per-device settings kept as WirePlumber rules in a file Soundstage owns.

Node rules rename one output or input exactly as GNOME shows it, keep it from
suspending or pin its sample rate; card rules rename a whole sound card, and
GNOME adds the profile ("Analog Stereo"). Other files in the folder that hold
nothing but renames are taken over on the first change and disabled, so every
name lives in one place.
"""

import json
import re
from pathlib import Path

from gi.repository import Gio, GLib

CONF_DIR = Path(GLib.get_user_config_dir()) / "wireplumber" / "wireplumber.conf.d"
OWN = CONF_DIR / "60-soundstage-devices.conf"
MONITORS = {"alsa_": "monitor.alsa.rules", "bluez_": "monitor.bluez.rules"}
MATCH = {"node": "node.name", "card": "device.name"}
NAME_KEYS = {"node": ("node.description", "node.nick"), "card": ("device.description", "device.nick")}
AWAKE = "session.suspend-timeout-seconds"
RATE = "audio.rate"
# The props Soundstage writes, by rule kind; files holding anything else are left alone.
KNOWN = {"node": {*NAME_KEYS["node"], AWAKE, RATE}, "card": set(NAME_KEYS["card"])}

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


def read(path, known=KNOWN):
    """Rules in a file as {(kind, name): props}, or None if it holds anything else."""
    try:
        data = parse(path.read_text())
    except (OSError, IndexError, ValueError):
        return None
    rules = {}
    for section, entries in data.items():
        if section not in MONITORS.values() or not isinstance(entries, list):
            return None
        for rule in entries:
            props = rule.get("actions", {}).get("update-props", {})
            matches = rule.get("matches", [])
            if set(rule) - {"matches", "actions"} or set(rule.get("actions", {})) - {"update-props"}:
                return None
            kind = next((k for k, keys in known.items() if props and set(props) <= keys), None)
            if kind is None:
                return None
            for match in matches:
                name = match.get(MATCH[kind])
                if len(match) != 1 or not isinstance(name, str) or name.startswith("~"):
                    return None
                rules.setdefault((kind, name), {}).update(props)
    return rules


def rules():
    return read(OWN) or {}


def custom():
    """Names Soundstage has set, as {(kind, name): description}."""
    return {key: props[NAME_KEYS[key[0]][0]] for key, props in rules().items() if NAME_KEYS[key[0]][0] in props}


def node_props(node_name):
    return rules().get(("node", node_name), {})


def _take_over():
    found_all = {}
    renames = {kind: set(keys) for kind, keys in NAME_KEYS.items()}
    for path in sorted(CONF_DIR.glob("*.conf")):
        if path == OWN:
            continue
        found = read(path, renames)
        if found:
            found_all.update(found)
            path.rename(path.with_name(path.name + ".disabled"))
    return found_all


def write(all_rules):
    sections = {}
    for (kind, name), props in sorted(all_rules.items()):
        section = monitor(name)
        if section is None or not props:
            continue
        body = " ".join(f"{key} = {json.dumps(value)}" for key, value in props.items())
        sections.setdefault(section, []).append(
            f"  {{\n    matches = [ {{ {MATCH[kind]} = {json.dumps(name)} }} ]\n"
            f"    actions = {{ update-props = {{ {body} }} }}\n  }}"
        )
    text = "\n".join(f"{section} = [\n" + "\n".join(entries) + "\n]\n" for section, entries in sections.items())
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OWN.with_suffix(".tmp")
    tmp.write_text("# Written by Soundstage; change these from its Devices page.\n" + text)
    tmp.replace(OWN)


def update(node_name, props):
    """Sets a node's props; a value of None removes that prop. Returns once the file is written."""
    all_rules = {**_take_over(), **rules()}
    current = all_rules.setdefault(("node", node_name), {})
    for key, value in props.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    if not current:
        del all_rules[("node", node_name)]
    write(all_rules)


def rename(node_name, description):
    update(node_name, dict.fromkeys(NAME_KEYS["node"], description or None))


def restart_wireplumber(done):
    """WirePlumber reads rules only at startup, so changes apply after a restart."""
    proc = Gio.Subprocess.new(["systemctl", "--user", "restart", "wireplumber.service"], Gio.SubprocessFlags.NONE)
    proc.wait_async(None, lambda p, result: (p.wait_finish(result), done()))
