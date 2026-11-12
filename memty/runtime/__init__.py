"""Background processes.

``daemon`` is ``memtyd``: one process per vault that every CLI, MCP and browser
call goes through.  ``autostart`` registers the browser bridge to start at login.
"""
