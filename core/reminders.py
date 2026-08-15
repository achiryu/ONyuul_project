"""
core.reminders
===============
복약 알림 + 일반 일정 알림을 다루는 전용 모듈입니다.

core.mental_care의 설계 원칙("일정/생산성 기능은 여기 넣지 않는다")을 따라
별도로 분리했습니다. 다만 productivity 패키지는 DB/네트워크에 직접 접근하지
않는 순수 함수만 두기로 되어 있어서(productivity_manager.py 상단 원칙 참고),
알림처럼 영속 저장이 필요한 기능은 productivity가 아니라 여기(core) 쪽에
둡니다 — core는 "DB가 필요한 각 도메인별 매니저"들이 모이는 곳이라는 원래
구조(safety.py, mental_care.py)에 맞춥니다.

원칙:
- 이 모듈은 안전-critical 로직(core.safety)이나 CrisisInterceptor를 참조/우회하지 않습니다.
- 되돌리기 어려운 시스템 동작(프로그램 실행 등)은 여기 추가하지 않습니다 — 순수하게
  "언제 무엇을 상기시킬지"만 담당합니다. 실제로 사용자에게 알리는 방식(음성으로
  말하기, 배너 표시 등)은 jarvis_ui.py가 책임집니다.
"""
import datetime
from typing import Optional, Dict, List, Any

from .db import connection_scope


class ReminderManager:
    """reminders 테이블 전용 CRUD. 복약(medication)과 일반 일정(schedule) 두 종류를 다룬다."""

    VALID_KINDS = ("medication", "schedule")
    VALID_REPEATS = (None, "daily", "weekly")

    def __init__(self, db_path: str = "cbt_memory.db"):
        self.db_path = db_path
        self._init_table()

    def _conn(self):
        return connection_scope(self.db_path)

    def _init_table(self):
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT DEFAULT 'default_user',
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    remind_at TIMESTAMP NOT NULL,
                    repeat_rule TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_notified_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def create_reminder(
        self,
        title: str,
        remind_at: str,
        kind: str = "schedule",
        repeat_rule: Optional[str] = None,
        user_id: str = "default_user",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        알림을 등록한다.

        remind_at: "YYYY-MM-DD HH:MM" 형식의 문자열 (예: "2026-08-14 20:00").
        kind: "medication"(복약) 또는 "schedule"(일반 일정).
        repeat_rule: None(1회) | "daily"(매일) | "weekly"(매주).
        """
        if kind not in self.VALID_KINDS:
            kind = "schedule"
        if repeat_rule not in self.VALID_REPEATS:
            repeat_rule = None

        try:
            # 형식 검증 — 여기서 걸러야 이후 비교 쿼리에서 조용히 안 걸리는 사고를 막는다.
            datetime.datetime.strptime(remind_at, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return {"status": "error", "message": "remind_at 형식이 올바르지 않습니다 (예: '2026-08-14 20:00')."}

        if not title or not title.strip():
            return {"status": "error", "message": "알림 제목이 비어 있습니다."}

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO reminders (user_id, kind, title, remind_at, repeat_rule, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            ''', (user_id, kind, title.strip(), remind_at, repeat_rule))
            reminder_id = cursor.lastrowid

        return {"status": "success", "reminder_id": reminder_id, "title": title.strip(), "remind_at": remind_at}

    def get_due_reminders(self, user_id: str = "default_user", **kwargs) -> List[Dict[str, Any]]:
        """지금 시점 기준으로 알려야 할(마감이 지났고, 아직 이번 회차로는 안 알린) 알림들."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM reminders
                WHERE user_id = ? AND is_active = 1 AND remind_at <= ?
                  AND (last_notified_at IS NULL OR last_notified_at < remind_at)
                ORDER BY remind_at ASC
            ''', (user_id, now_str))
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def mark_reminder_notified(self, reminder_id: int, **kwargs) -> Dict[str, Any]:
        """
        알림을 실제로 전달한 뒤 호출한다. 반복 규칙이 있으면 다음 회차로 remind_at을
        전진시키고, 1회성이면 is_active를 꺼서 다시 안 뜨게 한다.
        """
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT remind_at, repeat_rule FROM reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "message": "해당 알림을 찾지 못했습니다."}

            remind_at, repeat_rule = row["remind_at"], row["repeat_rule"]

            if repeat_rule in ("daily", "weekly"):
                try:
                    dt = datetime.datetime.strptime(remind_at, "%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    dt = datetime.datetime.now()
                delta = datetime.timedelta(days=1 if repeat_rule == "daily" else 7)
                next_dt = dt + delta
                # 놓친 회차가 여러 번 쌓여 있었다면(앱이 오래 꺼져 있었던 경우 등)
                # 과거 시각에 계속 멈춰있지 않도록 현재 이후로 밀어준다.
                while next_dt <= datetime.datetime.now():
                    next_dt += delta
                cursor.execute(
                    "UPDATE reminders SET last_notified_at = ?, remind_at = ? WHERE id = ?",
                    (now_str, next_dt.strftime("%Y-%m-%d %H:%M"), reminder_id),
                )
            else:
                cursor.execute(
                    "UPDATE reminders SET last_notified_at = ?, is_active = 0 WHERE id = ?",
                    (now_str, reminder_id),
                )

        return {"status": "success", "reminder_id": reminder_id}

    def get_upcoming_reminders(self, user_id: str = "default_user", limit: int = 20, **kwargs) -> List[Dict[str, Any]]:
        """앞으로 다가올(활성 상태인) 알림 목록. GUI 목록/음성 조회용."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM reminders
                WHERE user_id = ? AND is_active = 1
                ORDER BY remind_at ASC
                LIMIT ?
            ''', (user_id, limit))
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def delete_reminder(self, reminder_id: int, **kwargs) -> Dict[str, Any]:
        """알림 완전 삭제 (GUI 수동 관리 전용 — AI 도구로는 노출하지 않는다)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            deleted = cursor.rowcount > 0
        if not deleted:
            return {"status": "error", "message": f"알림(id={reminder_id})을 찾지 못했습니다."}
        return {"status": "success", "reminder_id": reminder_id}

    def toggle_reminder(self, reminder_id: int, is_active: bool, **kwargs) -> Dict[str, Any]:
        """알림 켜기/끄기 (삭제하지 않고 잠시 비활성화하고 싶을 때)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reminders SET is_active = ? WHERE id = ?", (1 if is_active else 0, reminder_id))
        return {"status": "success", "reminder_id": reminder_id, "is_active": is_active}
