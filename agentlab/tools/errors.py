"""Given (Node 03). An exception type for errors that should be shown to the MODEL as-is.

Raise ToolError("message the model can act on") inside a tool. ToolRegistry.execute (Node 03 SPEC adds this)
turns it into ToolResultBlock(is_error=True, content=<the message>), with no "Tool X failed: ..." wrapping
and no exception type name.
"""


class ToolError(Exception):
    pass
