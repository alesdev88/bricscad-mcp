"""`python -m bricscad_mcp`, which is how the MCPB bundle starts the server.

Not `-m bricscad_mcp.server`: that would load server.py a second time as __main__, and the tools
would register on the other copy.
"""

from .server import main

main()
