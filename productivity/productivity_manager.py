"""
productivity.productivity_manager
==================================
생산성 기능(데일리 브리핑, 향후 브레인덤프, 시스템 제어 등)을 위한 모듈입니다.

⚠️ 설계 원칙 (지난 논의 반영):
1. 여기 들어갈 기능은 core.safety의 CrisisInterceptor 경로를 절대 우회하지 않습니다.
   브레인덤프처럼 사용자 발화를 분류하는 기능은 반드시 기존 위기 감지 파이프라인을
   먼저 통과한 텍스트만 입력으로 받아야 합니다.
2. 시스템 제어(앱 실행, 볼륨/밝기 조절 등)는 새 실행 경로를 만들지 말고, 가능하면
   jarvis_ui.py의 기존 `open_program`(확인 절차 포함) 패턴을 확장해서 구현합니다.
3. 되돌리기 어려운 동작(파일 삭제, 프로그램 강제 종료 등)은 이 모듈에 추가하지 않습니다.
4. 이 모듈은 DB/네트워크에 직접 접근하지 않습니다. 데이터 조회는 jarvis_ui.py가
   기존 memory_db / get_current_weather 등을 통해 가져오고, 이 모듈은 순수 조합/
   가공 로직만 담당합니다 (테스트하기 쉽고, core 모듈과의 결합을 최소화하기 위함).

현재 구현된 기능: 데일리 브리핑 텍스트 조합(build_daily_briefing_text),
브레인덤프 1차 분류(classify_brain_dump).
"""

import re

from guardrail_interceptor import is_crisis_text


class ProductivityManager:
    """향후 브레인덤프 / 시스템 제어 기능이 들어갈 자리."""

    def __init__(self, db_path: str = "cbt_memory.db"):
        self.db_path = db_path
        # TODO: 시스템 제어 로직 등은 여기에 추가


def build_daily_briefing_text(
    greeting: str,
    weather_text: str = "",
    quest_text: str = "",
    anchor_text: str = None,
) -> str:
    """데일리 브리핑 문구를 조합합니다.

    이 함수는 DB/네트워크에 직접 접근하지 않는 순수 텍스트 조합 함수입니다.
    실제 데이터(날씨, 퀘스트, 긍정 앵커)는 호출하는 쪽(jarvis_ui.py)에서
    기존 memory_db/get_current_weather를 통해 미리 가져와 넘겨줍니다 —
    이 모듈이 core.mental_care나 CrisisInterceptor 경로를 직접 건드리지
    않도록 하기 위한 의도적인 설계입니다.
    """
    parts = [greeting]

    if weather_text:
        parts.append(weather_text)

    if quest_text:
        parts.append(quest_text)

    if anchor_text:
        parts.append(f"오늘의 긍정적인 기억도 하나 떠올려보세요: {anchor_text}")

    parts.append("오늘 하루도 Master 곁에서 함께하겠습니다.")
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# 🧠 브레인덤프 1차 분류 (순수 함수, DB/네트워크 접근 없음)
#
# 이 함수는 이번 턴에 Gemini가 스스로 도구를 호출하지 않았을 때만 호출되는
# "백업" 경로다. 안전망이 너무 공격적으로 분류하면 애매한 잡담이 quests/mood_log
# 같은 구조화된 테이블에 잘못 들어가 리포트 품질을 해칠 수 있으므로, 신호가
# 확실할 때만 세부 카테고리로 분류하고 애매하면 memory(일반 catch-all)로
# 안전하게 떨어뜨린다. thought_records(사고기록)는 여러 구조화된 필드가 필요해
# 한 문장짜리 발화에서 자동 추론하는 게 CBT 원칙에 어긋나므로 대상에서 뺐다 —
# 그건 온율이가 대화로 유도해서 채우는 영역으로 남겨둔다.
#
# 우선순위: mood(숫자 신호) > quest(의도 표현) > anchor(긍정 감정) > memory > skip
# ─────────────────────────────────────────────────────────────────────────

_MOOD_SCORE_PATTERNS = [
    re.compile(r"(\d{1,2})\s*점"),
    re.compile(r"기분[^\d]{0,6}(\d{1,2})"),
]
_SLEEP_HOURS_PATTERNS = [
    re.compile(r"(\d{1,2}(?:\.\d)?)\s*시간\s*(?:잤|잤어|잤다|잠)"),
]

_QUEST_PATTERNS = [
    r"야\s*겠",       # 가야겠다, 해야겠다, 먹어야겠다 (동사 종류 무관)
    r"야\s*지",       # 가야지, 해야지, 먹어야지
    r"고\s*싶",       # 가고 싶다, 하고 싶어, 먹고 싶다
    r"거야",          # 갈 거야, 할 거야, 먹을 거야
    r"거\s*예요",
    r"목표는",
    r"계획은",
    r"기로\s*했",     # 가기로 했다, 하기로 했다, 먹기로 했다
]

_ANCHOR_PATTERNS = [
    r"좋았", r"행복했", r"뿌듯했", r"기뻤", r"감사했", r"즐거웠", r"만족스러웠",
]

_SKIP_MIN_LEN = 5
_FILLER_ONLY = {"음", "어", "그냥", "네", "아니", "응", "아", "흠", "그래", "어어"}


def classify_brain_dump(text: str) -> dict:
    """
    사용자 발화 한 문장을 브레인덤프 카테고리로 1차 분류한다.

    Returns:
        {"category": "mood"|"quest"|"anchor"|"memory"|"skip", "extracted": {...}}
        extracted의 키는 core.mental_care의 대응 메서드 키워드 인자와 이름을
        맞춰뒀다 (호출부에서 **extracted로 바로 넘길 수 있도록).
    """
    stripped = (text or "").strip()

    if not stripped or len(stripped) < _SKIP_MIN_LEN or stripped in _FILLER_ONLY:
        return {"category": "skip", "extracted": {}}

    # 2차 방어선: 정상적으로는 crisis_active 게이트가 이미 위기 문구를 걸러내고
    # 이 함수까지 도달하지 못하게 막아야 한다. 하지만 게이트가 어떤 이유로든
    # 뚫리는 경우(타이밍 레이스 등)에 대비해, 분류기 자체도 위기 문구를 재검사한다.
    # 예를 들어 quest 패턴의 "고 싶" 어미는 "죽고 싶다"에도 매칭되므로, 이 재검사가
    # 없으면 위기 발화가 그대로 퀘스트로 저장되는 사고가 날 수 있다.
    if is_crisis_text(stripped):
        return {"category": "skip", "extracted": {}}

    mood_score = None
    for pat in _MOOD_SCORE_PATTERNS:
        m = pat.search(stripped)
        if m:
            val = float(m.group(1))
            if 1 <= val <= 10:
                mood_score = val
                break

    sleep_hours = None
    for pat in _SLEEP_HOURS_PATTERNS:
        m = pat.search(stripped)
        if m:
            sleep_hours = float(m.group(1))
            break

    if mood_score is not None or sleep_hours is not None:
        return {
            "category": "mood",
            "extracted": {
                "mood_score": mood_score if mood_score is not None else "",
                "sleep_hours": sleep_hours if sleep_hours is not None else "",
                "notes": stripped,
            },
        }

    if any(re.search(p, stripped) for p in _QUEST_PATTERNS):
        return {"category": "quest", "extracted": {"quest_title": stripped}}

    if any(re.search(p, stripped) for p in _ANCHOR_PATTERNS):
        return {"category": "anchor", "extracted": {"content": stripped, "emotion_tag": "😊"}}

    return {"category": "memory", "extracted": {"information": stripped, "category": "brain_dump"}}
