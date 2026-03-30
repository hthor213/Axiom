"""ResultOpsMixin: result, draft review, and spec review database operations."""

from __future__ import annotations

import json
from typing import Optional

from .db_models import Result, DraftReview, SpecReview
from .db_converters import row_to_result, row_to_draft_review, row_to_spec_review


class ResultOpsMixin:
    """Mixin providing result, draft review, and spec review operations.

    Relies on _connect() and _dict_cursor() from TaskOpsMixin.
    """

    # ---- Result operations ----

    def save_result(self, result: Result) -> Result:
        """Save a task result."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO results (task_id, session_id, branch_name,
                       commit_sha, diff_summary, test_passed, test_failed,
                       test_output, adversarial_verdict, adversarial_report,
                       harness_check, approved, project_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (result.task_id, result.session_id, result.branch_name,
                     result.commit_sha, result.diff_summary, result.test_passed,
                     result.test_failed, result.test_output,
                     result.adversarial_verdict,
                     json.dumps(result.adversarial_report) if result.adversarial_report else None,
                     json.dumps(result.harness_check) if result.harness_check else None,
                     result.approved, result.project_id),
                )
                result.id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        return result

    def get_result(self, result_id: int) -> Optional[Result]:
        """Get a single result by ID."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM results WHERE id=%s", (result_id,))
                row = cur.fetchone()
                return row_to_result(dict(row)) if row else None
        finally:
            conn.close()

    def get_results(self, task_id: Optional[int] = None,
                    pending_only: bool = False,
                    limit: int = 50) -> list[Result]:
        """Get results, optionally filtered."""
        conn = self._connect()
        try:
            sql = "SELECT * FROM results"
            params: list = []
            conditions = []
            if task_id is not None:
                conditions.append("task_id=%s")
                params.append(task_id)
            if pending_only:
                conditions.append("approved IS NULL")
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY id DESC LIMIT %s"
            params.append(limit)
            with self._dict_cursor(conn) as cur:
                cur.execute(sql, params)
                return [row_to_result(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    def approve_result(self, result_id: int, approved: bool, reject_reason: str = None) -> bool:
        """Approve or reject a result. Rejection can include a reason."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE results SET approved=%s, approved_at=NOW(), reject_reason=%s WHERE id=%s",
                    (approved, reject_reason if not approved else None, result_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    # ---- Draft review operations ----

    def create_draft_review(self, draft: DraftReview) -> DraftReview:
        """Create a new draft review record."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO draft_reviews (task_id, spec_number, spec_title, version,
                       original_spec, refined_spec, questions, answers, gemini_feedback, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (draft.task_id, draft.spec_number, draft.spec_title, draft.version,
                     draft.original_spec, draft.refined_spec,
                     json.dumps(draft.questions) if draft.questions else None,
                     json.dumps(draft.answers) if draft.answers else None,
                     draft.gemini_feedback, draft.status),
                )
                draft.id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        return draft

    def get_draft_reviews(self, status: Optional[str] = None, limit: int = 50) -> list[DraftReview]:
        """Get draft reviews, optionally filtered by status."""
        conn = self._connect()
        try:
            sql = "SELECT * FROM draft_reviews"
            params: list = []
            if status:
                sql += " WHERE status=%s"
                params.append(status)
            sql += " ORDER BY id DESC LIMIT %s"
            params.append(limit)
            with self._dict_cursor(conn) as cur:
                cur.execute(sql, params)
                return [row_to_draft_review(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_draft_review(self, draft_id: int) -> Optional[DraftReview]:
        """Get a single draft review by ID."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM draft_reviews WHERE id=%s", (draft_id,))
                row = cur.fetchone()
                return row_to_draft_review(dict(row)) if row else None
        finally:
            conn.close()

    def update_draft_review(self, draft_id: int, **kwargs) -> bool:
        """Update draft review fields."""
        conn = self._connect()
        try:
            if not kwargs:
                return False
            for key in ("questions", "answers"):
                if key in kwargs and kwargs[key] is not None and not isinstance(kwargs[key], str):
                    kwargs[key] = json.dumps(kwargs[key])
            sets = [f"{k}=%s" for k in kwargs]
            vals = list(kwargs.values()) + [draft_id]
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE draft_reviews SET {', '.join(sets)} WHERE id=%s",
                    vals,
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_latest_draft_review(self, spec_number: str) -> Optional[DraftReview]:
        """Get the most recent draft review for a spec (highest version)."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute(
                    "SELECT * FROM draft_reviews WHERE spec_number=%s ORDER BY version DESC LIMIT 1",
                    (spec_number,),
                )
                row = cur.fetchone()
                return row_to_draft_review(dict(row)) if row else None
        finally:
            conn.close()

    def get_latest_draft_version(self, spec_number: str) -> int:
        """Get the highest version number for a spec's draft reviews."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(version) FROM draft_reviews WHERE spec_number=%s",
                    (spec_number,),
                )
                row = cur.fetchone()
                return row[0] or 0
        finally:
            conn.close()

    # ---- Spec review operations (interactive GPT mentor + Claude editor) ----

    def create_spec_review(self, review: SpecReview) -> SpecReview:
        """Create a new spec review record."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO spec_reviews (spec_number, version, original_content,
                       user_modifications, gpt_feedback, edited_content, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (review.spec_number, review.version, review.original_content,
                     review.user_modifications, review.gpt_feedback,
                     review.edited_content, review.status),
                )
                review.id = cur.fetchone()[0]
            conn.commit()
            return review
        finally:
            conn.close()

    def get_spec_review(self, review_id: int) -> Optional[SpecReview]:
        """Get a spec review by ID."""
        conn = self._connect()
        try:
            with self._dict_cursor(conn) as cur:
                cur.execute("SELECT * FROM spec_reviews WHERE id=%s", (review_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return row_to_spec_review(dict(row))
        finally:
            conn.close()

    def update_spec_review(self, review_id: int, **kwargs) -> None:
        """Update spec review fields."""
        if not kwargs:
            return
        conn = self._connect()
        try:
            sets = [f"{k}=%s" for k in kwargs]
            vals = list(kwargs.values()) + [review_id]
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE spec_reviews SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s",
                    vals,
                )
            conn.commit()
        finally:
            conn.close()
