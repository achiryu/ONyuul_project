"""
cbt_memory
==========
하위 호환용 파사드(facade) 모듈입니다.

실제 로직은 두 곳으로 분리되어 있습니다:
- core.safety.SafetyPlanManager      : 안전-critical (위기 대응용 안전 계획)
- core.mental_care.MentalCareManager : 그 외 CBT/멘탈케어 기능 전체

jarvis_ui.py 등 기존 코드는 지금까지와 동일하게
`from cbt_memory import CBTMemoryManager` 로 이 클래스를 그대로 쓰면 됩니다 —
인터페이스는 바뀌지 않았습니다. 새 기능을 추가할 땐 이 파일이 아니라
core/safety.py 또는 core/mental_care.py를 직접 수정하세요.

--------------------------------------------------------------------------
__getattr__ 자동 위임 (이전엔 메서드마다 손으로 위임 코드를 썼던 부분)
--------------------------------------------------------------------------
예전 버전은 `_care`/`_safety`의 메서드 하나하나를 이 파일에 다시 선언해서
그대로 전달하는 방식이었다. 그 결과 core/mental_care.py에 새 메서드
(예: delete_quest)를 추가했는데 여기 위임 코드를 깜빡 안 넣어서
`AttributeError: 'CBTMemoryManager' object has no attribute 'delete_quest'`가
나는 실제 버그를 겪었다. `__getattr__`로 "여기 명시적으로 없는 속성은
_safety, _care 순서로 찾아서 위임한다"는 규칙 하나만 두면, 앞으로 두 매니저에
메서드를 추가/삭제해도 이 파일은 손댈 필요가 없다.

`__getattr__`는 일반적인 속성 조회(인스턴스 __dict__, 클래스에 정의된 메서드 등)가
전부 실패했을 때만 파이썬이 호출하므로, 아래 명시적으로 남겨둔 `get_connection`
같은 특수 케이스나 `db_path` 같은 인스턴스 속성과 충돌하지 않는다.
"""
from core.safety import SafetyPlanManager, SafePlanDict
from core.mental_care import MentalCareManager, AnchorRow

__all__ = ["CBTMemoryManager", "SafePlanDict", "AnchorRow"]


class CBTMemoryManager:
    def __init__(self, db_path: str = "cbt_memory.db"):
        self.db_path = db_path
        self._safety = SafetyPlanManager(db_path)
        self._care = MentalCareManager(db_path)

    def get_connection(self):
        """하위 호환: 기존 코드가 memory_db.get_connection()을 직접 호출하는 경우 대비.
        (mental_care 쪽 커넥션을 대표로 반환 — safety_plan은 별도 테이블이라
        get_connection의 기존 용례상 mental_care 쪽이 맞다.)"""
        return self._care._conn()

    def __getattr__(self, name):
        """
        여기 명시적으로 정의되지 않은 속성/메서드 접근을 _safety → _care 순서로
        찾아서 위임한다. 두 클래스 모두에 없으면 원래대로 AttributeError를 낸다
        (조용히 None을 반환하는 등으로 오류를 숨기지 않음 — 실제로 없는 메서드를
        불렀을 때는 명확하게 실패해야 디버깅이 쉽다).

        self.__dict__.get(...)으로 안전하게 접근하는 이유: 만약 __init__이 아직
        _safety/_care를 설정하기 전(예: 서브클래싱 등 예외적인 상황)에 어떤 속성
        접근이 발생하면, `self._safety`처럼 일반 접근을 쓸 경우 그 자체가 다시
        __getattr__를 호출해 무한 재귀에 빠질 수 있다. __dict__.get은 그런 재귀
        없이 "아직 없으면 None"을 안전하게 돌려준다.
        """
        safety = self.__dict__.get("_safety")
        care = self.__dict__.get("_care")

        if safety is not None and hasattr(safety, name):
            return getattr(safety, name)
        if care is not None and hasattr(care, name):
            return getattr(care, name)

        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")