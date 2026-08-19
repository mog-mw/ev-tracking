from urllib.request import urlopen
import json
import tomllib
import yaml
from pathlib import Path
from os import makedirs


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(IndentDumper, self).increase_indent(flow, False)


class InlineList(list):
    pass


class MultilineStr(str):
    pass


def inline_list_representer(dumper, data):
    return dumper.represent_sequence(u'tag:yaml.org,2002:seq', data, flow_style=True)


def multiline_str_presenter(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


yaml.add_representer(InlineList, inline_list_representer)
yaml.add_representer(MultilineStr, multiline_str_presenter)

LIST_URL = "https://modding-openmw.com/api/lists/expanded-vanilla"
CONFIG_URL = "https://modding-openmw.com/api/cfg-generator/expanded-vanilla"
EXTRA_CFG_URL = "https://gitlab.com/modding-openmw/modding-openmw.com/-/raw/master/momw/momw/data_seeds/data/extra-cfg.toml"
SEED_URL = "https://gitlab.com/modding-openmw/modding-openmw.com/-/raw/master/momw/momw/data_seeds/data/expanded-vanilla.toml"
DEFAULTS = {
    "name": "",
    "url": "",
    "dl_url": "",
    "download_info": [],
    "data_paths": [""],
    "plugins": [],
}
DOWNLOAD_INFO_DEFAULTS = {
    "direct_download": None,
    "file_name": None,
    "nexus_file_id": None,
    "extract_to": "",
    "pinned": False,
    "actions": [],
}

# key is the name of the category; value is the list of mods in it.
output_categories = {
    "ModdingResources": [{
        "name": "Morrowind",
        "data_paths": ["Data Files"],
        "plugins": ["Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm"],
        "archives": ["Morrowind.bsa", "Tribunal.bsa", "Bloodmoon.bsa"],
    }]
}


def main():
    with urlopen(CONFIG_URL) as response:
        config = json.load(response)

    makedirs("expanded-vanilla/load_orders", exist_ok=True)

    groundcover = []

    for (field, filename, prefix, insert_above) in (
            ("data paths", "data_paths", "data=C:\\games\\OpenMWMods\\", "MOMWToolsPack"),
            ("fallback archives", "archives", "fallback-archive=", None),
            ("content files", "plugins", "content=", "momw-gameplay.omwscripts"),
            ("groundcover files", "groundcover", "groundcover=", "groundcover.omwaddon")):
        with open(f"expanded-vanilla/load_orders/{filename}", "w") as f:
            for line in config["openmw_cfg"][field].split("\n"):
                assert line.startswith(prefix)
                line = line.removeprefix(prefix)

                if field == "data paths":
                    line = line.replace("\\", "/")
                    line = line[line.index("/")+1:]

                if field == 'groundcover files':
                    groundcover.append(line)

                if line == insert_above:
                    f.write("# insert new entries above\n")

                f.write(line+"\n")
    with urlopen(SEED_URL) as response:
        seed = tomllib.load(response)

    settings_list = []
    for i, j in enumerate(seed["sublists"]):
        if j["title"] in ("Settings Tweaks"):
            settings_list.extend(j["mods"])

    with urlopen(EXTRA_CFG_URL) as response:
        extra_cfg = tomllib.load(response)

    extra_fields = {}

    for cfg in extra_cfg["extra_cfg"]:
        if "on_lists" not in cfg or "expanded-vanilla" not in cfg["on_lists"]:
            continue
        for mod in cfg["for_mods"]:
            lines = cfg["text"].split("\n")
            i = 0
            for i, line in enumerate(lines):
                if line.startswith("["):
                    break
                line = line.strip()
                if line == "":
                    continue
                field = line.split("=")[0]
                match field:
                    case "fallback-archive":
                        extra_fields.setdefault(mod, {})
                        extra_fields[mod].setdefault("archives", [])
                        extra_fields[mod]["archives"].append(
                            line.removeprefix("fallback-archive="))
                    case "fallback":
                        extra_fields.setdefault(mod, {})
                        extra_fields[mod].setdefault("fallbacks", [])
                        extra_fields[mod]["fallbacks"].append(
                            line.removeprefix("fallback="))
                    case _:
                        raise AssertionError(line)

            if i != len(lines)-1:
                extra_fields.setdefault(mod, {})
                extra_fields[mod].setdefault("settings", MultilineStr(""))
                extra_fields[mod]["settings"] = MultilineStr(
                    extra_fields[mod]["settings"] + "\n".join(lines[i:]))

    with urlopen(LIST_URL) as response:
        mods = json.load(response)

    for mod in mods:
        category = mod["category"]
        if category in ("FirstSteps"):
            continue

        new_mod = {}
        for field, default in DEFAULTS.items():
            if field == "download_info":
                assert len(mod["download_info"]) != 0
                new_dl_info = []
                for dl_info_entry in mod["download_info"]:
                    dl_info_entry = reformat_dl_info(dl_info_entry, mod["dir"])
                    if dl_info_entry == {}:
                        assert len(new_dl_info) == 0 and \
                            len(mod["download_info"]) == 1
                        break
                    new_dl_info.append(dl_info_entry)
                if new_dl_info != []:
                    new_mod["download_info"] = new_dl_info
                continue
            if field == "data_paths":
                for i in range(len(mod["data_paths"])):
                    mod["data_paths"][i] = remove_path_prefix(
                        mod["data_paths"][i], mod["dir"])
                    assert not mod["data_paths"][i].startswith("..")
            if field in ("url", "dl_url"):
                if mod[field].startswith("/"):
                    mod[field] = "https://modding-openmw.com" + mod[field]
            if field == "plugins":
                for i in mod["plugins"]:
                    if i in groundcover:
                        new_mod.setdefault("groundcover", [])
                        new_mod["groundcover"].append(i)
                    else:
                        new_mod.setdefault("plugins", [])
                        new_mod["plugins"].append(i)
                continue

            if mod[field] == default:
                continue
            new_mod[field] = mod[field]

        if new_mod["name"] in extra_fields:
            new_mod.update(extra_fields[new_mod["name"]])

        if category not in output_categories:
            output_categories[category] = []
        output_categories[category].append(new_mod)

    output_categories["SettingsTweaks"] = []

    for i in settings_list:
        new_mod = {"name": i}
        new_mod.update(extra_fields[new_mod["name"]])
        output_categories["SettingsTweaks"].append(new_mod)

    makedirs("expanded-vanilla/mods", exist_ok=True)

    # clear output dir
    for i in Path("expanded-vanilla/mods").iterdir():
        if i.is_file():
            i.unlink()

    for category, mods in output_categories.items():
        output = {}
        output["category"] = category
        output["mods"] = mods

        s = yaml.dump(output, Dumper=IndentDumper, sort_keys=False,
                      default_flow_style=False, width=1000000)

        # add line breaks for readability
        lines = s.split("\n")
        lines[0] = lines[0] + "\n"
        for i in range(3, len(lines)):
            if lines[i].startswith("  - "):
                lines[i] = "\n" + lines[i]
        s = "\n".join(lines)

        with open(f"expanded-vanilla/mods/{category}.yml", "w") as f:
            f.write(s)


def reformat_dl_info(dl_info, prefix):
    dl_info["extract_to"] = remove_path_prefix(dl_info["extract_to"], prefix)
    assert not dl_info["extract_to"].startswith("..")

    new_dl_info = {}
    for field, default in DOWNLOAD_INFO_DEFAULTS.items():
        if dl_info[field] == default:
            continue
        new_dl_info[field] = dl_info[field]

    if "actions" in new_dl_info:
        for action in new_dl_info["actions"]:
            for i in ("path", "src", "dst"):
                if i not in action:
                    continue
                action[i] = remove_path_prefix(action[i], prefix)
            if "paths" in action:
                for i, j in enumerate(action["paths"]):
                    action["paths"][i] = remove_path_prefix(j, prefix)
            if "arguments" in action:
                action["arguments"] = InlineList(action["arguments"])

    return new_dl_info


def remove_path_prefix(path, prefix):
    if path == prefix:
        return ""
    elif path.startswith(prefix + "/"):
        return path.removeprefix(prefix + "/")
    else:
        return "../" + path


if __name__ == "__main__":
    main()
