"""
config_manager
==============
사용자별 로컬 설정(현재는 Gemini API 키) 저장/조회.

배포판(.exe)에서는 각 사용자가 자기 Gemini API 키를 직접 발급받아 입력하게
한다. .env는 개발 중 로컬 테스트용 기본값을 두는 용도로 남겨두고, 배포판에서는
사용자가 UI로 입력한 키를 이 모듈이 관리하는 별도의 로컬 설정 파일
(user_config.json)에 저장한다.

우선순위: 로컬 설정 파일 > 환경변수(GEMINI_API_KEY, .env 포함) > 빈 문자열(미설정)

주의: 이 config.json은 평문으로 저장된다. 개인용 데스크톱 앱에서 흔한 방식이지만,
더 강한 보안이 필요하면 OS 자격 증명 관리자(Windows Credential Manager 등)를
활용하는 `keyring` 패키지로 교체를 검토할 것.
"""
import json
import os
from pathlib import Path

# 사용자 홈/APPDATA 아래 고정 위치에 저장한다. exe 파일 옆에 저장하면 재설치나
# exe 이동 시 설정이 함께 날아갈 수 있어, OS 표준 사용자 데이터 경로를 쓴다.
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "ONyuul"
CONFIG_PATH = CONFIG_DIR / "user_config.json"
DB_PATH = CONFIG_DIR / "cbt_memory.db"


def get_db_path() -> str:
    """
    CBT/멘탈케어 SQLite DB의 절대 경로를 반환한다.

    이전에는 CBTMemoryManager()가 기본값 "cbt_memory.db"(상대경로)를 그대로
    썼는데, 이건 exe를 실행하는 시점의 작업 디렉터리(cwd) 기준이다. 바탕화면
    바로가기로 실행하거나 쓰기 권한이 없는 폴더(Program Files 등)에 exe를 두면
    실행 위치마다 DB가 따로 생기거나, 최초 실행부터 쓰기 오류가 날 수 있다.
    API 키(user_config.json)와 동일하게 고정된 사용자 데이터 폴더를 쓴다.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return str(DB_PATH)


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_api_key() -> str:
    """저장된 키가 있으면 그걸, 없으면 환경변수(.env 포함)를 확인한다."""
    config = _load_config()
    key = str(config.get("gemini_api_key", "")).strip()
    if key:
        return key
    return os.environ.get("GEMINI_API_KEY", "").strip()


def save_api_key(api_key: str) -> None:
    config = _load_config()
    config["gemini_api_key"] = api_key.strip()
    _save_config(config)


def clear_api_key() -> None:
    config = _load_config()
    config.pop("gemini_api_key", None)
    _save_config(config)


# ─────────────────────────────────────────────────────────────────────────
# 웨이크워드 사용자 변형 (오인식 학습용)
#
# 기본 내장 변형 리스트는 코드에 하드코딩돼 있지만, 사람마다 발음/사투리/억양이
# 달라 그것만으로는 부족할 수 있다. 사용자가 GUI에서 직접 변형을 추가/삭제할 수
# 있게 이 파일에 별도로 저장한다 (기본 내장 목록과 합쳐서 사용).
# ─────────────────────────────────────────────────────────────────────────

def get_wake_word_variants() -> list:
    """사용자가 직접 추가한 웨이크워드 변형 목록 (기본 내장 목록은 제외)."""
    config = _load_config()
    variants = config.get("wake_word_variants", [])
    return list(variants) if isinstance(variants, list) else []


def add_wake_word_variant(word: str) -> None:
    word = word.strip()
    # 한두 글자짜리는 일상 대화에서 흔히 등장해 오탐(엉뚱한 순간에 대기 모드가
    # 풀리는 현상)이 폭증할 위험이 크므로, 최소 길이를 둔다.
    if not word or len(word) < 2:
        return
    config = _load_config()
    variants = config.get("wake_word_variants", [])
    if not isinstance(variants, list):
        variants = []
    if word not in variants:
        variants.append(word)
    config["wake_word_variants"] = variants
    _save_config(config)


def remove_wake_word_variant(word: str) -> None:
    config = _load_config()
    variants = config.get("wake_word_variants", [])
    if not isinstance(variants, list):
        return
    if word in variants:
        variants.remove(word)
    config["wake_word_variants"] = variants
    _save_config(config)


# ─────────────────────────────────────────────────────────────────────────
# 화면 테마 (Dark / Light / AUTO)
#
# 주/야간 "케어 모드"(AI 응답 톤)와는 완전히 독립적인 설정이다 — 사용자가
# 케어 톤과 무관하게 화면 테마만 따로 고정하고 싶을 수 있어 분리했다.
# ─────────────────────────────────────────────────────────────────────────

def get_theme_mode() -> str:
    """저장된 테마 모드. 값은 'Dark' | 'Light' | 'AUTO' 중 하나이며, 기본값은 'AUTO'."""
    config = _load_config()
    mode = str(config.get("theme_mode", "AUTO")).strip()
    return mode if mode in ("Dark", "Light", "AUTO") else "AUTO"


def save_theme_mode(mode: str) -> None:
    if mode not in ("Dark", "Light", "AUTO"):
        return
    config = _load_config()
    config["theme_mode"] = mode
    _save_config(config)


# ─────────────────────────────────────────────────────────────────────────
# Windows 시작 시 자동 실행
#
# HKEY_CURRENT_USER\...\Run 레지스트리는 관리자 권한 없이도(사용자 단위) 등록
# 가능한 표준적인 방법이다. winreg는 Windows 전용 표준 라이브러리라, 다른
# OS(예: 개발 중 이 코드를 리눅스/맥에서 돌릴 때)에서도 앱이 죽지 않도록
# import 실패를 조용히 처리한다.
# ─────────────────────────────────────────────────────────────────────────
_AUTOSTART_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_VALUE_NAME = "ONyuul"


def is_autostart_enabled() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY_PATH, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, _AUTOSTART_VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_autostart_enabled(enable: bool, command: str) -> bool:
    """
    성공 여부를 bool로 반환한다. 실패해도 예외를 던지지 않는다 — 자동 실행은
    있으면 좋은 부가 기능이지, 이것 때문에 앱 자체가 죽으면 안 된다.
    """
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, _AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_VALUE_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"⚠️ [Autostart] 설정 실패: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────
# 온보딩 투어 표시 여부
# ─────────────────────────────────────────────────────────────────────────

def has_seen_onboarding() -> bool:
    config = _load_config()
    return bool(config.get("has_seen_onboarding", False))


def mark_onboarding_seen() -> None:
    config = _load_config()
    config["has_seen_onboarding"] = True
    _save_config(config)


# ─────────────────────────────────────────────────────────────────────────
# TTS(온율 음성) 출력 볼륨
# ─────────────────────────────────────────────────────────────────────────

def get_tts_volume() -> float:
    config = _load_config()
    try:
        v = float(config.get("tts_volume", 1.0))
        return max(0.0, min(1.0, v))
    except (ValueError, TypeError):
        return 1.0


def save_tts_volume(volume: float) -> None:
    config = _load_config()
    config["tts_volume"] = max(0.0, min(1.0, float(volume)))
    _save_config(config)