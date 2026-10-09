"""Size limits for data that arrives in requests (risk-audit finding F-03).

Without these, a request could carry an enormous resume structure or a very long text field: it would be stored, or forwarded
to the paid AI service at the owner's expense. The caps are generous for real use (a long resume is a few thousand
characters) and tiny compared with an abusive request. A request over a cap gets a normal 422 answer saying which field.

Use them in request models:  resume_data: BoundedDict    title: Short    description: Long | None = None
"""
import json
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

MAX_STRUCTURE_CHARS = 400_000   # a whole resume or interview history, written out as JSON
MAX_ITEMS = 500                 # entries in any one list we accept from the browser


def _bounded(value):
    if isinstance(value, (list, tuple)) and len(value) > MAX_ITEMS:
        raise ValueError(f"That list is too long (more than {MAX_ITEMS} items).")
    if len(json.dumps(value, default=str)) > MAX_STRUCTURE_CHARS:
        raise ValueError("That is too much data in one request.")
    return value


BoundedDict = Annotated[dict, AfterValidator(_bounded)]
BoundedList = Annotated[list, AfterValidator(_bounded)]
BoundedDictList = Annotated[list[dict], AfterValidator(_bounded)]

Tiny = Annotated[str, StringConstraints(max_length=100)]       # dates, short labels, a status
Short = Annotated[str, StringConstraints(max_length=300)]      # names, titles, organizations, a contact line
Medium = Annotated[str, StringConstraints(max_length=2_000)]   # a sentence or two of source text
Long = Annotated[str, StringConstraints(max_length=20_000)]    # a role description, notes, a summary
