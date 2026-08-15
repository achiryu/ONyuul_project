# guardrail_interceptor.py
import asyncio
import re

from google import genai

# ─────────────────────────────────────────────────────────────────────────
# 위기 신호 탐지 패턴
#
# 재현율(recall) 우선: 완곡 표현이나 구어체까지 폭넓게 잡되, 오탐(false positive)이
# 늘더라도 안전 팝업이 한 번 더 뜨는 게 놓치는 것보다 훨씬 안전하다는 원칙을 따른다.
# 이 정규식만으로는 은어/초성/완전히 간접적인 표현까지는 못 잡으므로, 추후 LLM 기반
# 세이프티 분류(2차 필터)를 더하는 걸 권장한다 — 이건 결정론적 1차 필터일 뿐이다.
#
# 방법(method)에 대한 구체적 지시/수단은 포함하지 않는다 — 탐지 목적의 패턴이다.
# ─────────────────────────────────────────────────────────────────────────
_CRISIS_PATTERNS = [
    # 자살 관련
    r"자살",
    r"죽고\s*싶",
    r"죽어\s*버리고\s*싶",
    r"목숨을?\s*끊",
    r"극단적\s*선택",
    r"세상을?\s*떠나고\s*싶",
    r"사라지고\s*싶",
    r"더\s*이상\s*못\s*버티",
    r"살기\s*싫",
    r"삶을?\s*끝내고?\s*싶",
    r"그만\s*살고\s*싶",
    r"안\s*태어났으면",
    r"다\s*끝났으면\s*좋겠",
    r"다\s*의미\s*없",
    r"뛰어내리",
    r"목\s*매",
    r"약을?\s*많이\s*먹",
    r"다\s*(놓아|놔)\s*버리고\s*싶",   # 다 놔 버리고 싶다 / 다 놓아 버리고 싶다
    r"다\s*내려놓고\s*싶",
    r"포기\s*하고\s*싶",
    # 자해 관련
    r"자해",
    r"손목\s*(을|를)?\s*긋",
    r"나\s*자신을?\s*(아프게|다치게)",
    r"내\s*몸에?\s*상처",
    # 타해 관련 (시스템 지침이 자/타해 모두를 다루므로 함께 포함)
    r"죽이고\s*싶",
    r"해치고\s*싶",
    r"복수\s*(하겠|할\s*거)",
]

_COMPILED_CRISIS_PATTERNS = [re.compile(p) for p in _CRISIS_PATTERNS]


def is_crisis_text(text: str) -> bool:
    """텍스트에서 위기 신호를 탐지한다 (공개 API). 띄어쓰기 우회를 줄이기 위해
    공백 제거본도 함께 검사한다(완전한 우회 방지는 아니며, 2차 LLM 필터가
    보완해야 함). productivity_manager.classify_brain_dump 등 다른 모듈에서
    "이 텍스트는 위기 문구라 브레인덤프 분류 대상에서 아예 제외해야 한다"를
    판단하는 2차 방어선으로도 재사용된다."""
    if not text:
        return False
    normalized = text.replace(" ", "")
    return any(p.search(text) or p.search(normalized) for p in _COMPILED_CRISIS_PATTERNS)


# 하위 호환용 별칭 (이 모듈 내부 코드가 기존 이름을 계속 쓸 수 있도록)
_is_crisis = is_crisis_text


class SessionState:
    def __init__(self):
        self.is_speaking = False
        # block_playback: 과거엔 "위기 시 오디오 재생을 막는다"는 의미였지만,
        # 이제 AI 음성 응답은 위기 중에도 자연스럽게 계속 흐르게 하기로 했으므로
        # 이 플래그는 더 이상 오디오를 막는 용도로 쓰지 않는다 (항상 False로 둔다).
        # 대신 "위기 중 부수효과(도구 실행, 자동 DB 기록)는 차단한다"는 원래
        # 안전 원칙은 여전히 유효하므로, 그 역할만 crisis_active로 분리했다.
        self.block_playback = False
        self.crisis_active = False  # 🆕 위기 개입 중: 도구 실행/자동 기록 차단 전용 플래그
        self.is_standby = False
        # 🎙️ 마이크 하드 뮤트: 대기 모드(is_standby)와 완전히 별개다. 대기 모드는
        # 웨이크워드를 들어야 하므로 오디오를 계속 서버로 보내지만, 이건 그 전송
        # 자체를 완전히 끊는다 — 회의 중이라 마이크 자체를 확실히 죽이고 싶을 때 등.
        self.mic_hard_muted = False

    def enter_standby(self):
        self.is_standby = True
        print("\n💤 [ONyuul System] 대기 모드로 전환되었습니다.")

    def exit_standby(self):
        self.is_standby = False
        print("\n🔔 [ONyuul System] 대기 모드가 해제되었습니다.")


