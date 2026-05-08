from dataclasses import fields
from typing import List, Optional


def iter_numeric(obj, excluded_fields: Optional[List[str]] = None):
    for f in fields(obj):
        if f.name in excluded_fields:
            continue
        yield f.name, getattr(obj, f.name)
