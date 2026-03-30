"""Autonomous runtime — server-driven development loop.

Deterministic server process that orchestrates Claude Agent SDK sessions,
manages task queues via PostgreSQL, and sends Telegram notifications.
Python controls the loop. LLMs provide intelligence.
"""
