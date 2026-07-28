from dataclasses import fields


def iter_numeric(obj, excluded_fields: list[str] | None = None):
    for f in fields(obj):
        if f.name in excluded_fields:
            continue
        yield f.name, getattr(obj, f.name)
