"""The routers: one module per surface, plus the state they share.

    app_state.py   paths, the book cache, the database, the AI service
    text.py        word counts and reading times
    titles.py      slugs, folder names, the library's ordering
    assets.py      cache-busting versions

Each router imports what it needs from those directly (`from .app_state import
get_db`), so a file's dependencies are its own import block rather than a
function-local line hidden in the middle of a handler. This module holds no code
of its own: it is the package, and its docstring is the map (REVIEW P3-14).
"""
