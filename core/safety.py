"""
core.safety
===========
⚠️ 안전-critical 모듈입니다.

위기 상황에서 사용되는 '안전 계획(safety plan)' 데이터만 격리해서 다룹니다.
CrisisInterceptor(guardrail_interceptor.py)가 위기를 탐지했을 때 참조/노출되는
데이터가 바로 이 모듈을 거칩니다.

원칙:
- 이 파일에는 생산성/편의 기능(퀘스트, 브레인덤프 등) 코드를 절대 추가하지 않습니다.
- 스키마나 로직을 바꿀 때는 반드시 회귀 테스트(최소 저장→조회 왕복 확인)를 거칩니다.
"""
import json
from typing import Optional

from .db import connection_scope


class SafePlanDict(dict):
    """KeyError 방지용 안전 Dictionary 클래스 (존재하지 않는 키 접근 시 기본값 반환)."""

    def __getitem__(self, item):
        if item not in self:
            if item in ('coping_strategies', 'emergency_contacts'):
                return []
            return ""
        val = super().__getitem__(item)
        if val is None:
            return ""
        return val


class SafetyPlanManager:
    """안전 계획(safety_plan) 테이블 전용 CRUD. 다른 기능과 절대 섞지 않습니다."""

    def __init__(self, db_path: str = "cbt_memory.db"):
        self.db_path = db_path
        self._init_table()

    def _conn(self):
        # connection_scope: with 블록 종료 시 커밋(예외 시 롤백) + 커넥션 close까지
        # 보장한다. 호출부(with self._conn() as conn: ...)는 그대로 둬도 된다.
        return connection_scope(self.db_path)

    def _init_table(self):
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS safety_plan (
                    user_id TEXT PRIMARY KEY,
                    warning_signals TEXT,
                    coping_strategies TEXT NOT NULL,
                    emergency_contacts TEXT NOT NULL,
                    safe_environment TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # 기존 테이블 컬럼 자동 마이그레이션
            try:
                cursor.execute("PRAGMA table_info(safety_plan)")
                cols = [row[1] for row in cursor.fetchall()]
                if cols and "warning_signals" not in cols:
                    cursor.execute("ALTER TABLE safety_plan ADD COLUMN warning_signals TEXT")
                if cols and "safe_environment" not in cols:
                    cursor.execute("ALTER TABLE safety_plan ADD COLUMN safe_environment TEXT")
            except Exception:
                pass
            conn.commit()

    def save_safety_plan(
        self,
        user_id: str = "default_user",
        warning_signals: str = "",
        coping_strategies: Optional[list] = None,
        emergency_contacts: Optional[list] = None,
        safe_environment: str = "",
        **kwargs
    ) -> None:
        """UI 모달에서 입력한 안전 계획을 저장(upsert)합니다."""
        strategies_json = json.dumps(coping_strategies or [], ensure_ascii=False)
        contacts_json = json.dumps(emergency_contacts or [], ensure_ascii=False)
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO safety_plan (user_id, warning_signals, coping_strategies, emergency_contacts, safe_environment)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    warning_signals = excluded.warning_signals,
                    coping_strategies = excluded.coping_strategies,
                    emergency_contacts = excluded.emergency_contacts,
                    safe_environment = excluded.safe_environment,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, warning_signals, strategies_json, contacts_json, safe_environment))
            conn.commit()

    def get_safety_plan(self, user_id: str = "default_user", **kwargs) -> SafePlanDict:
        """위기 키워드 감지 시 또는 UI 모달 호출 시 안전 계획 데이터 반환."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM safety_plan WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()

            if row:
                keys = row.keys()

                def get_val(key, default):
                    return row[key] if key in keys and row[key] is not None else default

                coping_raw = get_val("coping_strategies", "[]")
                contacts_raw = get_val("emergency_contacts", "[]")

                try:
                    coping = json.loads(coping_raw) if isinstance(coping_raw, str) else coping_raw
                except Exception:
                    coping = ["심호흡 3회 하기", "조용한 곳에서 물 한 잔 마시기"]

                try:
                    contacts = json.loads(contacts_raw) if isinstance(contacts_raw, str) else contacts_raw
                except Exception:
                    contacts = [
                        {"name": "자살예방상담전화", "phone": "109"},
                        {"name": "정신건강위기상담전화", "phone": "1577-0199"}
                    ]

                data = {
                    "user_id": row["user_id"],
                    "warning_signals": get_val("warning_signals", "갑작스러운 무기력감, 불안감 증가"),
                    "coping_strategies": coping,
                    "emergency_contacts": contacts,
                    "safe_environment": get_val("safe_environment", "주변 환경 정돈 및 밝은 장소로 이동"),
                    "updated_at": get_val("updated_at", None)
                }
            else:
                data = {
                    "user_id": user_id,
                    "warning_signals": "갑작스러운 무기력감, 불안감 증가",
                    "coping_strategies": ["심호흡 3회 하기", "조용한 곳에서 물 한 잔 마시기"],
                    "emergency_contacts": [
                        {"name": "자살예방상담전화", "phone": "109"},
                        {"name": "정신건강위기상담전화", "phone": "1577-0199"}
                    ],
                    "safe_environment": "주변 환경 정돈 및 밝은 장소로 이동",
                    "updated_at": None
                }
            return SafePlanDict(data)
