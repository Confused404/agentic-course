"""GIVEN: the scopes each Shopfront support tool requires (Node 13 TEXTBOOK §3).

"public" tools need no scope beyond a valid token. A token carries a space-separated list of scopes; a session
built from it may only SEE and CALL tools whose scope it holds (least privilege at listing time and at call time).
"""
TOOL_SCOPES = {
    "search_help_center": "public",
    "get_my_orders": "orders:read",
    "lookup_order": "orders:read",
    "check_refund_eligibility": "orders:read",
    "cancel_order": "orders:write",
    "issue_refund": "refunds:write",
    "escalate_to_human": "tickets:write",
}
SCOPES = ("orders:read", "orders:write", "refunds:write", "tickets:write")
