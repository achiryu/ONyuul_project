"""
core.mental_care
=================
안전 계획(core.safety)을 제외한 나머지 CBT/멘탈케어 기능을 다룹니다:
사고 기록(thought records), 퀘스트, 긍정 앵커, 기분/수면 로그, 그라운딩 세션 로그,
일반 메모리 저장/검색.

생산성 기능(일정, 브레인덤프, 시스템 제어 등)은 여기 넣지 않고 productivity 패키지로
분리합니다 — 이 모듈은 어디까지나 '멘탈케어' 범위로 한정합니다.
"""
import json
from typing import Optional, Dict, List, Any, Tuple

from .db import get_connection


class AnchorRow(tuple):
    """3-튜플 호환 클래스 (for ts, content, emotion_tag in rows 언패킹 및 Dict 키 접근 동시 지원)."""

    def __new__(cls, ts, content, emotion_tag="✨"):
        return super().__new__(cls, (ts or "", content or "", emotion_tag or "✨"))

    def __getitem__(self, item):
        if isinstance(item, str):
            item_lower = item.lower()
            if item_lower in ('ts', 'created_at', 'timestamp', 'date'):
                return super().__getitem__(0)
            elif item_lower == 'content':
                return super().__getitem__(1)
            elif item_lower in ('emotion_tag', 'tag', 'emotion'):
                return super().__getitem__(2)
            return None
        return super().__getitem__(item)

    def get(self, key, default=None):
        try:
            val = self[key]
            return val if val is not None else default
        except (IndexError, TypeError):
            return default


