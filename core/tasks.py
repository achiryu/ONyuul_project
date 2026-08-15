"""
core.tasks
==========
마감일이 있는 "진짜 할 일"을 다루는 전용 모듈입니다.

core.mental_care의 quests(마이크로 퀘스트)와는 의도적으로 분리했습니다:
- quests: 행동 활성화 목적의 부담 없는 작은 미션. 마감 개념이 없다.
- tasks(이 모듈): 마감일/우선순위가 있는, 실제로 처리해야 하는 일.

두 개념을 한 테이블에 섞으면 "부담 없이 시도해볼 것"과 "꼭 해야 하는 일"이
심리적으로 뒤섞여 오히려 부담이 커질 수 있다는 이전 논의를 그대로 반영했다.

원칙: core.reminders와 마찬가지로 안전-critical 로직을 참조/우회하지 않고,
되돌리기 어려운 시스템 동작을 추가하지 않는다.
"""
import datetime
from typing import Optional, Dict, List, Any

from .db import connection_scope


class TaskManager:
    """tasks 테이블 전용 CRUD."""

    VALID_PRIORITIES = ("low", "medium", "high")

    def __init__(self, db_path: str = "cbt_memory.db"):
        self.db_path = db_path
        self._init_table()

    def _conn(self):
        return connection_scope(self.db_path)

    def _init_table(self):
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT DEFAULT 'default_user',
                    title TEXT NOT NULL,
                    due_date TEXT,
                    priority TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')

    def create_task(
        self,
        title: str,
        due_date: Optional[str] = None,
        priority: str = "medium",
        user_id: str = "default_user",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        할 일을 등록한다.

        due_date: "YYYY-MM-DD" 형식 (마감 없는 할 일이면 생략 가능).
        priority: "low" | "medium" | "high".
        """
        if not title or not title.strip():
            return {"status": "error", "message": "할 일 제목이 비어 있습니다."}
        if priority not in self.VALID_PRIORITIES:
            priority = "medium"
        if due_date:
            try:
                datetime.datetime.strptime(due_date, "%Y-%m-%d")
            except (ValueError, TypeError):
                return {"status": "error", "message": "due_date 형식이 올바르지 않습니다 (예: '2026-08-20')."}

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (user_id, title, due_date, priority, status)
                VALUES (?, ?, ?, ?, 'pending')
            ''', (user_id, title.strip(), due_date, priority))
            task_id = cursor.lastrowid

        return {"status": "success", "task_id": task_id, "title": title.strip()}

    def complete_task(
        self,
        task_id: Optional[int] = None,
        title: str = "",
        user_id: str = "default_user",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        할 일을 완료 처리한다. task_id가 주어지면 그걸로, 아니면 title로 매칭을
        시도하고(정확히 일치 안 하면 가장 최근 PENDING으로 폴백), 아무것도 없으면
        가장 최근 PENDING 항목을 완료 처리한다. 완료할 대상이 실제로 없으면
        정직하게 실패를 반환한다 (무조건 성공했다고 하지 않음).
        """
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            cursor = conn.cursor()
            updated = False

            if task_id is not None:
                cursor.execute(
                    "UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ? AND status = 'pending'",
                    (now_str, task_id),
                )
                updated = cursor.rowcount > 0
            elif title:
                cursor.execute(
                    "UPDATE tasks SET status = 'completed', completed_at = ? "
                    "WHERE title = ? AND status = 'pending' AND (user_id = ? OR user_id IS NULL)",
                    (now_str, title, user_id),
                )
                updated = cursor.rowcount > 0

            if not updated:
                cursor.execute(
                    "UPDATE tasks SET status = 'completed', completed_at = ? "
                    "WHERE id = (SELECT id FROM tasks WHERE status = 'pending' ORDER BY id DESC LIMIT 1)",
                    (now_str,),
                )
                updated = cursor.rowcount > 0

        if not updated:
            return {"status": "error", "message": "완료 처리할 할 일이 없습니다."}
        return {"status": "success"}

    def get_pending_tasks(self, user_id: str = "default_user", limit: int = 30, **kwargs) -> List[Dict[str, Any]]:
        """마감일 빠른 순 → 우선순위 높은 순으로 정렬된 미완료 할 일 목록."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'pending'
                ORDER BY
                    (due_date IS NULL) ASC,
                    due_date ASC,
                    CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END ASC
                LIMIT ?
            ''', (user_id, limit))
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_overdue_tasks(self, user_id: str = "default_user", **kwargs) -> List[Dict[str, Any]]:
        """마감일이 지났는데 아직 완료 안 된 할 일들."""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'pending' AND due_date IS NOT NULL AND due_date < ?
                ORDER BY due_date ASC
            ''', (user_id, today))
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def delete_task(self, task_id: int, **kwargs) -> Dict[str, Any]:
        """할 일 완전 삭제 (GUI 수동 관리 전용 — AI 도구로는 노출하지 않는다)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            deleted = cursor.rowcount > 0
        if not deleted:
            return {"status": "error", "message": f"할 일(id={task_id})을 찾지 못했습니다."}
        return {"status": "success", "task_id": task_id}
