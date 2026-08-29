"""Test access to the scripted model.

The handlers themselves live in app/adapters/scripted_world.py, because they are
also what makes `VDS_USE_SCRIPTED_MODEL=true` work for anyone running the system
without a Google Cloud project.
"""

from app.adapters.scripted_world import (  # noqa: F401
    NODES,
    _discovery,
    _extract_quote,
    build_scripted_llm,
)
