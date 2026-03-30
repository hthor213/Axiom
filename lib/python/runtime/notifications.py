"""Telegram notifications — batch complete, spec alignment alerts, draft questions.

Telegram failures log and continue — this is the one place
except Exception is acceptable.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from .db import Task, TaskStore, DraftReview


def send_batch_complete(run_id: int, completed: int, failed: int,
                        reason: str, store: TaskStore, config):
    """Send Telegram batch complete notification with spec details."""
    try:
        lib_path = os.path.join(config.repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from platform_telegram import notify

        repo_name = os.path.basename(config.repo_root)
        url = f"{config.dashboard_url}/results"

        # Get spec details for this run
        spec_lines = ""
        try:
            tasks = store.get_tasks_for_run(run_id)
            seen = set()
            spec_parts = []
            for t in tasks:
                if t.spec_number not in seen:
                    seen.add(t.spec_number)
                    spec_parts.append(f"{t.spec_number} {t.spec_title}")
            if spec_parts:
                spec_lines = f"Specs: {', '.join(spec_parts)}\n"
        except Exception:
            pass

        # Check for tasks needing human input
        waiting_lines = ""
        try:
            waiting = [t for t in tasks if t.status == "waiting_for_human"]
            if waiting:
                parts = [f"- {t.spec_number}: {t.done_when_item[:60]}" for t in waiting]
                waiting_lines = (
                    f"\n<b>Needs your input ({len(waiting)}):</b>\n"
                    + "\n".join(parts) + "\n"
                )
        except Exception:
            pass

        msg = (
            f"<b>Batch Complete ({repo_name})</b>\n\n"
            f"{spec_lines}"
            f"{completed} done, {failed} failed\n"
            f"Reason: {reason}\n"
            f"{waiting_lines}\n"
            f"<a href=\"{url}\">Review Results</a>"
        )
        notify(msg)
    except Exception as e:
        # Telegram is best-effort
        print(f"Telegram notification failed: {e}", file=sys.stderr)


def send_spec_alignment_alert(task: Task, category_c_items: list[dict],
                               config):
    """Send Telegram alert for category C (outside spec) items."""
    try:
        lib_path = os.path.join(config.repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from platform_telegram import notify

        items_text = ""
        for item in category_c_items[:5]:  # max 5 to keep message short
            items_text += f"\n- {item.get('description', item.get('id', '?'))[:100]}"

        msg = (
            f"<b>Spec Alignment Alert: {task.spec_number}</b>\n\n"
            f"Claude added changes outside the spec:\n"
            f"{items_text}\n\n"
            f"Task is paused. Allow / Reject / Update spec?"
        )
        notify(msg)
    except Exception as e:
        print(f"Telegram spec alignment alert failed: {e}", file=sys.stderr)


def send_draft_questions(draft: DraftReview, config):
    """Send a notification to Telegram with link to dashboard drafts."""
    try:
        lib_path = os.path.join(config.repo_root, "lib", "python")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from platform_telegram import notify

        total = len(draft.questions) if draft.questions else 0
        if total == 0:
            return

        url = getattr(config, "dashboard_url", "https://spliffdonk.com")
        msg = (
            f"\U0001f4cb Draft Review: Spec {draft.spec_number} \u2014 "
            f"{draft.spec_title} (v0.{draft.version})\n"
            f"{total} questions waiting for your input.\n\n"
            f"Answer in the dashboard:\n"
            f"{url}/dashboard/#drafts\n\n"
            f"\u26a0\ufe0f Replies here are not captured \u2014 use the dashboard."
        )
        notify(msg)

    except Exception:
        pass
