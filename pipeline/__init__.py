"""
pipeline/ — Phase-based cycle loop for yonc_agent.

Phases:
  1. FormatCheckPhase  — rule-based tag structure validation
  2. WBSTagPhase       — WBS level assignment with block context
  3. SplitTaskPhase    — interactive CLI task decomposition
  4. EnrichPhase       — priority, type, mode, and state tagging
"""
