from pathlib import Path
from typing import List, Dict

from config.settings import DATA_DIR
from utils.file_utils import display_company_name, list_company_folders


def _folder_priority(folder_name: str) -> tuple:
    encoded_penalty = 1 if "#U" in folder_name else 0
    system_penalty = 1 if folder_name.startswith("_") else 0
    return (system_penalty, encoded_penalty, len(folder_name), folder_name)


def get_company_options() -> List[Dict[str, str]]:
    folders = [
        folder for folder in list_company_folders(DATA_DIR)
        if folder and not folder.startswith("_") and not folder.startswith(".")
    ]
    grouped = {}

    for folder in folders:
        label = display_company_name(folder).strip() or folder
        grouped.setdefault(label, [])
        grouped[label].append(folder)

    options = []
    for label, raw_folders in grouped.items():
        raw_folders = sorted(raw_folders, key=_folder_priority)
        chosen = raw_folders[0]
        options.append({"value": chosen, "label": label})

    options.sort(key=lambda item: item["label"])
    return options


def get_company_select_values() -> List[str]:
    return [""] + [item["value"] for item in get_company_options()]


def get_company_label_map() -> Dict[str, str]:
    return {"": "— 请选择公司 —", **{item["value"]: item["label"] for item in get_company_options()}}


def format_company_option(value: str) -> str:
    return get_company_label_map().get(value, value)


def get_company_folder_path(company_value: str) -> Path:
    return Path(DATA_DIR) / company_value