class CrisisInterceptor:
    # 2차 필터 전용 경량 모델. Live 세션과 무관한 단발성 분류 호출이라 저지연/저비용
    # 모델을 쓴다. 정확한 모델명은 계정/리전에 따라 달라질 수 있으니 실제 사용 가능한
    # 모델로 필요시 교체할 것.
    LLM_FILTER_MODEL = "gemini-flash-lite-latest"

    def __init__(self, on_start=None, on_end=None, api_key: str = None):
        self.on_start = on_start
        self.on_end = on_end
        # 1차 정규식 필터와 별개로 완곡 표현까지 잡기 위한 2차 LLM 필터용 클라이언트.
        # api_key가 없으면 2차 필터는 조용히 비활성화되고(1차 필터만으로 동작),
        # 시스템 전체가 죽지 않는다.
        self._llm_client = genai.Client(api_key=api_key) if api_key else None

    def check_and_flag(self, state: SessionState, text: str) -> bool:
        """
        동기적으로 위기 여부를 판단하고, 감지 시 state.crisis_active를 '즉시' True로
        세팅한다. await 없이 호출부와 같은 실행 컨텍스트에서 바로 실행되므로
        레이스 컨디션이 없다.

        기존 흐름(asyncio.create_task(interceptor.maybe_intercept(...)))은
        create_task가 코루틴을 '예약'만 할 뿐 실제 실행은 다음 await 지점까지
        미뤄진다는 점 때문에, 같은 turn_complete 처리 안에서 크리티컬한 레이스가
        있었다: transcription 처리 시 create_task로 예약된 위기 처리가 아직 한
        번도 실행되지 못한 채로, 바로 이어지는 브레인덤프 게이트(`not state.
        crisis_active`)가 먼저 통과해버릴 수 있었다. 호출부는 이제 다음처럼
        써야 한다:

            if interceptor.check_and_flag(state, text):
                crisis_task = asyncio.create_task(interceptor.run_popup_and_cooldown(state))
        """
        if state.crisis_active:
            # 이미 개입 중(예: LLM 경로가 먼저 이 문장을 잡은 경우)이라면 재트리거하지
            # 않는다. 이걸 빼면 정규식 경로와 LLM 경로가 서로를 모른 채 각자
            # run_popup_and_cooldown을 불러 팝업이 중복으로 뜰 수 있다.
            return False
        if _is_crisis(text):
            state.crisis_active = True
            return True
        return False

    async def llm_check(self, text: str) -> bool:
        """
        2차 안전 필터. 정규식(1차)이 놓치는 완곡 표현("이제 그만하고 싶다",
        "다 놓아버리고 싶어" 등)까지 잡기 위해 LLM에게 짧게 판단을 맡긴다.

        - 이 호출이 실패(네트워크 오류, 클라이언트 미설정 등)해도 예외를 삼키고
          False를 반환한다 — 2차 필터가 죽어도 1차 정규식 필터는 계속 살아있으므로
          시스템 전체가 무너지지 않는다.
        - 매 청크가 아니라 턴이 끝날 때 최종 텍스트로 1회만 호출하는 걸 전제로
          설계했다 (비용/지연 관리).
        """
        if not self._llm_client or not text:
            return False
        try:
            prompt = (
                "다음은 실시간 음성 비서에게 사용자가 한 발화입니다. "
                "이 발화가 자살, 자해, 또는 타인에 대한 위해 위험 신호를 담고 있는지 "
                "판단하세요. '이제 그만하고 싶다', '다 놓아버리고 싶어'처럼 완곡한 "
                "표현도 신중하게 위험 신호로 간주하세요. 다만 '과제 때문에 죽겠다', "
                "'배고파 죽겠다' 같은 단순 관용구·과장 표현은 위험 신호로 보지 마세요.\n\n"
                f'발화: "{text}"\n\n'
                "위험 신호가 있다고 판단되면 정확히 YES, 아니면 정확히 NO라고만 "
                "답하세요. 다른 말은 붙이지 마세요."
            )
            response = await asyncio.to_thread(
                self._llm_client.models.generate_content,
                model=self.LLM_FILTER_MODEL,
                contents=prompt,
            )
            answer = (getattr(response, "text", "") or "").strip().upper()
            return answer.startswith("YES")
        except Exception as e:
            print(f"⚠️ [Guardrail 2.0] LLM 2차 필터 오류(1차 필터만으로 계속 동작): {e}")
            return False

    async def maybe_intercept_llm(self, state: SessionState, text: str) -> bool:
        """
        LLM 2차 필터 전용 진입점. 이미 1차 필터로 crisis_active가 켜져 있다면
        (=정규식이 이미 잡았다면) 중복 호출하지 않고 바로 반환한다.

        주의: LLM 호출 자체에 지연이 있으므로, 이 경로로 개입이 트리거되는 시점은
        1차 필터보다 몇 초 늦을 수 있다. 그 사이 브레인덤프 같은 다른 로직이 먼저
        실행됐을 가능성은 남아있다 — 호출부(jarvis_ui.py)가 이 함수의 반환값(bool)을
        보고 "뒤늦게 위기로 확인됐다"는 걸 알아채 방금 저장된 항목을 되돌릴 수 있게,
        실제로 개입했는지 여부를 반환한다.

        이중 팝업 방지: llm_check(await로 몇 초 걸림)가 진행되는 '동안' 정규식(1차)
        필터가 같은 문장을 먼저 잡아 팝업을 띄울 수 있다. 그 상태에서 LLM 응답이
        뒤늦게 도착했을 때 재확인 없이 그대로 팝업을 또 띄우면 중복 팝업이 뜬다.
        그래서 llm_check가 끝난 '직후'(팝업을 띄우기 바로 전)에 crisis_active를
        다시 확인한다 — 이 재확인과 실제 팝업 호출 사이엔 await가 없어 asyncio의
        협조적 스케줄링상 새로운 경쟁 상태가 생기지 않는다.
        """
        if state.crisis_active:
            return False

        is_crisis = await self.llm_check(text)
        if not is_crisis:
            return False

        if state.crisis_active:
            # llm_check가 await로 대기하는 동안, 정규식(1차) 필터가 이미 이 문장을
            # 잡아 팝업을 띄웠을 수 있다. 여기서 다시 걸어 중복 팝업을 막는다.
            return False

        state.crisis_active = True
        await self.run_popup_and_cooldown(state)
        return True

    async def run_popup_and_cooldown(self, state: SessionState):
        """check_and_flag가 이미 crisis_active=True로 세팅한 뒤 호출되는,
        팝업 표시 + 15초 유지 + 해제를 담당하는 백그라운드 태스크."""
        print("\n🚨 [Guardrail 2.0] 위기 감지! AI가 위로를 건네며, UI 팝업을 띄웁니다.")

        if self.on_start:
            try:
                self.on_start()
            except Exception as e:
                print(f"⚠️ on_start 오류: {e}")

        await asyncio.sleep(15.0)

        if self.on_end:
            try:
                self.on_end()
            except Exception as e:
                print(f"⚠️ on_end 오류: {e}")

        state.crisis_active = False

    async def maybe_intercept(self, state: SessionState, text: str):
        """
        하위 호환용 통합 메서드 (check_and_flag + run_popup_and_cooldown을 한 번에).
        직접 `await`로 호출하는 경우(예: 테스트 코드)는 레이스 컨디션이 없으므로
        안전하게 계속 쓸 수 있다. 다만 실시간 파이프라인처럼 `asyncio.create_task`로
        예약해서 쓰는 곳에서는 반드시 check_and_flag를 먼저 동기 호출한 뒤
        run_popup_and_cooldown만 태스크로 예약할 것.
        """
        if self.check_and_flag(state, text):
            await self.run_popup_and_cooldown(state)

    def on_turn_complete(self, state: SessionState):
        pass