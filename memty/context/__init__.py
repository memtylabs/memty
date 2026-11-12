"""Turning stored facts into a capsule an assistant can read.

``privacy`` decides what a provider may see (SECRET never leaves the device,
CONFIDENTIAL is redacted, allow/block lists apply).  ``compiler`` ranks and
packs the allowed facts into a token budget, and ``render`` turns the result
into plain ``Title: value`` lines for chat apps.
"""
