from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    if hasattr(mapping, "get"):
        return mapping.get(key)
    return None
