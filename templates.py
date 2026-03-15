"""
Post templates: reusable text skeletons for common post types.
Storage in data/templates.json.
"""
import json
import os
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TEMPLATES_JSON = os.path.join(DATA_DIR, "templates.json")

os.makedirs(DATA_DIR, exist_ok=True)


def _load():
    try:
        with open(TEMPLATES_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(records):
    with open(TEMPLATES_JSON, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def list_templates():
    return _load()


def get_template(tpl_id):
    for t in _load():
        if t.get("id") == tpl_id:
            return t
    return None


def create_template(name, body, platform=None):
    record = {
        "id": "tpl_" + uuid.uuid4().hex[:8],
        "name": name,
        "body": body,
        "platform": platform or "",
    }
    records = _load()
    records.append(record)
    _save(records)
    return record


def update_template(tpl_id, name=None, body=None, platform=None):
    records = _load()
    for t in records:
        if t.get("id") == tpl_id:
            if name is not None:
                t["name"] = name
            if body is not None:
                t["body"] = body
            if platform is not None:
                t["platform"] = platform
            _save(records)
            return t
    return None


def delete_template(tpl_id):
    records = _load()
    records = [t for t in records if t.get("id") != tpl_id]
    _save(records)