class MentalCareManager:
    def __init__(self, db_path: str = "cbt_memory.db"):
        self.db_path = db_path
        self._init_tables()

    def _conn(self):
        return get_connection(self.db_path)

    def _init_tables(self):
        with self._conn() as conn:
            cursor = conn.cursor()

            # 🧠 Thought Records 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS thought_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    automatic_thought TEXT NOT NULL,
                    cognitive_distortion TEXT,
                    alternative_thought TEXT NOT NULL,
                    emotion_before INTEGER CHECK(emotion_before BETWEEN 0 AND 100),
                    emotion_after INTEGER CHECK(emotion_after BETWEEN 0 AND 100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 🌟 Positive Anchors 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positive_anchors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    content TEXT,
                    emotion_tag TEXT DEFAULT '✨',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 🎯 Quests 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    title TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 🔍 Memories 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    content TEXT,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 😴 Mood / Sleep 로그 테이블 (신규)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mood_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    mood_score REAL,
                    sleep_hours REAL,
                    emotion_keywords TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 🧘 그라운딩 세션 로그 테이블 (신규)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS grounding_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    technique_type TEXT,
                    feedback TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 📔 자유 일기 테이블 (AI 개입/분류 없이 순수하게 사용자가 직접 쓰는 글)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 기존 테이블 컬럼 자동 마이그레이션
            try:
                cursor.execute("PRAGMA table_info(memories)")
                cols = [row[1] for row in cursor.fetchall()]
                if cols and "content" not in cols:
                    cursor.execute("ALTER TABLE memories ADD COLUMN content TEXT")
                if cols and "category" not in cols:
                    cursor.execute("ALTER TABLE memories ADD COLUMN category TEXT")
            except Exception:
                pass

            try:
                cursor.execute("PRAGMA table_info(positive_anchors)")
                cols = [row[1] for row in cursor.fetchall()]
                if cols and "emotion_tag" not in cols:
                    cursor.execute("ALTER TABLE positive_anchors ADD COLUMN emotion_tag TEXT DEFAULT '✨'")
            except Exception:
                pass

            conn.commit()

    # ==========================================
    # 🧠 Thought Record API
    # ==========================================
    def add_thought_record(
        self,
        user_id: str = "default_user",
        situation: str = "",
        automatic_thought: str = "",
        alternative_thought: str = "",
        emotion_before: int = 50,
        emotion_after: int = 50,
        cognitive_distortion: Optional[str] = None,
        **kwargs
    ) -> int:
        """인지 재구성 기록 저장."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO thought_records
                (user_id, situation, automatic_thought, cognitive_distortion, alternative_thought, emotion_before, emotion_after)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, situation, automatic_thought, cognitive_distortion, alternative_thought, emotion_before, emotion_after))
            conn.commit()
            return cursor.lastrowid

    def get_user_thought_history(self, user_id: str = "default_user", limit: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """사용자의 인지 재구성 이력 조회."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT *, (emotion_before - emotion_after) AS emotion_relief
                FROM thought_records
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (user_id, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # ==========================================
    # 🎯 Quest API (생성, 완료 및 조회)
    # ==========================================
    def create_micro_quest(self, quest_title: str, user_id: str = "default_user", **kwargs) -> Dict[str, Any]:
        """마이크로 퀘스트 신규 생성 및 DB 저장."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO quests (user_id, title, status) VALUES (?, ?, 'pending')",
                (user_id, quest_title)
            )
            conn.commit()
            return {"status": "success", "quest_id": cursor.lastrowid, "title": quest_title}

    def add_quest(self, title: str, user_id: str = "default_user", status: str = "pending", **kwargs) -> int:
        """새 퀘스트 추가 (호환용)."""
        res = self.create_micro_quest(quest_title=title, user_id=user_id, **kwargs)
        return res["quest_id"]

    def complete_micro_quest(self, quest_title: str = "", user_id: str = "default_user", **kwargs) -> Dict[str, Any]:
        """마이크로 퀘스트 완료 처리."""
        with self._conn() as conn:
            cursor = conn.cursor()
            if quest_title:
                cursor.execute(
                    "UPDATE quests SET status = 'completed' WHERE title = ? AND (user_id = ? OR user_id IS NULL)",
                    (quest_title, user_id)
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO quests (user_id, title, status) VALUES (?, ?, 'completed')",
                        (user_id, quest_title)
                    )
            else:
                cursor.execute(
                    "UPDATE quests SET status = 'completed' WHERE id = (SELECT id FROM quests WHERE status = 'pending' ORDER BY id DESC LIMIT 1)"
                )
            conn.commit()
            return {"status": "success", "message": f"Micro quest '{quest_title}' completed successfully."}

    def complete_quest(self, quest_title: str = "", user_id: str = "default_user", quest_id: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        """일반 퀘스트 완료 처리 호환."""
        return self.complete_micro_quest(quest_title=quest_title, user_id=user_id, **kwargs)

    def get_quest_stats(self, user_id: Optional[str] = None, **kwargs) -> Tuple[int, int]:
        """퀘스트 통계 데이터 조회."""
        with self._conn() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute('SELECT status, COUNT(*) as count FROM quests WHERE user_id = ? GROUP BY status', (user_id,))
            else:
                cursor.execute('SELECT status, COUNT(*) as count FROM quests GROUP BY status')
            rows = cursor.fetchall()
            completed = 0
            total = 0
            for row in rows:
                cnt = row["count"]
                total += cnt
                if str(row["status"]).lower() in ['completed', 'done', '완료']:
                    completed += cnt
            return (completed, total)

    def get_pending_quests(self, user_id: str = "default_user", **kwargs) -> str:
        """대기 중인 퀘스트 목록을 문자열로 반환 (AI 음성 응답 및 함수호출용)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT title FROM quests WHERE status = 'pending' AND (user_id = ? OR user_id IS NULL) ORDER BY id DESC",
                (user_id,)
            )
            titles = [row["title"] for row in cursor.fetchall()]
        if not titles:
            return "현재 대기 중인 퀘스트가 없습니다."
        return "대기 중인 퀘스트: " + ", ".join(titles)

    def complete_quest_by_id(self, quest_id: int, **kwargs) -> Dict[str, Any]:
        """ID로 특정 퀘스트를 완료 처리 (퀘스트 일지 수동 완료 버튼용)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE quests SET status = 'completed' WHERE id = ?", (quest_id,))
            conn.commit()
            return {"status": "success", "quest_id": quest_id}

    def delete_quest(self, quest_id: int, **kwargs) -> Dict[str, Any]:
        """
        ID로 특정 퀘스트를 완전히 삭제 (퀘스트 일지 수동 삭제 버튼용).

        AI 도구 호출로는 절대 노출하지 않는다 — jarvis_ui.py의 GUI 버튼에서만
        직접 호출되어야 한다. 위기 문구가 잘못 분류돼 퀘스트로 저장되는 등의
        사고를 사용자가 직접 정리할 수 있게 하기 위한 수동 관리 기능이다.
        """
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM quests WHERE id = ?", (quest_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
        if not deleted:
            return {"status": "error", "message": f"퀘스트(id={quest_id})를 찾지 못했습니다."}
        return {"status": "success", "quest_id": quest_id}

    def get_all_quests_raw(self, user_id: Optional[str] = None, limit: Optional[int] = None, **kwargs) -> List[Dict[str, Any]]:
        """전체 퀘스트 데이터 조회."""
        with self._conn() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM quests'
            params: List[Any] = []
            if user_id:
                query += ' WHERE user_id = ?'
                params.append(user_id)
            query += ' ORDER BY id DESC'
            if limit:
                query += ' LIMIT ?'
                params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ==========================================
    # 🌟 Positive Anchors API
    # ==========================================
    def get_positive_anchors_raw(self, user_id: Optional[str] = None, limit: Optional[int] = None, **kwargs) -> List[AnchorRow]:
        """긍정 앵커 데이터 조회 (원본 행)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM positive_anchors'
            params: List[Any] = []
            if user_id:
                query += ' WHERE user_id = ?'
                params.append(user_id)
            query += ' ORDER BY id DESC'
            if limit:
                query += ' LIMIT ?'
                params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                keys = row.keys()
                ts = row["created_at"] if "created_at" in keys else ""
                content = row["content"] if "content" in keys else ""
                emotion_tag = row["emotion_tag"] if "emotion_tag" in keys else "✨"
                results.append(AnchorRow(ts, content, emotion_tag))

            return results

    def save_positive_anchor(self, content: str, emotion_tag: str = "✨", user_id: str = "default_user", **kwargs) -> Dict[str, Any]:
        """긍정 앵커(좋았던 순간) 저장."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO positive_anchors (user_id, content, emotion_tag) VALUES (?, ?, ?)",
                (user_id, content, emotion_tag)
            )
            conn.commit()
            return {"status": "success", "anchor_id": cursor.lastrowid}

    def get_positive_anchors(self, limit: int = 10, user_id: Optional[str] = None, **kwargs) -> str:
        """AI 음성 응답용: 저장된 긍정 앵커를 사람이 읽기 좋은 문자열로 반환."""
        rows = self.get_positive_anchors_raw(user_id=user_id, limit=limit)
        if not rows:
            return "아직 저장된 긍정적인 기억이 없습니다."
        lines = [f"{r['emotion_tag']} {r['content']}" for r in rows]
        return "떠올려볼 긍정적인 기억들: " + " / ".join(lines)

    # ==========================================
    # 😴 Mood / Sleep API
    # ==========================================
    def log_mood_and_sleep(
        self,
        mood_score: Any = "",
        sleep_hours: Any = "",
        emotion_keywords: str = "",
        notes: str = "",
        user_id: str = "default_user",
        **kwargs
    ) -> Dict[str, Any]:
        """오늘의 기분/수면 상태 기록. mood_score/sleep_hours는 음성 함수호출 특성상
        문자열로 들어올 수 있어 안전하게 숫자로 변환을 시도합니다."""
        def _to_float(val):
            try:
                return float(val) if val not in (None, "") else None
            except (TypeError, ValueError):
                return None

        mood_val = _to_float(mood_score)
        sleep_val = _to_float(sleep_hours)

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO mood_log (user_id, mood_score, sleep_hours, emotion_keywords, notes) VALUES (?, ?, ?, ?, ?)",
                (user_id, mood_val, sleep_val, emotion_keywords, notes)
            )
            conn.commit()
            return {"status": "success", "message": "오늘의 기분과 수면 상태를 기록했습니다."}

    def get_mood_history(self, days: int = 7, user_id: str = "default_user", **kwargs) -> str:
        """최근 N일간 기분/수면 기록을 문자열로 요약."""
        try:
            days_int = int(days)
        except (TypeError, ValueError):
            days_int = 7

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT mood_score, sleep_hours, emotion_keywords, notes, created_at FROM mood_log "
                "WHERE user_id = ? AND created_at >= datetime('now', ?) ORDER BY created_at DESC",
                (user_id, f'-{days_int} days')
            )
            rows = cursor.fetchall()

        if not rows:
            return f"최근 {days_int}일간 기록된 기분/수면 데이터가 없습니다."

        lines = []
        for r in rows:
            mood = r["mood_score"] if r["mood_score"] is not None else "?"
            sleep = r["sleep_hours"] if r["sleep_hours"] is not None else "?"
            kw = f" ({r['emotion_keywords']})" if r["emotion_keywords"] else ""
            lines.append(f"{r['created_at']}: 기분 {mood}, 수면 {sleep}시간{kw}")
        return f"최근 {days_int}일간 기록:\n" + "\n".join(lines)

    # ==========================================
    # 🧘 Grounding Session API
    # ==========================================
    def log_grounding_session(self, technique_type: str, feedback: str = "", user_id: str = "default_user", **kwargs) -> Dict[str, Any]:
        """그라운딩(호흡/오감 자극 등) 세션 수행 기록."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO grounding_sessions (user_id, technique_type, feedback) VALUES (?, ?, ?)",
                (user_id, technique_type, feedback)
            )
            conn.commit()
            return {"status": "success", "session_id": cursor.lastrowid}

    # ==========================================
    # 🔍 Memories API
    # ==========================================
    def save_memory(self, text: str, category: str = "cbt_context", user_id: str = "default_user", **kwargs) -> Dict[str, Any]:
        """일반 대화/맥락 메모리 저장 (검색은 search_relevant_memories로)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO memories (user_id, content, category) VALUES (?, ?, ?)",
                (user_id, text, category)
            )
            conn.commit()
            return {"status": "success", "memory_id": cursor.lastrowid}

    def search_relevant_memories(self, query: str, n_results: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """기억/상담 기록 키워드 검색."""
        with self._conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA table_info(memories)")
                cols = [row[1] for row in cursor.fetchall()]

                if not cols:
                    return []

                search_col = 'content' if 'content' in cols else cols[0]
                keywords = query.split()

                if keywords:
                    sql_conditions = " OR ".join([f"{search_col} LIKE ?"] * len(keywords))
                    params = [f"%{kw}%" for kw in keywords]
                    cursor.execute(f'SELECT * FROM memories WHERE {sql_conditions} LIMIT ?', (*params, n_results))
                else:
                    cursor.execute('SELECT * FROM memories LIMIT ?', (n_results,))

                return [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                print(f"Memory search error fallback: {e}")
                return []

    def save_journal_entry(self, content: str, user_id: str = "default_user", **kwargs) -> Dict[str, Any]:
        """
        자유 일기 저장. AI 분류/개입 없이 사용자가 직접 쓴 글을 그대로 저장한다
        (브레인덤프나 사고기록과 달리, 이 메서드는 도구 호출로 노출되지 않고
        GUI에서 직접 호출된다).
        """
        if not content or not content.strip():
            return {"status": "error", "message": "일기 내용이 비어 있습니다."}
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO journal_entries (user_id, content) VALUES (?, ?)",
                (user_id, content.strip()),
            )
            entry_id = cursor.lastrowid
        return {"status": "success", "entry_id": entry_id}

    def get_journal_entries(self, user_id: str = "default_user", limit: int = 30, **kwargs) -> List[Dict[str, Any]]:
        """최신순 자유 일기 목록."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM journal_entries WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def delete_journal_entry(self, entry_id: int, **kwargs) -> Dict[str, Any]:
        """일기 삭제 (GUI 수동 관리 전용)."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
            deleted = cursor.rowcount > 0
        if not deleted:
            return {"status": "error", "message": f"일기(id={entry_id})를 찾지 못했습니다."}
        return {"status": "success", "entry_id": entry_id}
