import re
import math
import asyncio
import os
from pathlib import Path
import sys
import sqlite3
import random
import pyaudio
import warnings
import subprocess
import shutil
from tkinter import filedialog
import datetime
import urllib.request
import urllib.parse
import threading
import webbrowser
import numpy as np
import tkinter
import psutil
try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    # Pillow가 없으면 트레이 아이콘과 PNG 아이콘 로더 둘 다 비활성화되고
    # 나머지 앱은 정상 동작한다 (이모지로 자연 폴백).
    PIL_AVAILABLE = False
try:
    import pystray
    TRAY_AVAILABLE = PIL_AVAILABLE
except ImportError:
    TRAY_AVAILABLE = False
import customtkinter as ctk
import websockets
from dotenv import load_dotenv
import config_manager

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from google import genai
from google.genai import types
from faster_whisper import WhisperModel

from cbt_memory import CBTMemoryManager
from core.reminders import ReminderManager
from core.tasks import TaskManager
from core.db import get_connection as _core_get_connection
from core import db_crypto
from guardrail_interceptor import CrisisInterceptor, SessionState
from productivity.productivity_manager import build_daily_briefing_text, classify_brain_dump

load_dotenv()

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN_WARNING"] = "1"
warnings.filterwarnings("ignore")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_SIZE = 1024

# Google Search 그라운딩 진단용 스위치. "1008 invalid authentication credentials,
# expected OAuth 2 access token" 오류의 원인이 확정될 때까지 False로 둔다.
# 원인 확인 후 True로 되돌리면 일반 지식 질문 기능이 다시 켜진다.
ENABLE_GOOGLE_SEARCH = False

# 베타 피드백 수집용 구글 폼 링크. 실제 폼을 만드신 뒤 이 URL만 교체하면 됩니다.
FEEDBACK_FORM_URL = "https://forms.gle/tAuxQGjeiF2WudFn7"

# ─────────────────────────────────────────────────────────────────────────
# 디자인 토큰 (색상)
#
# 기능을 하나씩 추가할 때마다 그때그때 hex 값을 즉석으로 정해 쓰다 보니,
# 41개의 서로 다른 색(같은 색의 대소문자 표기 차이 포함)이 코드 곳곳에
# 흩어져 있었다. 5회 이상 반복되는(=실질적으로 "이 앱의 색"으로 굳어진) 색만
# 의미 있는 이름으로 통합했다. 1~4회만 쓰인 색은 의도적인 단발성 강조색
# (위기 배너, 안전 계획 카드 등)일 가능성이 높아 그대로 남겨뒀다 — 억지로
# 통일하면 오히려 의도된 포인트 컬러가 사라진다.
# ─────────────────────────────────────────────────────────────────────────
COLOR_TEXT_MUTED = "#888888"        # 보조 설명, placeholder급 텍스트
COLOR_TEXT_SECONDARY = "#CCCCCC"    # 본문보다 한 단계 옅은 텍스트
COLOR_TEXT_DISABLED = "#AAAAAA"     # 안내 문구, 흐린 텍스트

COLOR_CARD_BG = "#2b2b2b"           # 카드/패널 배경
COLOR_BORDER = "#3B3B3B"            # 구분선, 헤더 아이콘 버튼 배경

COLOR_PRIMARY = "#6AC3FF"           # 주요 액션 (재연결, 파란 버튼 등)

COLOR_SUCCESS = "#3EFF8F"           # 성공/완료를 나타내는 텍스트·상태
COLOR_SUCCESS_BTN = "#27AE60"       # 성공/확정 버튼 배경
COLOR_SUCCESS_BTN_HOVER = "#1E8449"

COLOR_DANGER = "#E74C3C"            # 경고/위험을 나타내는 텍스트
COLOR_DANGER_BTN = "#922B21"        # 삭제 등 위험한 동작의 버튼 배경
COLOR_DANGER_BTN_HOVER = "#641E16"

COLOR_WARNING = "#FFA514"           # 주의/진행중 표시
COLOR_WARNING_ALT = "#FFCC00"       # 대기 상태 등 노란 계열 강조

COLOR_NEUTRAL_BTN = "#555555"       # 취소/보조 버튼 배경
COLOR_NEUTRAL_HOVER = "#2B2B2B"     # 헤더 아이콘 버튼 hover
COLOR_AI_ACCENT = "#9B59B6"         # 온율(AI)의 발화를 나타내는 전용 색 (채팅 로그 발신자 구분용)

# ─────────────────────────────────────────────────────────────────────────
# 디자인 토큰 (타이포그래피)
#
# 색상과 달리, 여기서는 값을 억지로 병합하지 않았다 — 화면을 직접 보지 않은
# 채로 "12와 13은 거의 같으니 하나로 합치자"처럼 판단하면 의도치 않게 특정
# 화면의 크기감이 미묘하게 바뀔 위험이 있다. 그래서 지금 실제로 쓰이는 8개
# 크기를 전부 그대로 보존하면서 이름만 붙였다 — 최소한 "이 숫자가 왜 14인지"
# 는 알 수 있게 되고, 실제 화면을 보고 나서 병합할 만한 크기가 보이면
# 그때 안전하게 값을 조정하면 된다.
# ─────────────────────────────────────────────────────────────────────────
FONT_TITLE = 20         # 앱 최상단 타이틀 ("🤖 온율")
# 폰트 패밀리를 명시 안 하면, 한글은 시스템이 대체 폰트를 골라 쓰고 영문/숫자는
# customtkinter 기본 폰트(Roboto 계열)로 렌더링되어 화면 안에서 서로 다른
# 폰트가 섞여 보이는 문제가 있었다. Windows에 항상 내장된 폰트로 통일해서
# 별도 설치 없이 모든 사용자 환경에서 일관되게 보이도록 한다.
FONT_FAMILY = "맑은 고딕"
FONT_DIALOG_TITLE = 18  # 다이얼로그 큰 제목 (온보딩 등)
FONT_HEADING = 16       # 굵은 강조 헤더
FONT_SECTION = 15       # 섹션/다이얼로그 제목
FONT_SUBSECTION = 14    # 카드·좌측 패널 섹션 라벨
FONT_BODY = 13          # 본문 텍스트
FONT_LABEL = 12         # 보조 라벨, 설정 항목명
FONT_CAPTION = 11       # 캡션, 힌트, 타임스탬프

# ─────────────────────────────────────────────────────────────────────────
# 자체 업데이트 확인
#
# 별도 서버 없이, 정적 JSON 파일 하나(예: GitHub 저장소의 raw 파일)를 참조하는
# 방식이다. 새 버전을 배포할 때마다 이 JSON 파일의 "version"만 갱신해두면 된다.
#
# JSON 형식 예시:
#   {
#     "version": "1.1.0",
#     "download_url": "https://github.com/yourname/onyuul/releases/latest",
#     "notes": "위기 감지 정확도 개선, 할 일 관리 기능 추가"
#   }
# ─────────────────────────────────────────────────────────────────────────
APP_VERSION = "2.0.0"
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/achiryu/ONyuul_project/main/version.json"


def _parse_version(v: str) -> tuple:
    """'1.2.10' 같은 버전 문자열을 (1, 2, 10) 튜플로 변환해 비교 가능하게 한다.
    형식이 이상하면 비교에서 항상 지도록 (0,)을 반환한다."""
    try:
        return tuple(int(p) for p in str(v).strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_newer_version(remote_version: str, current_version: str = APP_VERSION) -> bool:
    return _parse_version(remote_version) > _parse_version(current_version)

print("🎙️ [ONyuul STT Engine] 고성능 Whisper(small) 자막 엔진을 로드하는 중입니다...")
whisper_model = None
whisper_load_error = None
try:
    whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    print("✅ [ONyuul STT Engine] 자막 엔진 로드 완료!\n")
except Exception as e:
    # 이 로딩은 모듈 임포트 시점(=Tkinter GUI가 뜨기도 전)에 실행되므로, 여기서
    # 예외가 그대로 전파되면 사용자는 GUI조차 못 보고 콘솔 트레이스백만 마주친다.
    # 인터넷 연결 문제(최초 실행 시 모델 파일을 내려받아야 함)나 디스크 공간 부족 등
    # 비개발자 사용자에게 흔히 생길 수 있는 실패라, 자막 기능만 비활성화하고
    # 나머지(음성 대화, CBT 기능 등)는 정상 동작하도록 우회한다. 실제 경고는 GUI가
    # 뜬 뒤 채팅 로그에 한 번 표시한다 (__main__ 블록 참고).
    whisper_load_error = str(e)
    print(f"⚠️ [ONyuul STT Engine] 자막 엔진 로딩 실패 (자막 기능만 비활성화되고 나머지는 정상 동작합니다): {e}")

def resample_24k_to_16k(audio_24k: np.ndarray) -> np.ndarray:
    if len(audio_24k) == 0:
        return audio_24k
    num_output_samples = int(len(audio_24k) * 16000 / 24000)
    x_old = np.linspace(0, 1, len(audio_24k), endpoint=False)
    x_new = np.linspace(0, 1, num_output_samples, endpoint=False)
    return np.interp(x_new, x_old, audio_24k).astype(np.float32)

def transcribe_pcm24k(pcm_bytes: bytes) -> str:
    if not pcm_bytes or whisper_model is None:
        return ""
    audio_24k = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    audio_16k = resample_24k_to_16k(audio_24k)
    segments, _ = whisper_model.transcribe(
        audio_16k, language="ko", beam_size=3, initial_prompt="네, Master. 천천히 하나씩 해봐요."
    )
    return " ".join([seg.text.strip() for seg in segments]).strip()

_BUILTIN_WAKE_WORDS = ["온율", "온율아", "온율이", "오뉴월", "온유"]

# 음성으로 앱 종료를 의도했을 수 있는 표현들. "바이바이"/"수고했어" 같은 흔한 말은
# 앱과 무관한 일상 대화에서도 나올 수 있어서(예: "회사에서 수고했다는 말을 들었어"),
# 이 목록에 걸려도 곧바로 앱을 끄지 않고 반드시 "정말 종료하시겠어요?" 확인창을
# 띄우는 용도로만 쓴다 — 오탐이 나도 확인창 하나만 뜨고 넘어갈 뿐, 실수로 앱이
# 꺼지는 일은 없게 설계했다.
_EXIT_INTENT_PHRASES = [
    "바이바이", "잘가", "잘 가", "안녕히 계세요", "안녕히 있어",
    "수고했어", "수고하셨어요", "수고했습니다",
    "이만 종료", "이제 종료", "종료할게", "종료해줘", "꺼줘", "그만할게", "이만 할게",
]


def contains_exit_intent(text: str) -> bool:
    clean = text.replace(" ", "")
    return any(phrase.replace(" ", "") in clean for phrase in _EXIT_INTENT_PHRASES)


def apply_volume(pcm_bytes: bytes, volume: float) -> bytes:
    """
    16bit PCM 오디오 바이트에 볼륨(0.0~1.0) 배율을 곱해서 반환한다.

    volume == 1.0(100%)이면 원본을 그대로 반환해 불필요한 연산을 건너뛴다.
    int16 범위를 넘는 값은 클리핑해서 왜곡(찌그러짐)을 방지한다.
    """
    if volume >= 1.0 or not pcm_bytes:
        return pcm_bytes
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    arr *= volume
    arr = np.clip(arr, -32768, 32767).astype(np.int16)
    return arr.tobytes()

def contains_wake_word(text: str) -> bool:
    # 기본 내장 목록 + 사용자가 GUI에서 직접 추가한 변형(발음/사투리 대응)을 합쳐서 검사한다.
    # config_manager 파일 I/O가 매 청크마다 불리면 느릴 수 있으니, 매번 새로 읽지 않고
    # gui.wake_word_variants(런타임 캐시, 설정 창에서 추가/삭제 시 갱신)를 우선 참조하고,
    # 없으면(예: gui 초기화 전) config_manager에서 직접 읽는다.
    try:
        user_variants = _wake_word_runtime_cache if _wake_word_runtime_cache is not None else config_manager.get_wake_word_variants()
    except Exception:
        user_variants = []
    wake_words = _BUILTIN_WAKE_WORDS + user_variants
    clean_text = text.replace(" ", "").lower()
    return any(w.replace(" ", "").lower() in clean_text for w in wake_words if w)

# GUI가 초기화되며 config_manager.get_wake_word_variants()로 채워주는 런타임 캐시.
# 매 오디오 청크마다(수 ms 간격) contains_wake_word가 호출되므로 파일 I/O를 피하기 위함.
_wake_word_runtime_cache = None

def refresh_wake_word_cache():
    global _wake_word_runtime_cache
    try:
        _wake_word_runtime_cache = config_manager.get_wake_word_variants()
    except Exception:
        _wake_word_runtime_cache = []

def _get_startup_command() -> str:
    """
    Windows 시작 프로그램 레지스트리에 등록할 실행 명령어를 만든다.

    PyInstaller로 빌드된 .exe로 실행 중이면(sys.frozen) 그 exe 경로를 그대로
    쓰고, 개발 중(python jarvis_ui.py로 직접 실행)이면 파이썬 인터프리터 +
    이 스크립트 경로를 조합한다.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

def friendly_connection_error(exc: Exception) -> str:
    """
    연결 끊김 예외를 베타테스터가 이해할 수 있는 한국어 메시지로 변환한다.

    원본 예외(str(exc))는 콘솔에는 그대로 남기고(개발자가 재현할 때 필요),
    사용자에게 보이는 배너에는 이 함수의 결과만 노출한다. "429
    RESOURCE_EXHAUSTED" 같은 원문을 비개발자가 봐도 뭘 해야 할지 알 수 없다.
    """
    text = str(exc)
    lowered = text.lower()

    if "429" in text or "resource_exhausted" in lowered or "quota" in lowered:
        return "API 사용량 한도에 도달했습니다. 잠시 후 다시 시도해주세요."
    if any(k in text for k in ("401", "403")) or any(
        k in lowered for k in ("permission_denied", "api_key_invalid", "invalid api key", "unauthenticated")
    ):
        return "API 키가 유효하지 않거나 권한이 없습니다. 우측 상단 ⚙ 버튼에서 키를 다시 확인해주세요."
    if any(k in lowered for k in ("getaddrinfo", "name or service not known", "connection refused", "network is unreachable", "nodename nor servname")):
        return "인터넷 연결을 확인해주세요."
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in lowered:
        return "서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요."
    if "1006" in text or "abnormal closure" in lowered:
        return "서버와의 연결이 예기치 않게 끊겼습니다."
    if "1011" in text or "ping timeout" in lowered:
        return "연결이 응답 지연으로 끊겼습니다."

    # 매칭되는 패턴이 없으면 원문을 짧게 잘라서 함께 보여준다 (완전히 숨기지는 않음 —
    # 베타 단계에서는 예상 못 한 새로운 오류를 사용자가 그대로 알려주는 게
    # 오히려 디버깅에 도움이 된다).
    return f"연결 중 문제가 발생했습니다. ({text[:100]})"

# ─────────────────────────────────────────────────────────────────────────
# DB 복호화 (앱이 켜지는 시점, 매니저들이 DB 파일을 열기 전에 반드시 먼저 실행)
#
# 암호화된 백업(.enc)이 있으면 복호화해서 평문 작업 파일을 만든다. 평문
# 파일이 이미 존재하면(지난 세션이 비정상 종료된 경우) 절대 덮어쓰지 않고
# 그대로 둔다 — db_crypto.decrypt_db_on_startup 안에 그 안전장치가 있다.
# win32crypt/cryptography가 없는 환경(개발/테스트 등)에서는 조용히 건너뛴다.
# ─────────────────────────────────────────────────────────────────────────
_db_plain_path = Path(config_manager.get_db_path())
_db_encrypted_path = Path(str(_db_plain_path) + ".enc")
_db_config_dir = Path(config_manager.CONFIG_DIR) if hasattr(config_manager, "CONFIG_DIR") else _db_plain_path.parent
db_crypto.decrypt_db_on_startup(_db_encrypted_path, _db_plain_path, _db_config_dir)

memory_db = CBTMemoryManager(db_path=config_manager.get_db_path())
reminder_db = ReminderManager(db_path=config_manager.get_db_path())
task_db = TaskManager(db_path=config_manager.get_db_path())

def create_reminder(title: str, remind_at: str, kind: str = "schedule", repeat_rule: str = "") -> dict:
    return reminder_db.create_reminder(title=title, remind_at=remind_at, kind=kind, repeat_rule=(repeat_rule or None))

def get_upcoming_reminders(limit: int = 10) -> list:
    return reminder_db.get_upcoming_reminders(limit=limit)

def create_task(title: str, due_date: str = "", priority: str = "medium") -> dict:
    return task_db.create_task(title=title, due_date=(due_date or None), priority=priority)

def complete_task(task_title: str = "") -> dict:
    return task_db.complete_task(title=task_title)

def get_pending_tasks(limit: int = 20) -> list:
    return task_db.get_pending_tasks(limit=limit)

def save_user_memory(information: str, category: str = "cbt_context") -> str:
    return memory_db.save_memory(text=information, category=category)

def log_mood_and_sleep(mood_score: str = "", sleep_hours: str = "", emotion_keywords: str = "", notes: str = "") -> str:
    return memory_db.log_mood_and_sleep(mood_score=mood_score, sleep_hours=sleep_hours, emotion_keywords=emotion_keywords, notes=notes)

def get_mood_history(days: int = 7) -> str:
    return memory_db.get_mood_history(days=days)

def add_thought_record(
    situation: str = "",
    automatic_thought: str = "",
    alternative_thought: str = "",
    emotion_before: int = 50,
    emotion_after: int = 50,
    cognitive_distortion: str = "",
) -> dict:
    """CBT 인지 재구성 기록 저장. 온율이 대화로 (공감 → 인지 오류 탐지 →
    소크라테스식 질문 → 대안적 사고 도출) 흐름을 거친 뒤 호출하도록 시스템
    프롬프트에서 안내한다."""
    record_id = memory_db.add_thought_record(
        situation=situation,
        automatic_thought=automatic_thought,
        cognitive_distortion=cognitive_distortion or None,
        alternative_thought=alternative_thought,
        emotion_before=emotion_before,
        emotion_after=emotion_after,
    )
    return {"status": "success", "record_id": record_id}

def get_user_thought_history(limit: int = 10) -> list:
    return memory_db.get_user_thought_history(limit=limit)

def start_grounding_guide(technique: str = "breathing") -> str:
    if technique in ["breathing", "호흡", "478"]:
        return (
            "Master, 편안한 자세로 어깨 힘을 빼세요. "
            "이제 코로 천천히 숨을 마십니다. 하나... 둘... 셋... 넷. "
            "숨을 잠시 멈춥니다. 하나... 둘... 셋... 넷... 다섯... 여섯... 일곱. "
            "이제 입으로 길게 내쉬어봅니다. 후... 하나... 둘... 셋... 넷... 다섯... 여섯... 일곱... 여덟. "
            "참 잘하셨습니다."
        )
    else:
        return (
            "Master, 머릿속 생각을 잠시 멈추고 방 안을 둘러보세요. "
            "눈에 보이는 물건 3가지를 가만히 짚어보시고, 들리는 소리 2가지에 귀를 기울여보세요. "
            "Master는 지금 안전한 곳에 계십니다."
        )

def log_grounding_session(technique_type: str, feedback: str = "") -> str:
    return memory_db.log_grounding_session(technique_type=technique_type, feedback=feedback)

def save_positive_anchor(content: str, emotion_tag: str = "소소한 기쁨") -> str:
    return memory_db.save_positive_anchor(content=content, emotion_tag=emotion_tag)

def recall_positive_anchors(limit: int = 3) -> str:
    return memory_db.get_positive_anchors(limit=limit)

def create_micro_quest(quest_title: str) -> str:
    return memory_db.create_micro_quest(quest_title=quest_title)

def complete_micro_quest(quest_title: str = "") -> str:
    return memory_db.complete_micro_quest(quest_title=quest_title)

def get_pending_quests() -> str:
    return memory_db.get_pending_quests()

def get_current_time() -> str:
    now = datetime.datetime.now()
    days = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    day_str = days[now.weekday()]
    return now.strftime(f"현재 시각은 %Y년 %m월 %d일 {day_str} %H시 %M분입니다.")

def get_system_status() -> dict:
    """현재 PC의 CPU/RAM 사용률을 조회한다. Master가 '컴퓨터 좀 버벅여', '지금 얼마나
    무거워?' 같은 걸 물을 때 쓰인다."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        return {
            "status": "success",
            "cpu_percent": cpu_percent,
            "ram_percent": mem.percent,
            "ram_used_gb": round(mem.used / (1024 ** 3), 1),
            "ram_total_gb": round(mem.total / (1024 ** 3), 1),
        }
    except Exception as e:
        return {"status": "error", "message": f"시스템 상태 조회 중 오류: {e}"}

_WEATHER_CONDITION_KR = {
    "Clear": "맑음", "Sunny": "맑음",
    "Partly cloudy": "구름 조금", "Cloudy": "흐림", "Overcast": "흐림",
    "Mist": "옅은 안개", "Fog": "안개", "Freezing fog": "안개(결빙)",
    "Patchy rain possible": "가끔 비", "Patchy rain nearby": "가끔 비",
    "Patchy snow possible": "가끔 눈", "Patchy sleet possible": "가끔 진눈깨비",
    "Patchy freezing drizzle possible": "가끔 어는 이슬비",
    "Thundery outbreaks possible": "천둥 가능",
    "Blowing snow": "눈보라", "Blizzard": "심한 눈보라",
    "Patchy light drizzle": "가벼운 이슬비", "Light drizzle": "가벼운 이슬비",
    "Freezing drizzle": "어는 이슬비", "Heavy freezing drizzle": "강한 어는 이슬비",
    "Patchy light rain": "가벼운 비", "Light rain": "가벼운 비",
    "Light rain shower": "가벼운 소나기",
    "Moderate rain at times": "약한 비", "Moderate rain": "보통 비",
    "Moderate or heavy rain shower": "소나기",
    "Heavy rain at times": "강한 비", "Heavy rain": "강한 비",
    "Torrential rain shower": "폭우",
    "Light freezing rain": "약한 어는 비", "Moderate or heavy freezing rain": "강한 어는 비",
    "Light sleet": "약한 진눈깨비", "Light sleet showers": "약한 진눈깨비 소나기",
    "Moderate or heavy sleet": "진눈깨비", "Moderate or heavy sleet showers": "진눈깨비 소나기",
    "Patchy light snow": "가벼운 눈", "Light snow": "가벼운 눈", "Light snow showers": "가벼운 눈 소나기",
    "Patchy moderate snow": "약한 눈", "Moderate snow": "보통 눈",
    "Patchy heavy snow": "강한 눈", "Heavy snow": "강한 눈", "Moderate or heavy snow showers": "강한 눈 소나기",
    "Ice pellets": "우박", "Light showers of ice pellets": "약한 우박",
    "Moderate or heavy showers of ice pellets": "강한 우박",
    "Patchy light rain with thunder": "천둥 동반 약한 비",
    "Moderate or heavy rain with thunder": "천둥 동반 비",
    "Patchy light snow with thunder": "천둥 동반 약한 눈",
    "Moderate or heavy snow with thunder": "천둥 동반 눈",
}

def _translate_weather_condition(condition: str) -> str:
    """wttr.in의 %C는 lang 파라미터와 무관하게 항상 영어(WWO 표준 코드)로 내려오므로,
    자주 나오는 조건 문구를 한국어로 매핑합니다. 매핑에 없는 문구는 원문 그대로 둡니다."""
    return _WEATHER_CONDITION_KR.get(condition.strip(), condition.strip())

def get_current_weather(location: str = "안성시") -> str:
    try:
        url = f"https://wttr.in/{urllib.parse.quote(location)}?format=%C|%t|%w&lang=ko"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            raw = response.read().decode('utf-8').strip()
            fields = (raw.split('|') + ['', '', ''])[:3]
            condition_raw, temp, wind = [f.strip() for f in fields]
            condition_kr = _translate_weather_condition(condition_raw)
            result = " ".join(part for part in (condition_kr, temp, wind) if part)
            return f"{location}의 현재 날씨 상태는 {result} 입니다."
    except Exception:
        return f"{location}의 실시간 날씨 정보를 가져오는 도중 네트워크 오류가 발생했습니다."

def get_daily_briefing(location: str = "안성시") -> str:
    """아침 인사, 날씨, 오늘의 대기 퀘스트, 긍정 기억 하나를 묶은 데일리 브리핑.
    데이터 조회는 기존 함수(get_current_weather, memory_db.*)를 그대로 재사용하고,
    문구 조합만 productivity.productivity_manager로 위임합니다."""
    hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        greeting = "좋은 아침입니다, Master."
    elif 12 <= hour < 18:
        greeting = "좋은 오후입니다, Master."
    else:
        greeting = "늦은 시간까지 고생 많으십니다, Master."

    weather_text = get_current_weather(location=location)
    quest_text = memory_db.get_pending_quests()

    anchor_text = None
    try:
        anchors = memory_db.get_positive_anchors_raw(limit=10)
        if anchors:
            chosen = random.choice(anchors)
            anchor_text = f"{chosen['emotion_tag']} {chosen['content']}"
    except Exception:
        anchor_text = None

    return build_daily_briefing_text(
        greeting=greeting,
        weather_text=weather_text,
        quest_text=quest_text,
        anchor_text=anchor_text,
    )

def play_youtube_music(query: str = "조용한 음악 플레이리스트") -> str:
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
        webbrowser.open(url)
        return f"유튜브에서 '{query}' 검색 결과를 웹 브라우저로 열었습니다."
    except Exception as e:
        return f"유튜브 열기 중 오류 발생: {e}"

def find_and_open_shortcut(target_name: str) -> bool:
    search_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%USERPROFILE%\Desktop"),
        os.path.expandvars(r"%USERPROFILE%\바탕 화면"),
        os.path.expandvars(r"%PUBLIC%\Desktop"),
    ]
    translation_map = {"림버스": "limbus", "카카오톡": "kakaotalk", "크롬": "chrome"}
    raw_target = target_name.lower().replace(" ", "")
    search_keyword = translation_map.get(raw_target, raw_target)
    
    for base_dir in search_dirs:
        if not os.path.exists(base_dir):
            continue
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".lnk") or file.endswith(".url"):
                    file_name_clean = os.path.splitext(file)[0].lower().replace(" ", "")
                    if search_keyword in file_name_clean:
                        try:
                            os.startfile(os.path.join(root, file))
                            return True
                        except Exception:
                            pass
    return False

BLOCKED_KEYWORDS = ["cmd", "명령프롬프트", "powershell", "regedit", "레지스트리", "제어판", "taskmgr", "작업관리자"]
SAFE_LIST = {
    "메모장": "notepad.exe",
    "notepad": "notepad.exe",
    "계산기": "calc.exe",
    "calc": "calc.exe",
}

def open_program(target: str, confirmed: bool = False, state: SessionState = None) -> str:
    target_str = target.lower().replace(" ", "")

    if any(b in target_str for b in BLOCKED_KEYWORDS):
        return "보안 정책상 터미널 및 시스템 제어 프로그램은 실행할 수 없습니다."

    if target_str in SAFE_LIST:
        try:
            subprocess.Popen(SAFE_LIST[target_str], shell=True)
            return f"{target}을(를) 실행했습니다."
        except Exception as e:
            return f"'{target}' 실행 중 오류가 발생했습니다: {e}"

    if not confirmed:
        return (
            f"REQUIRES_CONFIRMATION: '{target}'은(는) 화이트리스트에 없는 프로그램입니다. "
            "Master에게 정말 실행할지 음성으로 다시 여쭤보고, 확인을 받으면 "
            "confirmed=true로 다시 호출하세요."
        )

    if find_and_open_shortcut(target_str):
        return f"'{target}'을(를) 실행했습니다."
    return f"'{target}' 단축 아이콘을 찾을 수 없습니다."


_LOCATION_ALIASES = {
    "바탕화면": r"%USERPROFILE%\Desktop",
    "데스크탑": r"%USERPROFILE%\Desktop",
    "desktop": r"%USERPROFILE%\Desktop",
    "문서": r"%USERPROFILE%\Documents",
    "documents": r"%USERPROFILE%\Documents",
    "다운로드": r"%USERPROFILE%\Downloads",
    "다운로드폴더": r"%USERPROFILE%\Downloads",
    "downloads": r"%USERPROFILE%\Downloads",
    "내pc": r"%USERPROFILE%",
    "내컴퓨터": r"%USERPROFILE%",
    "c드라이브": "C:\\",
    "d드라이브": "D:\\",
}


def _resolve_location(location: str) -> str:
    """
    Master가 말한 위치 표현을 실제 폴더 경로로 변환한다.

    1) "바탕화면", "C드라이브" 같은 흔한 한국어 표현은 별칭 매핑으로 바로 변환.
    2) 별칭에 없으면, 사용자가 실제 경로 자체를 말했을 가능성이 있으므로
       환경변수/사용자 홈 확장을 시도해 그대로 써본다 (존재 여부는 호출부에서 확인).
    """
    loc_clean = location.strip().lower().replace(" ", "")
    for alias, path in _LOCATION_ALIASES.items():
        if alias in loc_clean:
            return os.path.expandvars(path)
    return os.path.expandvars(os.path.expanduser(location.strip()))


# 직전 검색 결과 캐시: {(query, location): [전체 경로, ...]}. "REQUIRES_CONFIRMATION"으로
# 후보를 보여준 뒤, Master가 confirmed=true로 다시 호출할 때 검색을 처음부터 다시 돌리지
# 않고 이 캐시를 그대로 쓴다. 검색을 두 번 따로 실행하면(특히 C드라이브처럼 넓은 범위)
# os.walk 순서가 완전히 같으리라는 보장이 없어서, 사용자에게 보여준 파일과 실제로 열리는
# 파일이 달라지거나(혹은 그 사이 다른 파일이 없어져서) "파일이 사라졌다"는 혼란스러운
# 오류로 이어질 수 있었다.
_file_search_cache: dict = {}


def find_and_open_file(query: str, location: str = "", confirmed: bool = False) -> str:
    """
    파일 또는 폴더 이름에 query가 포함된 항목을 찾는다.

    location이 주어지면(예: "바탕화면", "다운로드", "C:\\프로젝트") 그 위치를 최우선으로,
    더 깊이(하위 5단계까지) 검색한다 — Master가 직접 위치를 짚어준 경우이므로 신뢰도가
    높다고 보고 기본 검색보다 범위를 넓힌다. location이 없으면 기존처럼 바탕화면/문서/
    다운로드 기본 위치를 하위 3단계까지 훑는다.

    open_program과 동일한 2단계 확인 절차를 따른다: 처음엔 후보 목록만 보여주고
    (REQUIRES_CONFIRMATION), Master의 명확한 승낙을 받은 뒤에만 실제로 연다.
    """
    cache_key = (query.lower().strip(), location.lower().strip())

    if confirmed and cache_key in _file_search_cache:
        # 처음 보여줬던 그 목록을 그대로 쓴다 (재검색 안 함).
        matches = _file_search_cache.pop(cache_key)
    else:
        default_dirs = [
            os.path.expandvars(r"%USERPROFILE%\Desktop"),
            os.path.expandvars(r"%USERPROFILE%\바탕 화면"),
            os.path.expandvars(r"%USERPROFILE%\Documents"),
            os.path.expandvars(r"%USERPROFILE%\문서"),
            os.path.expandvars(r"%USERPROFILE%\Downloads"),
            os.path.expandvars(r"%USERPROFILE%\다운로드"),
        ]

        search_targets = []  # (경로, 최대 탐색 깊이) 튜플 리스트
        if location:
            resolved = _resolve_location(location)
            search_targets.append((resolved, 5))
        search_targets.extend((d, 3) for d in default_dirs)

        query_clean = query.lower().replace(" ", "")
        if not query_clean:
            return "찾을 파일 이름을 알려주세요."

        def _search(term: str):
            """term(정규화된 검색어)로 파일/폴더를 찾는다. (결과 목록, 실제로 뒤진 경로가 있었는지)를 반환."""
            found = []
            searched = False
            for base_dir, max_depth in search_targets:
                if not os.path.exists(base_dir):
                    continue
                searched = True
                for root, dirs, files in os.walk(base_dir):
                    depth = root[len(base_dir):].count(os.sep)
                    if depth >= max_depth:
                        dirs[:] = []
                        continue

                    # 폴더도 검색 대상에 포함한다 — 예전엔 파일만 봐서 "OO 폴더 찾아줘"가
                    # 항상 실패하거나, 엉뚱한 파일을 폴더인 것처럼 돌려주는 문제가 있었다.
                    for d in dirs:
                        if term in d.lower().replace(" ", ""):
                            found.append(os.path.join(root, d))

                    for file in files:
                        name_no_ext = os.path.splitext(file)[0].lower().replace(" ", "")
                        name_with_ext = file.lower().replace(" ", "")
                        # 확장자를 포함해서 말한 경우("이력서.docx")와 안 한 경우("이력서")
                        # 둘 다 매칭되도록 두 형태 모두 비교한다.
                        if term in name_no_ext or term in name_with_ext:
                            found.append(os.path.join(root, file))

                if len(found) >= 10:
                    break
            return found, searched

        matches, searched_any = _search(query_clean)

        if not matches:
            # 정확한 이름으로 못 찾았다면, Master가 "이력서 파일 찾아줘"처럼 실제
            # 파일명에는 없는 군더더기 단어("파일"/"폴더"/"문서")를 검색어에 그대로
            # 포함해서 말했을 가능성이 있다. 그 단어들을 지우고 한 번 더 시도한다.
            stripped = query_clean
            for filler in ("파일", "폴더", "문서"):
                stripped = stripped.replace(filler, "")
            if stripped and stripped != query_clean:
                retry_matches, retry_searched = _search(stripped)
                matches = retry_matches
                searched_any = searched_any or retry_searched

        if not matches:
            if location and not searched_any:
                return f"'{location}' 경로를 찾을 수 없었습니다. 정확한 폴더명이나 경로를 다시 말씀해주세요."
            where = f"'{location}'과 기본 폴더(바탕화면/문서/다운로드)" if location else "바탕화면/문서/다운로드"
            return f"'{query}'와 일치하는 파일/폴더를 {where}에서 찾지 못했습니다."

        if not confirmed:
            _file_search_cache[cache_key] = matches
            preview = "\n".join(
                f"- {'📁' if os.path.isdir(m) else '📄'} {os.path.basename(m)}" for m in matches[:5]
            )
            more = f" (외 {len(matches) - 5}개 더)" if len(matches) > 5 else ""
            return (
                f"REQUIRES_CONFIRMATION: '{query}'로 다음 파일/폴더를 찾았습니다:\n{preview}{more}\n"
                "Master에게 어떤 걸 열지, 정말 열지 확인한 뒤 confirmed=true로 다시 호출하세요."
            )

    try:
        os.startfile(matches[0])
        kind = "폴더" if os.path.isdir(matches[0]) else "파일"
        return f"'{os.path.basename(matches[0])}' {kind}을(를) 열었습니다."
    except FileNotFoundError:
        # 검색 시점과 여는 시점 사이에 파일이 실제로 삭제/이동된 경우 (임시파일,
        # 설치 프로그램 캐시 등에서 특히 흔하다). 재검색을 유도하는 안내를 준다.
        return f"'{os.path.basename(matches[0])}' 항목이 그 사이 삭제되거나 이동된 것 같습니다. 다시 검색해볼까요?"
    except Exception as e:
        return f"파일을 여는 중 오류가 발생했습니다: {e}"

# ---------------------------------------------------------------------------
# CustomTkinter GUI 클래스 정의
# ---------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────────────────
# 아이콘 로더 (Lucide PNG → CTkImage)
#
# assets/icons/{name}.png가 있으면 그걸 불러오고, 없으면 None을 반환해서
# 호출부가 이모지로 자연스럽게 폴백하게 한다. 이러면 아이콘 파일을 아직
# 준비 못 한 상태로 개발을 계속해도 앱이 깨지지 않고, 나중에 파일만
# assets/icons/에 넣으면 재시작 시 자동으로 교체된다 (코드 수정 불필요).
#
# 주의: PyInstaller로 빌드된 .exe에서는 __file__이 실제 .exe 위치가 아니라
# 내부 번들 경로를 가리킬 수 있다. sys.frozen일 때는 sys.executable 기준으로
# 경로를 잡아야, 사용자가 .exe 바로 옆에 놓은 assets 폴더를 정확히 찾는다.
# ─────────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _APP_BASE_DIR = os.path.dirname(sys.executable)
else:
    _APP_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ICON_DIR = os.path.join(_APP_BASE_DIR, "assets", "icons")
_icon_cache: dict = {}


def load_icon(name: str, size: int = 20, faded: bool = False):
    """
    assets/icons/{name}.png를 CTkImage로 불러온다. 파일이 없거나 로드에
    실패하면 None을 반환한다 — 호출부는 반드시 `image or None`을 받아서
    None이면 이모지 text만 쓰는 기존 방식으로 자연스럽게 동작해야 한다.

    faded=True면 알파(투명도)를 크게 낮춰서 반환한다 — 빈 상태(empty state)
    화면에서 배경처럼 은은하게 깔아둘 큰 아이콘용. 일반 아이콘과는 별도로
    캐시해서 서로 안 섞인다.
    """
    cache_key = (name, size, faded)
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]

    if not PIL_AVAILABLE:
        _icon_cache[cache_key] = None
        return None

    path = os.path.join(_ICON_DIR, f"{name}.png")
    if not os.path.exists(path):
        _icon_cache[cache_key] = None
        return None

    try:
        img = Image.open(path).convert("RGBA")
        if faded:
            r, g, b, a = img.split()
            a = a.point(lambda p: int(p * 0.16))
            img = Image.merge("RGBA", (r, g, b, a))
        icon = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        _icon_cache[cache_key] = icon
        return icon
    except Exception as e:
        print(f"⚠️ [Icon Load Error] {name}: {e}")
        _icon_cache[cache_key] = None
        return None


class ToolTip:
    """
    CTk 위젯에 호버 시 뜨는 작은 플로팅 툴팁.

    CustomTkinter엔 내장 툴팁이 없어서 직접 구현한다. 커서가 위젯 위에 일정
    시간(delay_ms) 머물러야 뜨고, 벗어나면 즉시 사라진다 — 즉시 뜨게 하면
    마우스가 잠깐 스쳐 지나갈 때도 깜빡여서 오히려 산만해진다.

    아이콘 전용(텍스트 없는) 헤더 버튼들에 이름을 붙일 때 쓴다: 버튼 자체엔
    이모지만 남기고, 무슨 기능인지는 호버해야 보이게 해서 헤더를 더 정돈되고
    간결하게 만든다.
    """
    def __init__(self, widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip_window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._cancel_scheduled()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel_scheduled(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tw = tkinter.Toplevel(self.widget)
        tw.wm_overrideredirect(True)  # 제목표시줄/테두리 없이 순수 팝업처럼
        tw.attributes("-topmost", True)
        label = tkinter.Label(
            tw, text=self.text, justify="left",
            background="#1a1a2e", foreground="white",
            relief="solid", borderwidth=1,
            font=("Malgun Gothic", 10), padx=8, pady=4,
        )
        label.pack()
        # 위젯 중앙 아래에 배치하되, 화면 밖으로 안 나가게 살짝 보정
        tw.update_idletasks()
        tip_w = tw.winfo_width()
        x = max(0, x - tip_w // 2)
        tw.wm_geometry(f"+{x}+{y}")
        self._tip_window = tw

    def _hide(self, event=None):
        self._cancel_scheduled()
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None

    def update_text(self, new_text: str):
        """마이크 끄기/켜기처럼 상태에 따라 문구가 바뀌는 버튼의 툴팁을 갱신한다."""
        self.text = new_text


class ONyuulGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # customtkinter의 알려진 코스메틱 버그 방지: CTkButton은 클릭 직후 몇 ms 뒤에
        # 내부적으로 .focus()를 다시 거는 동작을 after()로 예약해두는데, 그 사이
        # 다이얼로그(CTkToplevel)가 이미 destroy()되면 "invalid command name"
        # TclError가 난다. 기능은 이미 끝난 뒤라 실질적 영향이 없는 무해한 오류라,
        # 여기서만 조용히 무시하고 나머지 진짜 예외는 그대로 콘솔에 남긴다.
        self.report_callback_exception = self._handle_tk_exception

        self.title("온율 (ONyuul) - AI Companion & Mind Care")
        self.geometry("980x680")
        self.minsize(900, 600)

        self.app_state = SessionState()
        self.selected_voice = "Aoede"
        self.night_mode_override = "AUTO"
        self.async_session = None
        self.chart_canvas = None
        self.chart_days = 7
        self._pulse_running = False
        self._pulse_t = 0.0
        self.chat_font_size = 14  # 채팅창 폰트 크기 (사용자가 A-/A+로 조절)
        self._new_msg_badge = None  # 과거 로그를 보고 있을 때 뜨는 "새 메시지" 배지
        self.recent_wake_misses = []  # 대기 모드 중 웨이크워드로 인식 못 한 최근 발화 (최대 15개)
        self.tray_icon = None  # 트레이 최소화 시 생성되는 pystray.Icon 인스턴스
        self._pending_undo = None  # 실행취소 대기 중인 삭제 작업
        self._undo_toast_widget = None
        self.tts_volume = config_manager.get_tts_volume()  # 저장된 온율 음성 볼륨 (기본 100%)
        self.reconnect_event = None  # asyncio.Event, start_async_pipeline이 app_loop 위에서 생성
        self.app_loop_ref = None     # 재연결 트리거를 위해 call_soon_threadsafe로 접근할 이벤트 루프

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._confirm_close_dialog)
        self.after(500, self._auto_theme_tick)  # AUTO 모드 야간/주간 테마 동기화 시작
        self.after(5000, self._reminder_check_tick)  # 알림/일정 체크 루프 시작
        self.after(10000, self._safety_plan_check_tick)  # 안전 계획 정기 점검 루프 시작
        self.after(3000, self.check_for_updates)  # 시작 3초 뒤 업데이트 확인 (한 번만)

    def _handle_tk_exception(self, exc_type, exc_value, exc_tb):
        """
        Tkinter의 report_callback_exception 훅.

        customtkinter 위젯(특히 CTkButton)이 클릭 직후 몇 ms 뒤로 예약해둔 내부
        .focus() 호출이, 그 사이 부모 다이얼로그가 destroy()된 상태에서 실행되면
        "TclError: invalid command name ...!ctkbutton...!ctkcanvas" 형태로 터진다.
        이 시점엔 사용자가 요청한 동작(버튼 커맨드)은 이미 끝난 뒤라 실질적인
        영향이 없는, 위젯 생명주기상의 알려진 코스메틱 버그다. 이것만 조용히
        무시하고, 그 외의 예외는 디버깅을 위해 그대로 콘솔에 남긴다.
        """
        if issubclass(exc_type, tkinter.TclError) and "invalid command name" in str(exc_value):
            return
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_tb)

    def _render_empty_state(self, parent, icon_name: str, message: str):
        """
        목록이 비어있을 때 흐릿한 큰 아이콘 + 안내 텍스트를 함께 보여주는 공통
        헬퍼. 아이콘 파일이 없으면 텍스트만 나오는 기존 방식으로 자연스럽게
        폴백한다 — 화면이 휑해 보이지 않게 하는 목적의 장식이라, 실패해도
        기능엔 전혀 영향 없다.
        """
        icon = load_icon(icon_name, size=64, faded=True)
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", pady=(30, 10))
        if icon:
            ctk.CTkLabel(container, fg_color="transparent", image=icon, text="").pack(pady=(0, 12))
        ctk.CTkLabel(
            container, fg_color="transparent", text=message,
            text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY),
            justify="center" if icon else "left", wraplength=420,
        ).pack(padx=10)

    def _set_tab_badge(self, frame, show: bool):
        """지정된 탭 프레임에 대응하는 아이콘 버튼 우측 상단에 작은 빨간 점을
        띄우거나(show=True) 지운다(show=False). 이미 원하는 상태면 아무것도 안 한다."""
        btn = self._tab_buttons.get(frame)
        if btn is None:
            return
        existing = self._tab_badges.get(frame)
        if show and existing is None:
            dot = ctk.CTkLabel(
                self.tab_sidebar, text="", fg_color=COLOR_DANGER, corner_radius=5,
                width=10, height=10,
            )
            dot.place(in_=btn, relx=1.0, rely=0.0, x=-2, y=2, anchor="ne")
            self._tab_badges[frame] = dot
        elif not show and existing is not None:
            existing.destroy()
            self._tab_badges[frame] = None

    def _update_tab_badges(self):
        """
        알림/할 일 탭에 지금 확인이 필요한 항목이 있으면 배지를 켠다.
        - 알림: 지금 당장 전달돼야 하는(마감이 지난) 알림이 있을 때
        - 할 일: 마감이 지난(overdue) 항목이 있을 때
        실패해도 조용히 넘어간다 — 배지는 부가 기능이라 이것 때문에 앱이
        죽으면 안 된다.
        """
        try:
            has_due_reminder = len(reminder_db.get_due_reminders()) > 0
        except Exception:
            has_due_reminder = False
        self._set_tab_badge(self.tab_reminders, has_due_reminder)

        try:
            has_overdue_task = len(task_db.get_overdue_tasks()) > 0
        except Exception:
            has_overdue_task = False
        self._set_tab_badge(self.tab_tasks, has_overdue_task)

    def switch_tab(self, target_frame):
        """
        자체 제작 탭 시스템의 전환 로직. 나머지 프레임은 화면에서 내리고
        선택된 프레임만 채워서 보여준다. 현재 선택된 탭은 배경색을 켜서
        표시한다 — 아이콘만 있고 텍스트가 없는 탭바라, 지금 어디 있는지
        시각적으로 알려주는 게 중요하다.
        """
        for frame in self._tab_frames:
            frame.pack_forget()
        target_frame.pack(fill="both", expand=True)

        for frame, btn in self._tab_buttons.items():
            if frame is target_frame:
                btn.configure(fg_color=COLOR_PRIMARY)
            else:
                btn.configure(fg_color="transparent")

    def _add_left_panel_divider(self):
        """좌측 패널의 섹션(안전/빠른실행/진행현황/설정) 사이를 시각적으로 구분하는 얇은 선."""
        ctk.CTkFrame(self.left_panel, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=15, pady=8)

    def _build_ui(self):
        self.crisis_banner = ctk.CTkFrame(self, corner_radius=0, fg_color="#B03A2E", height=48)
        self.crisis_banner_label = ctk.CTkLabel(
            self.crisis_banner, fg_color="transparent",
            text="🚨 안전 안내를 전달하고 있습니다 — 지금 힘드시다면 109(자살예방) / 1577-0199(정신건강위기)로 연결하세요",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"),
            text_color="white",
        )
        self.crisis_banner_label.pack(pady=12)

        # 🔌 연결 끊김 배너 (평소엔 숨김). 세션이 예기치 않게 끊기면 조용히 죽는 대신
        # 이 배너로 알리고, 재연결 버튼으로 사용자가 직접 다시 연결할 수 있게 한다.
        self.reconnect_banner = ctk.CTkFrame(self, corner_radius=0, fg_color="#B9770E", height=48)
        self.reconnect_banner_label = ctk.CTkLabel(
            self.reconnect_banner, fg_color="transparent", image=load_icon("unplug", size=16), compound="left", text=("연결이 끊겼습니다." if load_icon("unplug", size=16) else "🔌 연결이 끊겼습니다."),
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white",
        )
        self.reconnect_banner_label.pack(side="left", padx=(15, 10), pady=8)
        self.reconnect_btn = ctk.CTkButton(
            self.reconnect_banner, text=("재연결" if load_icon("refresh-cw", size=14) else "🔄 재연결"), image=load_icon("refresh-cw", size=14), compound="left", width=110, height=30,
            fg_color=COLOR_SUCCESS, text_color="white", hover_color=COLOR_SUCCESS_BTN, command=self.trigger_reconnect,
        )
        self.reconnect_btn.pack(side="left", pady=8)

        # 🎉 새 버전 알림 배너 (평소엔 숨김)
        self.update_banner = ctk.CTkFrame(self, corner_radius=0, fg_color=COLOR_SUCCESS_BTN, height=48)
        self.update_banner_label = ctk.CTkLabel(
            self.update_banner, fg_color="transparent", image=load_icon("sparkles", size=16), compound="left", text=("새 버전이 있습니다." if load_icon("sparkles", size=16) else "🎉 새 버전이 있습니다."),
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white",
        )
        self.update_banner_label.pack(side="left", padx=(15, 10), pady=8)
        self.update_download_btn = ctk.CTkButton(
            self.update_banner, text="⬇️ 다운로드", width=110, height=30,
            fg_color="#1a1a2e", hover_color="#0f0f1a", command=lambda: None,
        )
        self.update_download_btn.pack(side="left", pady=8)
        ctk.CTkButton(
            self.update_banner, text="나중에", width=70, height=30,
            fg_color="transparent", hover_color=COLOR_SUCCESS_BTN_HOVER,
            command=lambda: self.update_banner.pack_forget(),
        ).pack(side="left", padx=(4, 0), pady=8)

        self.header_frame = ctk.CTkFrame(self, corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=10)

        _title_icon = load_icon("bot", size=24)
        self.title_label = ctk.CTkLabel(
            self.header_frame, fg_color="transparent",
            text="온율 (ONyuul)" if _title_icon else "🤖 온율 (ONyuul)",
            image=_title_icon, compound="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_TITLE, weight="bold")
        )
        self.title_label.pack(side="left", padx=15, pady=10)

        self.mic_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.mic_frame.pack(side="left", padx=25, pady=10)

        self.mic_icon = ctk.CTkLabel(self.mic_frame, fg_color="transparent", text="🎙️", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION))
        self.mic_icon.pack(side="left", padx=(0, 8))

        self.mic_level_bar = ctk.CTkProgressBar(self.mic_frame, width=190, height=10, progress_color=COLOR_SUCCESS)
        self.mic_level_bar.pack(side="left")
        self.mic_level_bar.set(0.0)

        _mic_on_icon = load_icon("mic", size=18)
        self.mic_mute_btn = ctk.CTkButton(
            self.mic_frame, text="" if _mic_on_icon else "🎙️", image=_mic_on_icon, width=36, height=26,
            fg_color=COLOR_BORDER, text_color="white", hover_color=COLOR_NEUTRAL_HOVER, command=self.toggle_mic_mute,
        )
        self.mic_mute_btn.pack(side="left", padx=(12, 0))
        self.mic_mute_tooltip = ToolTip(self.mic_mute_btn, "마이크 끄기")

        _emergency_icon = load_icon("life-buoy", size=16)
        self.emergency_btn = ctk.CTkButton(
            self.header_frame, text="109 / 1577-0199" if _emergency_icon else "🆘 109 / 1577-0199",
            image=_emergency_icon, compound="left", width=150,
            fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
            command=self.on_emergency_button_click,
        )
        self.emergency_btn.pack(side="left", padx=10, pady=10)
        # 긴급 연락처는 안전 목적상 항상 텍스트가 보여야 하므로 아이콘 전용으로
        # 줄이지 않는다 — 그래도 마우스를 올렸을 때 무슨 동작인지는 알려준다.
        ToolTip(self.emergency_btn, "클릭하면 긴급 연락처가 클립보드에 복사됩니다")

        self.status_badge = ctk.CTkLabel(
            self.header_frame, fg_color="transparent", text="🟡 연결 준비 중...", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"),
            text_color=COLOR_WARNING_ALT
        )
        self.status_badge.pack(side="right", padx=15, pady=10)

        _settings_icon = load_icon("settings", size=18)
        self.settings_btn = ctk.CTkButton(
            self.header_frame, text="" if _settings_icon else "⚙", image=_settings_icon, width=36,
            fg_color=COLOR_BORDER, text_color="white", hover_color=COLOR_NEUTRAL_HOVER,
            command=lambda: self.open_api_key_dialog()
        )
        self.settings_btn.pack(side="right", padx=(0, 5), pady=10)
        ToolTip(self.settings_btn, "설정 (API 키 · 데이터 관리)")

        _wake_word_icon = load_icon("mic", size=18)
        self.wake_word_btn = ctk.CTkButton(
            self.header_frame, text="" if _wake_word_icon else "🗣️", image=_wake_word_icon, width=36,
            fg_color=COLOR_BORDER, text_color="white", hover_color=COLOR_NEUTRAL_HOVER,
            command=self.open_wake_word_dialog
        )
        self.wake_word_btn.pack(side="right", padx=(0, 5), pady=10)
        ToolTip(self.wake_word_btn, "웨이크워드 설정")

        _feedback_icon = load_icon("message-square", size=18)
        self.feedback_btn = ctk.CTkButton(
            self.header_frame, text="" if _feedback_icon else "📝", image=_feedback_icon, width=36,
            fg_color=COLOR_BORDER, text_color="white", hover_color=COLOR_NEUTRAL_HOVER,
            command=lambda: webbrowser.open(FEEDBACK_FORM_URL)
        )
        self.feedback_btn.pack(side="right", padx=(0, 5), pady=10)
        ToolTip(self.feedback_btn, "피드백 보내기")

        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=15, pady=5)

        # 좌측 패널 (안전 계획 등) — 가장 먼저 배치해서 맨 왼쪽에 오게 한다.
        self.left_panel = ctk.CTkFrame(self.main_container, width=300, corner_radius=10)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10), pady=0)

        # 세로 아이콘 탭바 — 좌측 패널 바로 다음(그 오른쪽)에 배치. 실제 아이콘
        # 버튼들은 콘텐츠 프레임들이 다 만들어진 뒤(이 파일 아래쪽)에 채워
        # 넣지만, 위치 자체는 여기서 먼저 pack해서 확보해둔다 (Tkinter의 pack은
        # 호출 순서대로 공간을 차지하므로, content_container보다는 먼저,
        # left_panel보다는 뒤에 와야 이 순서가 지켜진다).
        self.tab_sidebar = ctk.CTkFrame(self.main_container, width=52, corner_radius=10)
        self.tab_sidebar.pack(side="left", fill="y", padx=(0, 10))
        self.tab_sidebar.pack_propagate(False)

        # 💡 [1순위 신규] 나만의 안전 계획 설정 버튼
        _shield_icon = load_icon("shield", size=18)
        self.btn_safety_plan = ctk.CTkButton(
            self.left_panel, text="나의 안전 계획 작성/조회" if _shield_icon else "🛡️ 나의 안전 계획 작성/조회",
            image=_shield_icon, compound="left",
            fg_color="#C0392B", hover_color=COLOR_DANGER_BTN, 
            command=self.open_safety_plan_modal
        )
        self.btn_safety_plan.pack(fill="x", padx=15, pady=(15, 10))
        ToolTip(self.btn_safety_plan, "언제든 나만의 대처법과 비상연락처를 확인·수정할 수 있어요")

        self._add_left_panel_divider()

        # ⚡ 빠른 실행 — 자주 누르는 액션 버튼들을 한데 모아 상단에 배치
        _zap_icon = load_icon("zap", size=16)
        ctk.CTkLabel(
            self.left_panel, fg_color="transparent", text="빠른 실행" if _zap_icon else "⚡ 빠른 실행",
            image=_zap_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"),
        ).pack(anchor="w", padx=15, pady=(5, 5))

        _moon_icon = load_icon("moon", size=18)
        self.standby_btn = ctk.CTkButton(
            self.left_panel, text="대기 모드 전환" if _moon_icon else "💤 대기 모드 전환",
            image=_moon_icon, compound="left",
            fg_color=COLOR_DANGER, text_color="white", hover_color="#C0392B", command=self.toggle_standby
        )
        self.standby_btn.pack(fill="x", padx=15, pady=4)
        ToolTip(self.standby_btn, "마이크는 계속 듣되, '온율아'라고 부르기 전까진 반응하지 않아요")

        _wind_icon = load_icon("wind", size=18)
        self.btn_breathing = ctk.CTkButton(
            self.left_panel, text="4-7-8 호흡 가이드" if _wind_icon else "🧘 4-7-8 호흡 가이드",
            image=_wind_icon, compound="left",
            fg_color="#2980B9", hover_color="#1F618D", command=self.trigger_breathing
        )
        self.btn_breathing.pack(fill="x", padx=15, pady=4)
        ToolTip(self.btn_breathing, "들이쉬기 4초 · 참기 7초 · 내쉬기 8초로 온율이가 직접 리드해드려요")

        _anchor_icon = load_icon("anchor", size=18)
        self.btn_grounding = ctk.CTkButton(
            self.left_panel, text="마음 안정 가이드" if _anchor_icon else "⚓ 마음 안정 가이드",
            image=_anchor_icon, compound="left",
            fg_color="#8E44AD", hover_color="#6C3483", command=self.trigger_grounding
        )
        self.btn_grounding.pack(fill="x", padx=15, pady=4)
        ToolTip(self.btn_grounding, "지금 이 순간에 집중하도록 도와주는 감각 안정화 기법이에요")

        _sunrise_icon = load_icon("sunrise", size=18)
        self.btn_daily_briefing = ctk.CTkButton(
            self.left_panel, text="굿모닝 브리핑" if _sunrise_icon else "🌅 굿모닝 브리핑",
            image=_sunrise_icon, compound="left",
            fg_color="#D68910", hover_color="#B9770E", command=self.trigger_daily_briefing
        )
        self.btn_daily_briefing.pack(fill="x", padx=15, pady=(4, 15))
        ToolTip(self.btn_daily_briefing, "날씨, 오늘의 할 일, 최근 긍정적인 순간을 한 번에 정리해드려요")

        self._add_left_panel_divider()

        # 🎯 진행 현황
        _target_icon = load_icon("target", size=16)
        self.quest_label = ctk.CTkLabel(
            self.left_panel, fg_color="transparent", text="행동 활성화 진행률" if _target_icon else "🎯 행동 활성화 진행률",
            image=_target_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"),
        )
        self.quest_label.pack(anchor="w", padx=15, pady=(5, 5))

        self.quest_progress_bar = ctk.CTkProgressBar(self.left_panel, height=12, progress_color=COLOR_WARNING)
        self.quest_progress_bar.pack(fill="x", padx=15, pady=(0, 5))
        self.quest_progress_bar.set(0.0)

        self.quest_progress_label = ctk.CTkLabel(self.left_panel, fg_color="transparent", text="완료한 퀘스트 0 / 0", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_DISABLED)
        self.quest_progress_label.pack(anchor="w", padx=15, pady=(0, 15))

        self._add_left_panel_divider()

        # ⚙️ 설정 — 자주 안 바꾸는 항목들은 맨 아래로 모음
        _settings_section_icon = load_icon("settings", size=16)
        ctk.CTkLabel(
            self.left_panel, fg_color="transparent", text="설정" if _settings_section_icon else "⚙️ 설정",
            image=_settings_section_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"),
        ).pack(anchor="w", padx=15, pady=(5, 8))

        _mic_label_icon = load_icon("mic", size=14)
        self.voice_label = ctk.CTkLabel(
            self.left_panel, fg_color="transparent", text="TTS 목소리 선택" if _mic_label_icon else "🗣️ TTS 목소리 선택",
            image=_mic_label_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL),
        )
        self.voice_label.pack(anchor="w", padx=15, pady=(0, 3))

        self.voice_option = ctk.CTkOptionMenu(
            self.left_panel, 
            values=["Aoede (밝은 여성)", "Kore (부드러운 여성)", "Puck (경쾌한 남성)", "Fenrir (신뢰감 남성)", "Charon (중후한 남성)"],
            command=self.on_voice_change
        )
        self.voice_option.pack(fill="x", padx=15, pady=(0, 12))

        _moon_label_icon = load_icon("moon", size=14)
        self.mode_label = ctk.CTkLabel(
            self.left_panel, fg_color="transparent", text="주/야간 케어 모드" if _moon_label_icon else "🌙 주/야간 케어 모드",
            image=_moon_label_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL),
        )
        self.mode_label.pack(anchor="w", padx=15, pady=(0, 3))

        self.mode_var = ctk.StringVar(value="AUTO")
        self.radio_auto = ctk.CTkRadioButton(self.left_panel, text="자동 (밤 10시~새벽 6시)", variable=self.mode_var, value="AUTO", command=self.on_mode_change)
        self.radio_on = ctk.CTkRadioButton(self.left_panel, text="야간 모드 강제 ON", variable=self.mode_var, value="ON", command=self.on_mode_change)
        self.radio_off = ctk.CTkRadioButton(self.left_panel, text="주간 모드 강제 OFF", variable=self.mode_var, value="OFF", command=self.on_mode_change)
        
        self.radio_auto.pack(anchor="w", padx=20, pady=2)
        self.radio_on.pack(anchor="w", padx=20, pady=2)
        self.radio_off.pack(anchor="w", padx=20, pady=(2, 12))

        # 화면 테마 — 케어 모드(응답 톤)와 완전히 별개로 조절 가능하게 분리.
        # (예: 낮이라 케어 모드는 OFF지만 눈이 피곤해서 다크 테마만 쓰고 싶은 경우)
        _palette_icon = load_icon("palette", size=14)
        self.theme_label = ctk.CTkLabel(
            self.left_panel, fg_color="transparent", text="화면 테마" if _palette_icon else "🎨 화면 테마",
            image=_palette_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL),
        )
        self.theme_label.pack(anchor="w", padx=15, pady=(0, 3))

        self.theme_mode = config_manager.get_theme_mode()  # 저장된 값 불러오기 (기본 "AUTO")
        self.theme_selector = ctk.CTkSegmentedButton(
            self.left_panel, values=["다크", "라이트", "자동"], command=self.on_theme_change
        )
        theme_display_map = {"Dark": "다크", "Light": "라이트", "AUTO": "자동"}
        self.theme_selector.set(theme_display_map.get(self.theme_mode, "자동"))
        self.theme_selector.pack(fill="x", padx=15, pady=(0, 12))

        # 저장된 테마를 시작하자마자 즉시 반영 (AUTO/고정 모두). 이걸 안 하면
        # 모듈 로드 시 하드코딩된 기본 Dark 테마가 그대로 유지된 채, 사용자가
        # 저장해둔 Light/AUTO 선호가 다음 tick까지(또는 AUTO가 아니면 영원히) 반영 안 된다.
        if self.theme_mode == "AUTO":
            _now_hour = datetime.datetime.now().hour
            ctk.set_appearance_mode("Dark" if (_now_hour >= 22 or _now_hour < 6) else "Light")
        else:
            ctk.set_appearance_mode(self.theme_mode)

        self.autostart_var = ctk.BooleanVar(value=config_manager.is_autostart_enabled())
        self.autostart_checkbox = ctk.CTkCheckBox(
            self.left_panel, text="⏻ Windows 시작 시 자동 실행",
            variable=self.autostart_var, command=self.on_autostart_toggle,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL),
        )
        self.autostart_checkbox.pack(anchor="w", padx=15, pady=(0, 12))

        _volume_icon = load_icon("volume-2", size=14)
        self.volume_label = ctk.CTkLabel(
            self.left_panel, fg_color="transparent",
            text=f"온율 목소리 볼륨 {int(self.tts_volume * 100)}%" if _volume_icon else f"🔊 온율 목소리 볼륨 {int(self.tts_volume * 100)}%",
            image=_volume_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL),
        )
        self.volume_label.pack(anchor="w", padx=15, pady=(0, 3))

        self.volume_slider = ctk.CTkSlider(
            self.left_panel, from_=0.0, to=1.0, number_of_steps=20, command=self.on_volume_change,
        )
        self.volume_slider.set(self.tts_volume)
        self.volume_slider.pack(fill="x", padx=15, pady=(0, 15))

        # 우측 아이콘 전용 세로 탭바 + 콘텐츠 영역
        #
        # CTkTabview는 탭에 진짜 이미지 아이콘을 붙이는 공식 API가 없고, 이모지
        # 텍스트만으로는 Windows에서 컬러 폰트를 못 찾아 깨진 모양으로 렌더링되는
        # 문제가 있었다. CTkTabview 자체를 쓰지 않고, 이미 검증된 부품(load_icon +
        # ToolTip)만으로 "아이콘 버튼 클릭 → 해당 프레임만 보이기" 방식의 자체
        # 탭 시스템을 만들어서 이 한계를 원천적으로 피한다.
        #
        # tab_sidebar 프레임 자체는 이미 위(좌측 패널 바로 다음)에서 생성+배치
        # 해뒀다 — 여기서는 실제 아이콘 버튼들만 채워 넣는다. content_container는
        # 나머지 모든 공간을 채우도록 가장 마지막에 pack한다.
        self.content_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_container.pack(side="left", fill="both", expand=True)

        # 탭 순서: 실시간 대화(항상 첫 번째) → 정서 기록군(기분/사고/긍정기억/일기)
        # → 행동·생산성군(퀘스트/할일/알림) → 정보(참고용, 마지막)
        self.tab_chat = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_chart = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_thoughts = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_anchors = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_journal = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_quests = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_tasks = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_reminders = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_info = ctk.CTkFrame(self.content_container, fg_color="transparent")

        self._tab_frames = [
            self.tab_chat, self.tab_chart, self.tab_thoughts, self.tab_anchors,
            self.tab_journal, self.tab_quests, self.tab_tasks, self.tab_reminders, self.tab_info,
        ]

        # (프레임, Lucide 아이콘 이름, 이모지 폴백, 툴팁에 뜰 이름)
        tab_definitions = [
            (self.tab_chat, "message-circle", "💬", "실시간 대화"),
            (self.tab_chart, "bar-chart-2", "📊", "기분 리포트"),
            (self.tab_thoughts, "brain", "🧠", "사고기록 일지"),
            (self.tab_anchors, "star", "🌟", "긍정 기억"),
            (self.tab_journal, "book-open", "📔", "자유 일기"),
            (self.tab_quests, "target", "🎯", "퀘스트 일지"),
            (self.tab_tasks, "check-square", "✅", "할 일"),
            (self.tab_reminders, "bell", "⏰", "알림/일정"),
            (self.tab_info, "info", "ℹ️", "정보"),
        ]

        self._tab_buttons = {}
        for frame, icon_name, emoji_fallback, label in tab_definitions:
            icon = load_icon(icon_name, size=20)
            btn = ctk.CTkButton(
                self.tab_sidebar, text="" if icon else emoji_fallback, image=icon,
                width=40, height=40, corner_radius=8,
                fg_color="transparent", hover_color=COLOR_NEUTRAL_HOVER,
                command=lambda f=frame: self.switch_tab(f),
            )
            btn.pack(pady=4, padx=6)
            ToolTip(btn, label)
            self._tab_buttons[frame] = btn

        self._tab_badges = {}  # 탭 아이콘 우측 상단의 작은 알림 점 위젯들
        self.switch_tab(self.tab_chat)  # 기본 탭
        self.after(1000, self._update_tab_badges)  # 시작 직후 한 번 확인

        # 1. 대화 탭
        self.chat_font_bar = ctk.CTkFrame(self.tab_chat, fg_color="transparent")
        self.chat_font_bar.pack(fill="x", padx=5, pady=(5, 0))

        ctk.CTkLabel(self.chat_font_bar, fg_color="transparent", text="글자 크기", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color="#999999").pack(side="left", padx=(2, 8))
        ctk.CTkButton(self.chat_font_bar, text="A-", width=32, height=24, command=lambda: self.adjust_chat_font(-2)).pack(side="left", padx=2)
        ctk.CTkButton(self.chat_font_bar, text="A+", width=32, height=24, command=lambda: self.adjust_chat_font(2)).pack(side="left", padx=2)

        _eraser_icon = load_icon("eraser", size=14)
        ctk.CTkButton(
            self.chat_font_bar, text=("대화 지우기" if _eraser_icon else "🧹 대화 지우기"),
            image=_eraser_icon, compound="left", width=110, height=24,
            fg_color=COLOR_NEUTRAL_BTN, hover_color=COLOR_BORDER,
            command=self.clear_chat_log,
        ).pack(side="right", padx=2)

        self.chat_box = ctk.CTkTextbox(self.tab_chat, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION))
        self.chat_box.pack(fill="both", expand=True, padx=5, pady=5)
        self.chat_box.configure(state="disabled")

        # 발신자별 색상 태그. CTkTextbox의 tag_config는 font 옵션을 금지한다
        # (DPI 스케일링과 충돌 위험 때문에 customtkinter가 명시적으로 막아둠 —
        # AttributeError: 'font' option forbidden, because would be incompatible
        # with scaling). 그래서 굵게는 못 하고, foreground(색상)만으로 발신자를
        # 구분한다 — 색상 구분만으로도 목적은 충분히 달성된다.
        self.chat_box.tag_config("tag_master", foreground=COLOR_PRIMARY)
        self.chat_box.tag_config("tag_onyuul", foreground=COLOR_AI_ACCENT)
        self.chat_box.tag_config("tag_system", foreground=COLOR_TEXT_MUTED)
        self.chat_box.tag_config("tag_error", foreground=COLOR_DANGER)

        self.input_frame = ctk.CTkFrame(self.tab_chat, fg_color="transparent")
        self.input_frame.pack(fill="x", padx=5, pady=(5, 0))

        self.text_entry = ctk.CTkEntry(self.input_frame, placeholder_text="온율이에게 메시지 보내기...", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION))
        self.text_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.text_entry.bind("<Return>", lambda event: self.send_text_message())

        self.send_btn = ctk.CTkButton(self.input_frame, text="전송", width=70, command=self.send_text_message)
        self.send_btn.pack(side="right")

        # 2. 차트 탭
        self.chart_top_frame = ctk.CTkFrame(self.tab_chart, fg_color="transparent")
        self.chart_top_frame.pack(fill="x", padx=10, pady=5)

        self.chart_title = ctk.CTkLabel(self.chart_top_frame, fg_color="transparent", text="기분 변화 추이", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold"))
        self.chart_title.pack(side="left", padx=5)

        self.chart_period_selector = ctk.CTkSegmentedButton(
            self.chart_top_frame, values=["7일", "30일", "90일"], command=self.on_chart_period_change
        )
        self.chart_period_selector.set("7일")
        self.chart_period_selector.pack(side="left", padx=15)

        self.refresh_chart_btn = ctk.CTkButton(self.chart_top_frame, text=("차트 새로고침" if load_icon("refresh-cw", size=14) else "🔄 차트 새로고침"), image=load_icon("refresh-cw", size=14), compound="left", width=120, command=self.render_mood_chart)
        self.refresh_chart_btn.pack(side="right", padx=5)

        self.chart_container = ctk.CTkFrame(self.tab_chart)
        self.chart_container.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        self.emotion_tags_label = ctk.CTkLabel(
            self.tab_chart, fg_color="transparent", text="자주 나온 감정 키워드", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold")
        )
        self.emotion_tags_label.pack(anchor="w", padx=12, pady=(5, 2))

        self.emotion_tags_frame = ctk.CTkFrame(self.tab_chart, fg_color="transparent")
        self.emotion_tags_frame.pack(fill="x", padx=10, pady=(0, 10))

        # 3. 긍정 앵커 탭
        self.anchors_top_frame = ctk.CTkFrame(self.tab_anchors, fg_color="transparent")
        self.anchors_top_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(
            self.anchors_top_frame, fg_color="transparent", text="Master의 긍정 기억 조각들", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        ).pack(side="left", padx=5)

        self.refresh_anchors_btn = ctk.CTkButton(
            self.anchors_top_frame, text=("새로고침" if load_icon("refresh-cw", size=14) else "🔄 새로고침"), image=load_icon("refresh-cw", size=14), compound="left", width=110, command=self.render_positive_gallery
        )
        self.refresh_anchors_btn.pack(side="right", padx=5)

        self.anchors_scroll = ctk.CTkScrollableFrame(self.tab_anchors, fg_color="transparent")
        self.anchors_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 4. 퀘스트 일지 탭
        self.quests_top_frame = ctk.CTkFrame(self.tab_quests, fg_color="transparent")
        self.quests_top_frame.pack(fill="x", padx=10, pady=5)

        self.quests_title_label = ctk.CTkLabel(
            self.quests_top_frame, fg_color="transparent", image=load_icon("target", size=16), compound="left", text=("마이크로 퀘스트 성취 일지" if load_icon("target", size=16) else "🎯 마이크로 퀘스트 성취 일지"), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        )
        self.quests_title_label.pack(side="left", padx=5)

        self.refresh_quests_btn = ctk.CTkButton(
            self.quests_top_frame, text=("새로고침" if load_icon("refresh-cw", size=14) else "🔄 새로고침"), image=load_icon("refresh-cw", size=14), compound="left", width=110, command=self.render_quest_journal
        )
        self.refresh_quests_btn.pack(side="right", padx=5)

        # 수동 퀘스트 추가 입력창 (AI 분류에 의존하지 않고 직접 등록)
        self.quest_add_frame = ctk.CTkFrame(self.tab_quests, fg_color="transparent")
        self.quest_add_frame.pack(fill="x", padx=10, pady=(0, 5))

        self.quest_add_entry = ctk.CTkEntry(
            self.quest_add_frame, placeholder_text="새 퀘스트 제목 입력..."
        )
        self.quest_add_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.quest_add_entry.bind("<Return>", lambda e: self.manual_add_quest())

        self.quest_add_btn = ctk.CTkButton(
            self.quest_add_frame, text="+ 추가", width=80, command=self.manual_add_quest
        )
        self.quest_add_btn.pack(side="left")

        self.quests_scroll = ctk.CTkScrollableFrame(self.tab_quests, fg_color="transparent")
        self.quests_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 5. 사고기록 일지 탭
        self.thoughts_top_frame = ctk.CTkFrame(self.tab_thoughts, fg_color="transparent")
        self.thoughts_top_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(
            self.thoughts_top_frame, fg_color="transparent", image=load_icon("brain", size=16), compound="left", text=("함께 찾은 대안적 사고들" if load_icon("brain", size=16) else "🧠 함께 찾은 대안적 사고들"), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.thoughts_top_frame, text=("새로고침" if load_icon("refresh-cw", size=14) else "🔄 새로고침"), image=load_icon("refresh-cw", size=14), compound="left", width=110, command=self.render_thought_journal
        ).pack(side="right", padx=5)

        self.thoughts_scroll = ctk.CTkScrollableFrame(self.tab_thoughts, fg_color="transparent")
        self.thoughts_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 6. 알림/일정 탭
        ctk.CTkLabel(
            self.tab_reminders, fg_color="transparent", text="⏰ 복약 알림 및 일정", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        reminder_form = ctk.CTkFrame(self.tab_reminders, fg_color="transparent")
        reminder_form.pack(fill="x", padx=10, pady=(0, 5))

        self.reminder_title_entry = ctk.CTkEntry(reminder_form, placeholder_text="알림 제목 (예: 혈압약 복용)")
        self.reminder_title_entry.pack(fill="x", pady=(0, 5))

        row2 = ctk.CTkFrame(reminder_form, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 5))
        self.reminder_date_entry = ctk.CTkEntry(row2, placeholder_text="YYYY-MM-DD", width=140)
        self.reminder_date_entry.pack(side="left", padx=(0, 5))
        self.reminder_time_entry = ctk.CTkEntry(row2, placeholder_text="HH:MM", width=100)
        self.reminder_time_entry.pack(side="left", padx=(0, 5))

        self.reminder_kind_var = ctk.StringVar(value="일정")
        ctk.CTkSegmentedButton(row2, values=["일정", "복약"], variable=self.reminder_kind_var).pack(side="left", padx=(5, 0))

        row3 = ctk.CTkFrame(reminder_form, fg_color="transparent")
        row3.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(row3, fg_color="transparent", text="반복:", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL)).pack(side="left", padx=(0, 5))
        self.reminder_repeat_var = ctk.StringVar(value="없음")
        ctk.CTkSegmentedButton(row3, values=["없음", "매일", "매주"], variable=self.reminder_repeat_var).pack(side="left")
        ctk.CTkButton(row3, text="+ 알림 등록", command=self.manual_add_reminder).pack(side="right")

        ctk.CTkLabel(
            self.tab_reminders, fg_color="transparent", text="등록된 알림", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 2))

        self.reminders_scroll = ctk.CTkScrollableFrame(self.tab_reminders, fg_color="transparent")
        self.reminders_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 7. 할 일 탭
        ctk.CTkLabel(
            self.tab_tasks, fg_color="transparent", image=load_icon("check-square", size=16), compound="left", text=("마감 있는 할 일" if load_icon("check-square", size=16) else "✅ 마감 있는 할 일"), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        task_form = ctk.CTkFrame(self.tab_tasks, fg_color="transparent")
        task_form.pack(fill="x", padx=10, pady=(0, 5))

        self.task_title_entry = ctk.CTkEntry(task_form, placeholder_text="할 일 (예: 보고서 제출)")
        self.task_title_entry.pack(fill="x", pady=(0, 5))

        task_row2 = ctk.CTkFrame(task_form, fg_color="transparent")
        task_row2.pack(fill="x", pady=(0, 8))
        self.task_due_entry = ctk.CTkEntry(task_row2, placeholder_text="YYYY-MM-DD (선택)", width=160)
        self.task_due_entry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(task_row2, fg_color="transparent", text="우선순위:", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL)).pack(side="left", padx=(0, 5))
        self.task_priority_var = ctk.StringVar(value="보통")
        ctk.CTkSegmentedButton(task_row2, values=["낮음", "보통", "높음"], variable=self.task_priority_var).pack(side="left")
        ctk.CTkButton(task_row2, text="+ 할 일 추가", command=self.manual_add_task).pack(side="right")

        ctk.CTkLabel(
            self.tab_tasks, fg_color="transparent", text="미완료 할 일", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 2))

        self.tasks_scroll = ctk.CTkScrollableFrame(self.tab_tasks, fg_color="transparent")
        self.tasks_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 8. 정보 탭
        info_scroll = ctk.CTkScrollableFrame(self.tab_info, fg_color="transparent")
        info_scroll.pack(fill="both", expand=True, padx=15, pady=15)

        # 치료 대체 아님 고지 — 가장 눈에 띄게, 항상 맨 위에
        disclaimer_card = ctk.CTkFrame(info_scroll, fg_color="#5D3A00", corner_radius=10)
        disclaimer_card.pack(fill="x", pady=(0, 15))
        _disclaimer_icon = load_icon("triangle-alert", size=18)
        ctk.CTkLabel(
            disclaimer_card, fg_color="transparent",
            text="온율은 전문적인 심리 치료·상담을 대체하지 않습니다" if _disclaimer_icon else "⚠️ 온율은 전문적인 심리 치료·상담을 대체하지 않습니다",
            image=_disclaimer_icon, compound="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"), text_color="#FFD27A", wraplength=490, justify="left",
        ).pack(anchor="w", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            disclaimer_card, fg_color="transparent",
            text="온율은 정서적 지지와 CBT 원리를 활용한 대화를 통해 일상적인 마음 돌봄을 "
                 "돕는 동반자 도구입니다. 의사, 상담사, 심리 치료 전문가의 진단·치료를 "
                 "대체할 수 없으며, 지속적으로 힘든 시간이 이어진다면 전문가와 상담해보시길 "
                 "권해드립니다.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color="#E8C99A", wraplength=520, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # 긴급 연락처 (여기서도 항상 볼 수 있게)
        contact_card = ctk.CTkFrame(info_scroll, fg_color=COLOR_CARD_BG, corner_radius=10)
        contact_card.pack(fill="x", pady=(0, 15))
        _lifebuoy_icon = load_icon("life-buoy", size=16)
        ctk.CTkLabel(
            contact_card, fg_color="transparent", text="도움이 필요하시다면" if _lifebuoy_icon else "🆘 도움이 필요하시다면",
            image=_lifebuoy_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white",
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            contact_card, fg_color="transparent",
            text="자살예방상담전화 109 (24시간)\n정신건강 위기상담전화 1577-0199 (24시간)\n긴급 상황 112",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_SECONDARY, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # 이 앱이 하는 일 / 안 하는 일
        scope_card = ctk.CTkFrame(info_scroll, fg_color=COLOR_CARD_BG, corner_radius=10)
        scope_card.pack(fill="x", pady=(0, 15))
        _bot_scope_icon = load_icon("bot", size=16)
        ctk.CTkLabel(scope_card, fg_color="transparent", text="온율이 할 수 있는 것" if _bot_scope_icon else "🤖 온율이 할 수 있는 것", image=_bot_scope_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white").pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            scope_card, fg_color="transparent",
            text="• 공감하는 대화와 소크라테스식 질문을 통한 CBT식 인지 재구성\n"
                 "• 기분·수면·사고기록 등 정서 기록 관리\n"
                 "• 행동 활성화(마이크로 퀘스트)와 긍정 기억 아카이빙\n"
                 "• 복약/일정 알림, 할 일 관리, 파일 검색 등 일상 비서 기능",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_SECONDARY, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))
        _ban_icon = load_icon("ban", size=16)
        ctk.CTkLabel(scope_card, fg_color="transparent", text="온율이 할 수 없는 것" if _ban_icon else "🚫 온율이 할 수 없는 것", image=_ban_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white").pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            scope_card, fg_color="transparent",
            text="• 의학적/심리적 진단이나 처방\n• 응급 상황에서의 실제 개입 (위기 시 반드시 109/112 등 실제 기관에 연락)\n"
                 "• 전문 상담사·의료진과의 정기적인 치료 관계",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_SECONDARY, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # 개인정보 요약
        privacy_card = ctk.CTkFrame(info_scroll, fg_color=COLOR_CARD_BG, corner_radius=10)
        privacy_card.pack(fill="x", pady=(0, 15))
        _lock_icon = load_icon("lock", size=16)
        ctk.CTkLabel(privacy_card, fg_color="transparent", text="개인정보 안내" if _lock_icon else "🔒 개인정보 안내", image=_lock_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white").pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            privacy_card, fg_color="transparent",
            text="대화·기분·사고기록 등 모든 데이터는 이 PC에만 저장되며, Google Gemini API "
                 "호출 외에는 외부로 전송되지 않습니다. 설정(⚙)에서 데이터를 언제든 백업하거나 "
                 "영구 삭제할 수 있습니다.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_SECONDARY, wraplength=520, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # 앱 정보 + 피드백
        about_card = ctk.CTkFrame(info_scroll, fg_color=COLOR_CARD_BG, corner_radius=10)
        about_card.pack(fill="x")
        _msg_icon = load_icon("message-square", size=16)
        ctk.CTkLabel(about_card, fg_color="transparent", text="의견을 들려주세요" if _msg_icon else "💬 의견을 들려주세요", image=_msg_icon, compound="left", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color="white").pack(anchor="w", padx=16, pady=(14, 4))
        feedback_link = ctk.CTkLabel(
            about_card, fg_color="transparent", text="피드백 남기기" if _msg_icon else "📝 피드백 남기기",
            image=_msg_icon, compound="left", text_color=COLOR_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, underline=True), cursor="hand2",
        )
        feedback_link.pack(anchor="w", padx=16, pady=(0, 14))
        feedback_link.bind("<Button-1>", lambda e: webbrowser.open(FEEDBACK_FORM_URL))

        # 9. 자유 일기 탭 — AI 분류/개입 없이 그냥 조용히 쓰고 저장하는 순수 일기장
        ctk.CTkLabel(
            self.tab_journal, fg_color="transparent", image=load_icon("book-open", size=16), compound="left", text=("오늘의 일기" if load_icon("book-open", size=16) else "📔 오늘의 일기"), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            self.tab_journal, fg_color="transparent", text="AI 개입 없이 그대로 저장됩니다. 편하게 적어보세요.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color=COLOR_TEXT_MUTED,
        ).pack(anchor="w", padx=10, pady=(0, 8))

        self.journal_entry_box = ctk.CTkTextbox(self.tab_journal, height=140)
        self.journal_entry_box.pack(fill="x", padx=10, pady=(0, 8))

        journal_btn_frame = ctk.CTkFrame(self.tab_journal, fg_color="transparent")
        journal_btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(journal_btn_frame, text=("저장" if load_icon("save", size=14) else "💾 저장"), image=load_icon("save", size=14), compound="left", width=100, command=self.manual_save_journal_entry).pack(side="right")

        ctk.CTkLabel(
            self.tab_journal, fg_color="transparent", text="지난 일기", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold")
        ).pack(anchor="w", padx=10, pady=(0, 2))

        self.journal_scroll = ctk.CTkScrollableFrame(self.tab_journal, fg_color="transparent")
        self.journal_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 초기 렌더링
        self.after(500, self.render_mood_chart)
        self.after(500, self.render_positive_gallery)
        self.after(500, self.refresh_quest_progress)
        self.after(500, self.render_thought_journal)
        self.after(500, self.render_reminder_list)
        self.after(500, self.render_task_list)
        self.after(500, self.render_journal_entries)
        # 모든 스크롤 프레임이 다 만들어진 뒤(위 렌더링들과 같은 타이밍), 시작 시점의
        # 실제 테마(저장된 설정이 모듈 기본값인 Dark와 다를 수 있음)로 캔버스 배경을
        # 한 번 맞춰준다. 이걸 안 하면 "저장된 테마는 Light인데 스크롤 영역만 시작할 때의
        # 기본 Dark로 남아있는" 문제가 생긴다.
        self.after(500, self._resync_scrollable_frame_backgrounds)

    # ---------------------------------------------------------------------------
    # 💡 [1순위 신규] 안전 계획 모달 및 긴급 팝업 메서드
    # ---------------------------------------------------------------------------
    def open_safety_plan_modal(self):
        """평소에 나만의 안전 계획을 작성하고 편집하는 모달 창"""
        plan = memory_db.get_safety_plan()

        modal = ctk.CTkToplevel(self)
        modal.title("🛡️ 나만의 마음 안전 계획 (Safety Plan)")
        modal.geometry("520x620")
        modal.attributes("-topmost", True)
        modal.grab_set()

        ctk.CTkLabel(
            modal, fg_color="transparent", image=load_icon("shield", size=18), compound="left", text=("위기 상황 대비 나의 안전 수칙" if load_icon("shield", size=18) else "🛡️ 위기 상황 대비 나의 안전 수칙"), 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")
        ).pack(pady=(20, 5))

        ctk.CTkLabel(
            modal, fg_color="transparent", text="힘든 순간이 찾아왔을 때 나를 지켜줄 수 있는 대처법을 미리 적어두세요.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_DISABLED
        ).pack(pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=5)

        # 1. 위기 신호
        ctk.CTkLabel(scroll, fg_color="transparent", text="1. 내가 위기임을 느끼는 경고 신호 (생각/신체/행동)", font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w", pady=(5, 2))
        txt_signals = ctk.CTkTextbox(scroll, height=60)
        txt_signals.pack(fill="x", pady=(0, 10))
        txt_signals.insert("1.0", plan["warning_signals"])

        # 2. 스스로 대처법
        ctk.CTkLabel(scroll, fg_color="transparent", text="2. 마음을 진정시키기 위해 스스로 할 수 있는 대처법", font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w", pady=(5, 2))
        txt_coping = ctk.CTkTextbox(scroll, height=70)
        txt_coping.pack(fill="x", pady=(0, 10))
        txt_coping.insert("1.0", plan["coping_strategies"])

        # 3. 비상 연락처
        ctk.CTkLabel(scroll, fg_color="transparent", text="3. 도움을 요청할 수 있는 개인 비상 연락처", font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w", pady=(5, 2))
        txt_contacts = ctk.CTkTextbox(scroll, height=50)
        txt_contacts.pack(fill="x", pady=(0, 10))
        txt_contacts.insert("1.0", plan["emergency_contacts"])

        # 4. 안전 환경
        ctk.CTkLabel(scroll, fg_color="transparent", text="4. 주변 환경을 안전하게 만드는 수칙", font=ctk.CTkFont(family=FONT_FAMILY, weight="bold")).pack(anchor="w", pady=(5, 2))
        txt_env = ctk.CTkTextbox(scroll, height=50)
        txt_env.pack(fill="x", pady=(0, 10))
        txt_env.insert("1.0", plan["safe_environment"])

        def _save():
            memory_db.save_safety_plan(
                warning_signals=txt_signals.get("1.0", "end-1c").strip(),
                coping_strategies=txt_coping.get("1.0", "end-1c").strip(),
                emergency_contacts=txt_contacts.get("1.0", "end-1c").strip(),
                safe_environment=txt_env.get("1.0", "end-1c").strip()
            )
            self.log_message("System", "안전 계획이 성공적으로 저장되었습니다.")
            modal.destroy()

        ctk.CTkButton(
            modal, text=("저장하기" if load_icon("save", size=14) else "💾 저장하기"), image=load_icon("save", size=14), compound="left", fg_color=COLOR_SUCCESS_BTN, text_color="white", hover_color=COLOR_SUCCESS_BTN_HOVER, command=_save
        ).pack(pady=15)

    def show_crisis_popup(self):
        """🚨 위기 키워드 감지 시 즉시 팝업으로 노출되는 긴급 안전 수칙 창"""
        plan = memory_db.get_safety_plan()

        popup = ctk.CTkToplevel(self)
        popup.title("🚨 긴급 안전 안내 및 나의 안전 수칙")
        popup.geometry("560x650")
        popup.attributes("-topmost", True)
        popup.grab_set()

        # 상단 경고 뱃지
        header_frame = ctk.CTkFrame(popup, fg_color=COLOR_DANGER_BTN, corner_radius=0)
        header_frame.pack(fill="x")
        
        ctk.CTkLabel(
            header_frame, fg_color="transparent", image=load_icon("siren", size=20), compound="left", text=("Master, 지금 혼자가 아닙니다" if load_icon("siren", size=20) else "🚨 Master, 지금 혼자가 아닙니다"), 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_DIALOG_TITLE, weight="bold"), text_color="white"
        ).pack(pady=(15, 2))
        ctk.CTkLabel(
            header_frame, fg_color="transparent", text="힘든 마음이 느껴지실 때는 언제든 아래 전문 기관이나 나만의 대처법을 활용하세요.", 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color="#EAEAEA"
        ).pack(pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # 1. 하드코딩된 국가 비상 상담전화
        phone_card = ctk.CTkFrame(scroll, fg_color="#2c3e50", corner_radius=10)
        phone_card.pack(fill="x", pady=5)

        ctk.CTkLabel(
            phone_card, fg_color="transparent", image=load_icon("phone", size=16), compound="left", text=("24시간 긴급 전문 상담전화" if load_icon("phone", size=16) else "📞 24시간 긴급 전문 상담전화"), 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"), text_color=COLOR_WARNING_ALT
        ).pack(anchor="w", padx=12, pady=(10, 5))

        ctk.CTkLabel(
            phone_card, fg_color="transparent", text="• 자살예방 상담전화: 109 (24시간 통화 가능)\n• 정신건강 위기상담전화: 1577-0199", 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), justify="left", text_color="white"
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # 2. 사전 등록된 나만의 대처법
        coping_card = ctk.CTkFrame(scroll, fg_color=COLOR_CARD_BG, corner_radius=10)
        coping_card.pack(fill="x", pady=5)

        ctk.CTkLabel(
            coping_card, fg_color="transparent", image=load_icon("wind", size=16), compound="left", text=("Master가 직접 적어둔 마음 안정 대처법" if load_icon("wind", size=16) else "🧘 Master가 직접 적어둔 마음 안정 대처법"), 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"), text_color=COLOR_SUCCESS
        ).pack(anchor="w", padx=12, pady=(10, 5))

        coping_text = plan['coping_strategies'] or "미리 작성된 대처법이 없습니다."
        ctk.CTkLabel(
            coping_card, fg_color="transparent", text=coping_text, 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color="white", justify="left", wraplength=480
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # 3. 비상 연락처
        contact_card = ctk.CTkFrame(scroll, fg_color=COLOR_CARD_BG, corner_radius=10)
        contact_card.pack(fill="x", pady=5)

        ctk.CTkLabel(
            contact_card, fg_color="transparent", image=load_icon("users", size=16), compound="left", text=("나만의 비상 연락처" if load_icon("users", size=16) else "👥 나만의 비상 연락처"), 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION, weight="bold"), text_color=COLOR_PRIMARY
        ).pack(anchor="w", padx=12, pady=(10, 5))

        contact_text = plan['emergency_contacts'] or "미리 작성된 비상 연락처가 없습니다."
        ctk.CTkLabel(
            contact_card, fg_color="transparent", text=contact_text, 
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color="white", justify="left", wraplength=480
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # 4. 하단 버튼
        ctk.CTkButton(
            popup, text="확인했습니다 (온율이와 천천히 이야기하기)", 
            fg_color="#34495E", hover_color="#2C3E50", command=popup.destroy
        ).pack(pady=15)

    def set_crisis_mode(self, enable: bool):
        def _update():
            if enable:
                self.crisis_banner.pack(fill="x", side="top", before=self.header_frame)
                self.status_badge.configure(text="🚨 안전 안내 중...", text_color="white")
                # 💡 위기 감지 시 안전 수칙 팝업 자동 실행!
                self.show_crisis_popup()
                self._schedule_crisis_followup()
            else:
                self.crisis_banner.pack_forget()
                if not self.app_state.is_standby:
                    self.status_badge.configure(text="🟢 듣는 중...", text_color=COLOR_SUCCESS)
        self.after(0, _update)

    def _schedule_crisis_followup(self):
        """
        위기 개입이 발생하면, 24시간 뒤 온율이가 부드럽게 안부를 확인하도록
        알림을 자동 예약한다. 실제 위기 대응(postvention)에서 중요하게 다루는
        '팔로우업 접촉'의 가벼운 버전이다.

        같은 날 위기가 여러 번 감지돼도 팔로업이 중복으로 쌓이지 않도록,
        제목에 고정 접두사("🌱 안부 확인:")를 붙여두고 이미 예약된 게 있으면
        건너뛴다.
        """
        try:
            existing = reminder_db.get_upcoming_reminders(limit=50)
            if any(str(r.get("title", "")).startswith("🌱 안부 확인") for r in existing):
                return  # 이미 예약된 팔로업이 있으면 중복 생성하지 않음

            remind_at = (datetime.datetime.now() + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
            reminder_db.create_reminder(
                title=(
                    "🌱 안부 확인: 어제 힘든 순간이 있었어요. 부담 주지 않는 다정한 "
                    "톤으로, 지금은 어떤지 자연스럽게 안부를 물어봐 주세요."
                ),
                remind_at=remind_at,
                kind="schedule",
            )
            self.after(0, self.render_reminder_list)
        except Exception as e:
            print(f"⚠️ [Crisis Followup Schedule Error]: {e}")

    def show_reconnect_banner(self, reason: str = ""):
        def _update():
            has_icon = load_icon("unplug", size=16) is not None
            text = ("연결이 끊겼습니다." if has_icon else "🔌 연결이 끊겼습니다.") + (f" ({reason})" if reason else "")
            self.reconnect_banner_label.configure(text=text)
            self.reconnect_banner.pack(fill="x", side="top", before=self.header_frame)
            self.status_badge.configure(text="🔌 연결 끊김", text_color="#E67E22")
            # 재연결 시도가 실패해서 배너가 다시 뜬 것일 수 있으니, 버튼을
            # 다시 눌러볼 수 있는 상태로 되돌린다.
            self.reconnect_btn.configure(state="normal", text=("재연결" if load_icon("refresh-cw", size=14) else "🔄 재연결"))
        self.after(0, _update)

    def hide_reconnect_banner(self):
        def _update():
            self.reconnect_banner.pack_forget()
            # 연결에 성공해서 배너가 숨겨질 때도, 다음번을 위해 버튼 상태를
            # 정상으로 되돌려둔다.
            self.reconnect_btn.configure(state="normal", text=("재연결" if load_icon("refresh-cw", size=14) else "🔄 재연결"))
        self.after(0, _update)

    def trigger_reconnect(self):
        """
        재연결 버튼 및 설정 변경(목소리/API 키) 시 호출되는 진입점.

        asyncio.Event.set()은 스레드 세이프하지 않으므로, GUI(메인 스레드)에서
        직접 호출하면 안 되고 반드시 이벤트가 속한 이벤트 루프(app_loop) 위에서
        실행되도록 call_soon_threadsafe로 넘겨야 한다.
        """
        if self.app_loop_ref and self.reconnect_event:
            self.log_message("System", "🔄 재연결을 요청했습니다...")
            # 실제 연결이 완료(성공 시 hide_reconnect_banner, 실패 시
            # show_reconnect_banner가 다시 호출됨)될 때까지, 버튼을 비활성화하고
            # "재연결 시도 중..."으로 바꿔서 중복 클릭을 막고 진행 상태를 보여준다.
            self.reconnect_btn.configure(state="disabled", text="재연결 시도 중...")
            self.app_loop_ref.call_soon_threadsafe(self.reconnect_event.set)
        else:
            self.log_message("Error", "아직 연결 파이프라인이 준비되지 않았습니다. 잠시 후 다시 시도해주세요.")

    def trigger_breathing(self):
        if self.app_state.is_standby:
            self.set_standby_mode(False)
        self.log_message("Master (Action)", "[🧘 4-7-8 호흡 가이드 요청]")
        if self.async_session and app_loop:
            asyncio.run_coroutine_threadsafe(
                self.async_session.send_realtime_input(text="4-7-8 호흡 가이드를 바로 시작해주세요."), app_loop
            )

    def trigger_grounding(self):
        if self.app_state.is_standby:
            self.set_standby_mode(False)
        self.log_message("Master (Action)", "[⚓ 마음 안정 가이드 요청]")
        if self.async_session and app_loop:
            asyncio.run_coroutine_threadsafe(
                self.async_session.send_realtime_input(text="오감 인지 그라운딩 기법으로 마음 안정을 도와주세요."), app_loop
            )

    def trigger_daily_briefing(self):
        if self.app_state.is_standby:
            self.set_standby_mode(False)
        self.log_message("Master (Action)", "[🌅 데일리 브리핑 요청]")
        if self.async_session and app_loop:
            asyncio.run_coroutine_threadsafe(
                self.async_session.send_realtime_input(text="오늘의 데일리 브리핑을 해주세요."), app_loop
            )

    def on_chart_period_change(self, choice: str):
        period_map = {"7일": 7, "30일": 30, "90일": 90}
        self.chart_days = period_map.get(choice, 7)
        self.render_mood_chart()

    def render_mood_chart(self):
        from matplotlib.figure import Figure

        days = self.chart_days

        if self.chart_canvas:
            try:
                self.chart_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.chart_canvas = None

        today = datetime.datetime.now()
        dates_dict = {(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d"): None for i in range(days - 1, -1, -1)}

        try:
            # core.db.get_connection: WAL 모드와 busy_timeout(10초) 설정이 core/*.py의
            # 다른 모든 DB 접근과 일관되게 적용된다. 예전엔 여기만 sqlite3.connect()를
            # 직접 써서 파이썬 기본 busy timeout(5초)을 썼다 — WAL 모드 자체는 DB 파일
            # 레벨 설정이라 문제는 없었지만, 완전한 일관성을 위해 통일한다.
            conn = _core_get_connection(memory_db.db_path)
            cursor = conn.cursor()
            # 실제 테이블명은 mood_sleep_logs가 아니라 mood_log이고, 별도의 date 컬럼도
            # 없다 — created_at(전체 타임스탬프)의 앞 10글자(YYYY-MM-DD)를 잘라 쓴다.
            cursor.execute("""
                SELECT substr(created_at, 1, 10) AS date, mood_score
                FROM mood_log
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            conn.close()
            for date_part, score in rows:
                if not date_part or score is None:
                    continue
                if date_part in dates_dict:
                    try:
                        num_match = re.search(r"(\d+(?:\.\d+)?)", str(score))
                        if num_match:
                            dates_dict[date_part] = float(num_match.group(1))
                    except Exception:
                        pass
        except Exception as e:
            print(f"📊 [Chart DB Error]: {e}")

        dates = []
        scores = []
        last_valid_score = 5.0

        for d_str, score in dates_dict.items():
            display_date = d_str[5:].replace("-", "/")
            dates.append(display_date)
            if score is not None:
                last_valid_score = score
                scores.append(score)
            else:
                scores.append(last_valid_score)

        fig = Figure(figsize=(6, 3.5), dpi=100)
        fig.patch.set_facecolor(COLOR_CARD_BG)
        ax = fig.add_subplot(111)
        ax.set_facecolor('#1e1e1e')

        ax.plot(dates, scores, marker='o', color=COLOR_PRIMARY, linewidth=2.5, markersize=5 if days <= 7 else 3, label="기분 점수 (1~10)")
        ax.fill_between(dates, scores, color=COLOR_PRIMARY, alpha=0.2)

        ax.set_ylim(1, 10)
        ax.set_title(f"Mood Tracker (최근 {days}일)", color="white", fontsize=12, pad=10)
        ax.tick_params(colors='white', labelsize=9)
        ax.spines['bottom'].set_color('#555555')
        ax.spines['top'].set_color('#555555')
        ax.spines['left'].set_color('#555555')
        ax.spines['right'].set_color('#555555')
        ax.grid(True, linestyle='--', alpha=0.3, color=COLOR_TEXT_MUTED)

        if days > 14:
            tick_step = max(1, days // 10)
            ax.set_xticks(range(0, len(dates), tick_step))
            ax.set_xticklabels([dates[i] for i in range(0, len(dates), tick_step)], rotation=45, ha="right")

        self.chart_canvas = FigureCanvasTkAgg(fig, master=self.chart_container)
        self.chart_canvas.draw()
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.render_emotion_tags(days)

    def render_emotion_tags(self, days: int = None):
        import collections

        if days is None:
            days = self.chart_days

        for widget in self.emotion_tags_frame.winfo_children():
            widget.destroy()

        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days - 1)).strftime("%Y-%m-%d")
        counter = collections.Counter()
        try:
            conn = _core_get_connection(memory_db.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT substr(created_at, 1, 10) AS date, emotion_keywords FROM mood_log WHERE substr(created_at, 1, 10) >= ?",
                (cutoff,),
            )
            rows = cursor.fetchall()
            conn.close()
            for _date, keywords in rows:
                if not keywords:
                    continue
                for word in re.split(r"[,\s/·]+", str(keywords).strip()):
                    word = word.strip()
                    if word:
                        counter[word] += 1
        except Exception as e:
            print(f"📊 [Emotion Tag DB Error]: {e}")

        if not counter:
            ctk.CTkLabel(
                self.emotion_tags_frame, fg_color="transparent",
                text="아직 기록된 감정 키워드가 없습니다.\n"
                     "💡 \"오늘 기분 6점이야, 좀 뿌듯했어\"처럼 말해보세요.",
                text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), justify="left"
            ).pack(anchor="w", padx=5)
            return

        for word, count in counter.most_common(10):
            tag = ctk.CTkLabel(
                self.emotion_tags_frame, text=f"#{word} ({count})",
                fg_color="#34495E", corner_radius=12, padx=10, pady=4,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL),
            )
            tag.pack(side="left", padx=4, pady=4)

    def refresh_quest_progress(self):
        try:
            completed, total = memory_db.get_quest_stats()
        except Exception as e:
            print(f"🎯 [Quest Progress DB Error]: {e}")
            completed, total = 0, 0

        ratio = (completed / total) if total > 0 else 0.0
        self.quest_progress_bar.set(ratio)
        self.quest_progress_label.configure(text=f"완료한 퀘스트 {completed} / {total}")
        self.render_quest_journal()

    def render_quest_journal(self):
        """퀘스트 일지 목록을 화면에 렌더링"""
        # 기존 렌더링된 위젯 삭제 (스크롤 프레임 내부 초기화)
        if hasattr(self, 'quests_scroll'):
            for widget in self.quests_scroll.winfo_children():
                widget.destroy()

        rows = memory_db.get_all_quests_raw()
        if not rows:
            self._render_empty_state(
                self.quests_scroll, "target",
                "아직 등록된 퀘스트가 없습니다.\n"
                "💡 \"오늘 산책이라도 해볼까, 작은 목표 하나 추천해줘\"처럼 말해보세요.",
            )
            return

        # 데이터 형태(Dict/Tuple)에 맞춰 안전하게 추출하는 파싱 함수
        def parse_item(r):
            if isinstance(r, dict):
                return {
                    'id': r.get('id', ''),
                    'title': r.get('title') or r.get('quest_title') or '제목 없는 퀘스트',
                    'status': str(r.get('status', '')).upper(),
                    'created_at': str(r.get('created_at', ''))[:10] or '날짜 미상'
                }
            else:
                return {
                    'id': r[0] if len(r) > 0 else '',
                    'title': r[2] if len(r) > 2 else (r[1] if len(r) > 1 else '제목 없는 퀘스트'),
                    'status': str(r[3] if len(r) > 3 else '').upper(),
                    'created_at': str(r[4] if len(r) > 4 else '')[:10] or '날짜 미상'
                }

        parsed_rows = [parse_item(r) for r in rows]
        pending_quests = [q for q in parsed_rows if q['status'] == 'PENDING']
        completed_quests = [q for q in parsed_rows if q['status'] in ['COMPLETED', 'DONE']]

        # --- 퀘스트 카드가 그려지는 영역 ---
        target_container = getattr(self, 'quests_scroll', None)
        if not target_container:
            return

        # 진행 중인(대기중) 퀘스트 카드
        for q in pending_quests:
            card = ctk.CTkFrame(target_container, fg_color=COLOR_CARD_BG, corner_radius=8)
            card.pack(fill="x", padx=10, pady=5)

            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=15, pady=(10, 2))

            header_text = f"⏳ 진행중  ·  {q['created_at']}"
            lbl_header = ctk.CTkLabel(
                header_row, fg_color="transparent",
                text=header_text,
                font=("Malgun Gothic", 12, "bold"),
                text_color=COLOR_WARNING,
                anchor="w"
            )
            lbl_header.pack(side="left")

            ctk.CTkButton(
                header_row, text=("완료" if load_icon("check", size=14) else "✅ 완료"), image=load_icon("check", size=14), compound="left", width=60, height=24,
                fg_color=COLOR_SUCCESS_BTN, text_color="white", hover_color=COLOR_SUCCESS_BTN_HOVER,
                command=lambda qid=q['id']: self.manual_complete_quest(qid)
            ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(
                header_row, text=("" if load_icon("trash-2", size=14) else "🗑"), image=load_icon("trash-2", size=14), width=32, height=24,
                fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
                command=lambda qid=q['id'], c=card: self.request_delete_with_undo(
                    c, "퀘스트", lambda: memory_db.delete_quest(qid), self.render_quest_journal
                )
            ).pack(side="right", padx=(4, 0))

            lbl_title = ctk.CTkLabel(
                card, fg_color="transparent",
                text=q['title'],
                font=("Malgun Gothic", 14),
                text_color="#ffffff",
                anchor="w"
            )
            lbl_title.pack(fill="x", padx=15, pady=(2, 10))

        # 완료된 퀘스트 카드
        for q in completed_quests:
            # 카드 박스 생성
            card = ctk.CTkFrame(target_container, fg_color=COLOR_CARD_BG, corner_radius=8)
            card.pack(fill="x", padx=10, pady=5)

            # 상단 헤더 (달성 상태 및 날짜 + 삭제 버튼)
            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=15, pady=(10, 2))

            header_text = f"🌲 달성  ·  {q['created_at']}"
            lbl_header = ctk.CTkLabel(
                header_row, fg_color="transparent",
                text=header_text,
                font=("Malgun Gothic", 12, "bold"),
                text_color=COLOR_SUCCESS,
                anchor="w"
            )
            lbl_header.pack(side="left")

            ctk.CTkButton(
                header_row, text=("" if load_icon("trash-2", size=14) else "🗑"), image=load_icon("trash-2", size=14), width=32, height=24,
                fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
                command=lambda qid=q['id'], c=card: self.request_delete_with_undo(
                    c, "퀘스트", lambda: memory_db.delete_quest(qid), self.render_quest_journal
                )
            ).pack(side="right")

            # 하단 제목 (실제 퀘스트 명 출력)
            lbl_title = ctk.CTkLabel(
                card, fg_color="transparent", 
                text=q['title'], 
                font=("Malgun Gothic", 14), 
                text_color="#ffffff",
                anchor="w"
            )
            lbl_title.pack(fill="x", padx=15, pady=(2, 10))

    def render_thought_journal(self):
        """사고기록(인지 재구성) 일지를 카드로 렌더링."""
        if not hasattr(self, "thoughts_scroll"):
            return
        for widget in self.thoughts_scroll.winfo_children():
            widget.destroy()

        try:
            rows = memory_db.get_user_thought_history(limit=30)
        except Exception as e:
            print(f"🧠 [Thought Journal DB Error]: {e}")
            rows = []

        if not rows:
            self._render_empty_state(
                self.thoughts_scroll, "brain",
                "아직 기록된 사고기록이 없습니다.\n"
                "💡 \"오늘 발표를 망쳐서 나는 뭘 해도 안 되는 사람 같아\"처럼 "
                "힘든 생각을 이야기하면, 온율이와 함께 살펴본 뒤 여기에 쌓여요.",
            )
            return

        for r in rows:
            situation = r.get("situation", "")
            automatic = r.get("automatic_thought", "")
            distortion = r.get("cognitive_distortion") or ""
            alternative = r.get("alternative_thought", "")
            before = r.get("emotion_before")
            after = r.get("emotion_after")
            created_at = str(r.get("created_at", ""))[:10]

            card = ctk.CTkFrame(self.thoughts_scroll, corner_radius=10, fg_color=COLOR_CARD_BG)
            card.pack(fill="x", padx=5, pady=6)

            header_text = f"📅 {created_at}" + (f"  ·  {distortion}" if distortion else "")
            ctk.CTkLabel(
                card, fg_color="transparent", text=header_text, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold"), text_color="#9B59B6"
            ).pack(anchor="w", padx=12, pady=(10, 2))

            if situation:
                ctk.CTkLabel(
                    card, fg_color="transparent", text=f"상황: {situation}", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY),
                    text_color=COLOR_TEXT_SECONDARY, justify="left", wraplength=560,
                ).pack(anchor="w", padx=12, pady=(0, 2))

            ctk.CTkLabel(
                card, fg_color="transparent", text=f"❌ 자동적 사고: {automatic}", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY),
                text_color=COLOR_TEXT_SECONDARY, justify="left", wraplength=560,
            ).pack(anchor="w", padx=12, pady=(2, 2))

            ctk.CTkLabel(
                card, fg_color="transparent", text=f"✅ 대안적 사고: {alternative}", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"),
                text_color=COLOR_SUCCESS, justify="left", wraplength=560,
            ).pack(anchor="w", padx=12, pady=(2, 8))

            if before is not None and after is not None:
                try:
                    relief = int(before) - int(after)
                    relief_text = f"감정 강도 {before} → {after}  (완화 {relief}점)" if relief >= 0 else f"감정 강도 {before} → {after}"
                    ctk.CTkLabel(
                        card, fg_color="transparent", text=relief_text, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color=COLOR_TEXT_MUTED,
                    ).pack(anchor="w", padx=12, pady=(0, 10))
                except (TypeError, ValueError):
                    pass

    def manual_add_quest(self):
        title = self.quest_add_entry.get().strip()
        if not title:
            return
        try:
            create_micro_quest(title)
            self.quest_add_entry.delete(0, "end")
            self.log_message("System", f"퀘스트를 직접 추가했습니다: {title}")
            self.refresh_quest_progress()
        except Exception as e:
            print(f"🎯 [Manual Quest Add Error]: {e}")

    # ---------------------------------------------------------------------------
    # 🗑️➡️↩️ 범용 "실행취소 가능한 삭제" 메커니즘
    #
    # 삭제 버튼을 누르면 즉시 DB에서 지우는 대신, 카드를 화면에서만 잠깐 숨기고
    # "삭제됨 · 실행취소" 토스트를 5초간 띄운다. 그 안에 실행취소를 안 누르면
    # 그때 실제 DB 삭제(commit_delete_fn)를 실행한다. 퀘스트/할일/알림/일기
    # 4곳의 삭제 버튼이 전부 이 메커니즘 하나를 공유한다.
    # ---------------------------------------------------------------------------

    def request_delete_with_undo(self, card_widget, label: str, commit_delete_fn, refresh_fn):
        """
        card_widget: 삭제 대상 카드 위젯 (즉시 화면에서만 숨김, 아직 DB는 안 건드림)
        label: 토스트에 표시할 대상 이름 (예: "퀘스트", "할 일")
        commit_delete_fn: 실제 DB 삭제를 실행하는 콜백 (인자 없음)
        refresh_fn: 목록을 DB 기준으로 다시 그리는 콜백 (실행취소 시 이걸 부르면
                    카드가 그대로 복원된다 — 아직 DB에서 안 지워졌으므로)
        """
        # 이미 대기 중인 되돌리기가 있으면, 새 삭제를 처리하기 전에 그것부터 확정한다
        # (동시에 여러 개를 되돌리기 창에 걸어두면 헷갈리므로 하나만 유지).
        self._commit_pending_undo()

        card_widget.pack_forget()

        def _commit():
            self._pending_undo = None
            try:
                commit_delete_fn()
            except Exception as e:
                print(f"⚠️ [Undo Delete Commit Error]: {e}")
            self._hide_undo_toast()

        def _undo():
            pending = getattr(self, "_pending_undo", None)
            if pending:
                self.after_cancel(pending["job"])
            self._pending_undo = None
            self._hide_undo_toast()
            refresh_fn()

        job = self.after(5000, _commit)
        self._pending_undo = {"commit": _commit, "job": job}
        self._show_undo_toast_ui(f"{label}이(가) 삭제되었습니다", _undo)

    def _commit_pending_undo(self):
        """대기 중인 되돌리기가 있으면 즉시 확정(실제 삭제)한다."""
        pending = getattr(self, "_pending_undo", None)
        if pending:
            self.after_cancel(pending["job"])
            pending["commit"]()

    def _show_undo_toast_ui(self, message: str, on_undo):
        self._hide_undo_toast()
        toast = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        toast.place(relx=0.5, rely=0.96, anchor="s")
        ctk.CTkLabel(toast, fg_color="transparent", text=message, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color="white").pack(side="left", padx=(16, 8), pady=10)
        ctk.CTkButton(
            toast, text="↩️ 실행취소", width=90, height=28,
            fg_color=COLOR_PRIMARY, text_color="white", hover_color="#2980B9", command=on_undo,
        ).pack(side="left", padx=(0, 12), pady=10)
        self._undo_toast_widget = toast

    def _hide_undo_toast(self):
        widget = getattr(self, "_undo_toast_widget", None)
        if widget:
            widget.destroy()
            self._undo_toast_widget = None

    def manual_complete_quest(self, quest_id: int):
        try:
            memory_db.complete_quest_by_id(quest_id)
            self.log_message("System", f"퀘스트를 수동으로 완료 처리했습니다! 수고하셨어요 👏")
            self.refresh_quest_progress()
        except Exception as e:
            print(f"🎯 [Manual Quest Complete Error]: {e}")

    def render_positive_gallery(self):
        for widget in self.anchors_scroll.winfo_children():
            widget.destroy()

        try:
            rows = memory_db.get_positive_anchors_raw(limit=30)
        except Exception as e:
            print(f"🌟 [Positive Anchor DB Error]: {e}")
            rows = []

        if not rows:
            self._render_empty_state(
                self.anchors_scroll, "star",
                "아직 저장된 긍정 기억이 없습니다.\n"
                "💡 \"오늘 친구랑 산책해서 정말 좋았어\"처럼 좋았던 순간을 나눠보세요.",
            )
            return

        for ts, content, emotion_tag in rows:
            card = ctk.CTkFrame(self.anchors_scroll, corner_radius=10, fg_color=COLOR_CARD_BG)
            card.pack(fill="x", padx=5, pady=6)

            date_str = str(ts)[:10] if ts else ""
            ctk.CTkLabel(
                card, fg_color="transparent", text=f"🌟 {date_str}  ·  {emotion_tag or ''}",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold"), text_color=COLOR_WARNING_ALT
            ).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(
                card, fg_color="transparent", text=content, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY), text_color="white", justify="left", wraplength=560
            ).pack(anchor="w", padx=12, pady=(0, 10))

    def update_mic_level(self, level: float):
        def _update():
            if self.app_state.is_standby:
                self.mic_level_bar.set(0.0)
                self._pulse_running = False
            else:
                self.mic_level_bar.set(level)
                # 마이크 레벨이 일정 이상(실제로 말하는 중)일 때만 🎙️ 아이콘이
                # 숨쉬듯 커졌다 작아지는 펄스 애니메이션을 튼다. 매 오디오 청크마다
                # (수 ms 간격으로) update_mic_level이 불리므로, 이미 돌고 있으면
                # 다시 시작하지 않고 _pulse_step의 재귀 after() 루프에 맡긴다.
                speaking_now = level > 0.08
                if speaking_now and not self._pulse_running:
                    self._pulse_running = True
                    self._pulse_step()
                elif not speaking_now and self._pulse_running:
                    self._pulse_running = False
                    self.mic_icon.configure(font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION))
        self.after(0, _update)

    def _pulse_step(self):
        """🎙️ 아이콘 크기를 사인파로 부드럽게 오가게 해서 '말하는 중' 느낌을 준다."""
        if not self._pulse_running:
            self.mic_icon.configure(font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SUBSECTION))
            return
        self._pulse_t += 0.35
        scale = 1.0 + 0.3 * abs(math.sin(self._pulse_t))
        self.mic_icon.configure(font=ctk.CTkFont(family=FONT_FAMILY, size=int(14 * scale)))
        self.after(80, self._pulse_step)

    def record_wake_word_miss(self, text: str):
        """대기 모드에서 웨이크워드로 인식되지 않은 발화를 최근 목록(최대 15개)에 기록."""
        if not text or len(text) < 2:
            return
        if self.recent_wake_misses and self.recent_wake_misses[-1] == text:
            return  # 완전히 같은 문구 연속 기록 방지
        self.recent_wake_misses.append(text)
        self.recent_wake_misses = self.recent_wake_misses[-15:]

    def clear_chat_log(self):
        """
        화면에 보이는 대화 로그만 지운다. 기분/사고기록/퀘스트 등 실제로
        저장된 데이터는 전혀 건드리지 않는다 — 그냥 눈에 보이는 스크롤 기록을
        비우는 것뿐이라, 실수로 눌러도 되돌릴 수 없는 손실이 없다(그래서
        별도 확인창 없이 바로 실행한다).
        """
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")
        if self._new_msg_badge is not None:
            self._new_msg_badge.destroy()
            self._new_msg_badge = None
        self.log_message("System", "대화 로그를 지웠습니다. (저장된 기록은 그대로 유지됩니다)")

    def adjust_chat_font(self, delta: int):
        """A-/A+ 버튼: 채팅창(그리고 입력창) 글자 크기를 8~28 범위 안에서 조절.
        발신자 태그는 색상만 쓰고(font 미지정) 있어서, 본문 폰트 크기가 바뀌면
        태그가 적용된 글자도 자동으로 같은 크기를 따라간다 — 별도 갱신 불필요."""
        new_size = max(8, min(28, self.chat_font_size + delta))
        if new_size == self.chat_font_size:
            return
        self.chat_font_size = new_size
        self.chat_box.configure(font=ctk.CTkFont(family=FONT_FAMILY, size=new_size))
        self.text_entry.configure(font=ctk.CTkFont(family=FONT_FAMILY, size=new_size))

    def log_message(self, sender: str, text: str):
        def _update():
            # insert 하기 전에, 사용자가 지금 맨 아래를 보고 있는지 먼저 확인한다.
            # 과거 로그를 보려고 위로 스크롤해둔 상태라면, 새 메시지가 온다고
            # 강제로 맨 아래까지 끌어내리지 않는다 — 대신 배지로만 알려준다.
            _, bottom_fraction = self.chat_box.yview()
            was_at_bottom = bottom_fraction >= 0.995

            if was_at_bottom and self._new_msg_badge is not None:
                # 이미 맨 아래로 돌아와 있는데 배지가 남아있다면(수동 스크롤 등),
                # 여기서 정리해준다.
                self._new_msg_badge.destroy()
                self._new_msg_badge = None

            self.chat_box.configure(state="normal")
            # 발신자 이름표만 색을 입히고, 본문은 기본 색 그대로 둔다 — 상용
            # 채팅 앱들이 흔히 쓰는 패턴으로, 누가 말했는지는 색으로 바로 구분되고
            # 본문은 가독성을 위해 중립색을 유지한다.
            if sender in ("Master", "Master (Voice)"):
                tag = "tag_master"
            elif sender == "ONyuul":
                tag = "tag_onyuul"
            elif sender == "Error":
                tag = "tag_error"
            else:
                tag = "tag_system"
            self.chat_box.insert("end", f"[{sender}]", tag)
            self.chat_box.insert("end", f": {text}\n\n")
            self.chat_box.configure(state="disabled")

            if was_at_bottom:
                self.chat_box.see("end")
            else:
                self._show_new_message_badge()
        self.after(0, _update)

    def _show_new_message_badge(self):
        """과거 로그를 보고 있는 중에 새 메시지가 오면, 화면 하단에 작은
        '새 메시지' 배지를 띄운다. 이미 떠 있으면 중복으로 또 만들지 않는다."""
        if self._new_msg_badge is not None:
            return
        btn = ctk.CTkButton(
            self.tab_chat, text="🔽 새 메시지", width=120, height=32, corner_radius=16,
            fg_color=COLOR_PRIMARY, hover_color=COLOR_SUCCESS_BTN, text_color="white",
            command=self._jump_chat_to_bottom,
        )
        btn.place(relx=0.5, rely=0.96, anchor="s")
        self._new_msg_badge = btn

    def _jump_chat_to_bottom(self):
        self.chat_box.see("end")
        if self._new_msg_badge is not None:
            self._new_msg_badge.destroy()
            self._new_msg_badge = None

    def update_status(self, text: str, color: str = COLOR_SUCCESS):
        def _update():
            if self.app_state.is_standby and text != "🟡 대기 모드 중...":
                return
            self.status_badge.configure(text=text, text_color=color)
        self.after(0, _update)

    def set_standby_mode(self, enable: bool):
        def _update():
            if enable:
                self.app_state.enter_standby()
                self.standby_btn.configure(text="🔔 대기 모드 해제", fg_color=COLOR_SUCCESS_BTN)
                self.status_badge.configure(text="🟡 대기 모드 중...", text_color=COLOR_WARNING_ALT)
                self.mic_level_bar.set(0.0)
                self.log_message("System", "대기 모드로 전환되었습니다.")
            else:
                self.app_state.exit_standby()
                self.standby_btn.configure(text="💤 대기 모드 전환", fg_color=COLOR_DANGER)
                self.status_badge.configure(text="🟢 듣는 중...", text_color=COLOR_SUCCESS)
                self.log_message("System", "대기 모드가 해제되었습니다.")
        self.after(0, _update)

    def toggle_standby(self):
        self.set_standby_mode(not self.app_state.is_standby)

    def on_volume_change(self, value: float):
        self.tts_volume = float(value)
        _has_icon = load_icon("volume-2", size=14) is not None
        new_text = f"온율 목소리 볼륨 {int(self.tts_volume * 100)}%" if _has_icon else f"🔊 온율 목소리 볼륨 {int(self.tts_volume * 100)}%"
        self.volume_label.configure(text=new_text)
        config_manager.save_tts_volume(self.tts_volume)

    def toggle_mic_mute(self):
        """
        마이크만 끄는 토글 (대기 모드와 완전히 독립).

        대기 모드는 웨이크워드를 들어야 하니 오디오를 계속 서버로 보내지만,
        이건 그 전송 자체를 끊는다 — "온율아"라고 불러도 반응하지 않으므로
        다시 켜려면 이 버튼을 직접 눌러야 한다.
        """
        new_state = not self.app_state.mic_hard_muted
        self.app_state.mic_hard_muted = new_state
        if new_state:
            _icon = load_icon("mic-off", size=18)
            self.mic_mute_btn.configure(text="" if _icon else "🔇", image=_icon, fg_color=COLOR_DANGER_BTN, hover_color=COLOR_DANGER_BTN_HOVER)
            self.mic_mute_tooltip.update_text("마이크 켜기 (지금 꺼져 있음)")
            self.log_message("System", "🔇 마이크를 껐습니다. 웨이크워드도 반응하지 않으니, 다시 켜려면 이 버튼을 눌러주세요.")
        else:
            _icon = load_icon("mic", size=18)
            self.mic_mute_btn.configure(text="" if _icon else "🎙️", image=_icon, fg_color=COLOR_BORDER, hover_color=COLOR_NEUTRAL_HOVER)
            self.mic_mute_tooltip.update_text("마이크 끄기")
            self.log_message("System", "🎙️ 마이크를 다시 켰습니다.")

    def on_emergency_button_click(self):
        numbers = "자살예방상담전화 109 / 정신건강 위기상담전화 1577-0199"
        try:
            self.clipboard_clear()
            self.clipboard_append("109 / 1577-0199")
        except Exception:
            pass
        self.log_message("System", f"긴급 연락처를 클립보드에 복사했습니다. ({numbers})")
        self.show_crisis_popup()

    def open_wake_word_dialog(self):
        """
        웨이크워드 변형 관리 창.

        - 기본 내장 목록(코드에 하드코딩, 삭제 불가)과 사용자가 추가한 변형을 함께 보여준다.
        - '대기 모드에서 인식 못 한 최근 발화' 목록에서 바로 변형으로 추가할 수 있다
          (발음 오인식 패턴을 사용자가 직접 눈으로 보고 학습시키는 구조).
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("웨이크워드 설정")
        dialog.geometry("460x520")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        ctk.CTkLabel(dialog, fg_color="transparent", image=load_icon("mic", size=18), compound="left", text=("웨이크워드 변형 관리" if load_icon("mic", size=18) else "🗣️ 웨이크워드 변형 관리"), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")).pack(pady=(20, 5), padx=20)
        ctk.CTkLabel(
            dialog, fg_color="transparent",
            text="'온율'을 다르게 알아듣는 경우가 잦다면, 아래에서 직접 변형을\n추가하거나 필요 없는 걸 지울 수 있습니다.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_DISABLED, justify="left", wraplength=400,
        ).pack(padx=20, pady=(0, 12))

        ctk.CTkLabel(dialog, fg_color="transparent", text="현재 등록된 변형", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold")).pack(anchor="w", padx=20)
        variants_scroll = ctk.CTkScrollableFrame(dialog, height=110, fg_color="transparent")
        variants_scroll.pack(fill="x", padx=20, pady=(2, 10))

        def render_variants():
            for w in variants_scroll.winfo_children():
                w.destroy()
            user_variants = config_manager.get_wake_word_variants()
            for word in _BUILTIN_WAKE_WORDS:
                row = ctk.CTkFrame(variants_scroll, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, fg_color="transparent", text=f"{word}  (기본)", anchor="w", text_color=COLOR_TEXT_MUTED).pack(side="left", fill="x", expand=True)
            for word in user_variants:
                row = ctk.CTkFrame(variants_scroll, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, fg_color="transparent", text=word, anchor="w").pack(side="left", fill="x", expand=True)

                def _remove(w=word):
                    config_manager.remove_wake_word_variant(w)
                    refresh_wake_word_cache()
                    render_variants()

                ctk.CTkButton(row, text=("" if load_icon("trash-2", size=14) else "🗑"), image=load_icon("trash-2", size=14), width=28, height=22, fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER, command=_remove).pack(side="right")

        render_variants()

        add_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        add_frame.pack(fill="x", padx=20, pady=(0, 15))
        add_entry = ctk.CTkEntry(add_frame, placeholder_text="새 변형 추가 (예: 오뉼)")
        add_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        add_status_label = ctk.CTkLabel(add_frame, fg_color="transparent", text="", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color=COLOR_DANGER)

        def do_add():
            word = add_entry.get().strip()
            if not word:
                return
            if len(word) < 2:
                add_status_label.configure(text="2글자 이상 입력해주세요 (오탐 방지)")
                add_status_label.pack(side="left", padx=(8, 0))
                return
            add_status_label.pack_forget()
            config_manager.add_wake_word_variant(word)
            refresh_wake_word_cache()
            add_entry.delete(0, "end")
            render_variants()

        add_entry.bind("<Return>", lambda e: do_add())
        ctk.CTkButton(add_frame, text="+ 추가", width=70, command=do_add).pack(side="left")

        ctk.CTkLabel(dialog, fg_color="transparent", text="대기 모드에서 인식 못 한 최근 발화", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold")).pack(anchor="w", padx=20, pady=(5, 2))
        missed_scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        missed_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        def render_missed():
            for w in missed_scroll.winfo_children():
                w.destroy()
            if not self.recent_wake_misses:
                ctk.CTkLabel(missed_scroll, fg_color="transparent", text="아직 기록된 게 없습니다.", text_color=COLOR_TEXT_MUTED).pack(anchor="w", pady=5)
                return
            for text in reversed(self.recent_wake_misses):
                row = ctk.CTkFrame(missed_scroll, fg_color=COLOR_CARD_BG, corner_radius=8)
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, fg_color="transparent", text=text, text_color="white", anchor="w", wraplength=270, justify="left").pack(side="left", fill="x", expand=True, padx=8, pady=6)

                def _add_this(t=text):
                    config_manager.add_wake_word_variant(t)
                    refresh_wake_word_cache()
                    render_variants()
                    self.log_message("System", f"'{t}'를 웨이크워드 변형으로 추가했습니다.")

                ctk.CTkButton(row, text="+ 변형으로", width=90, height=24, command=_add_this).pack(side="right", padx=6)

        render_missed()

        ctk.CTkButton(dialog, text="닫기", width=100, command=dialog.destroy).pack(pady=(0, 15))

    def open_api_key_dialog(self, on_saved=None, first_run: bool = False):
        """
        Gemini API 키 설정 창.

        first_run=True(저장된 키가 아예 없어 앱 시작 전에 뜨는 경우)일 때는
        X 버튼으로 조용히 넘어가지 못하게 하고, "저장하고 시작"을 눌러야만
        닫히게 한다. 그 외(설정 버튼으로 직접 연 경우)는 취소 가능한 일반 창이다.

        세션 중 키를 바꿔도 이미 연결된 Live 세션을 즉시 갈아끼우지는 않는다
        (그건 별도의 재연결 로직이 필요한 범위 밖 작업). 대신 "다음 실행부터
        적용된다"고 안내한다.
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("Gemini API 키 설정")
        dialog.geometry("480x520")
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        if first_run:
            dialog.protocol("WM_DELETE_WINDOW", lambda: None)  # X로는 못 닫음

        title_text = "🔑 온율을 시작하려면 Gemini API 키가 필요합니다" if first_run else "🔑 Gemini API 키 설정"
        ctk.CTkLabel(dialog, fg_color="transparent", text=title_text, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold"), wraplength=430).pack(pady=(20, 4), padx=20)
        ctk.CTkLabel(
            dialog, fg_color="transparent", text="1분이면 끝나요 — 아래 4단계만 따라해주세요",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_MUTED,
        ).pack(pady=(0, 12))

        # 안심 문구 (신뢰를 주는 배지 형태로 나란히 배치)
        badge_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        badge_frame.pack(pady=(0, 14))
        for badge_text in ("💳 카드 등록 불필요", "🆓 무료로 발급", "🔒 이 PC에만 저장"):
            ctk.CTkLabel(
                badge_frame, text=badge_text, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color="white",
                fg_color=COLOR_CARD_BG, corner_radius=10, padx=10, pady=4,
            ).pack(side="left", padx=4)

        # 단계별 가이드 (문단 대신 번호가 매겨진 짧은 스텝으로, 한눈에 훑을 수 있게)
        steps_frame = ctk.CTkFrame(dialog, fg_color="#242424", corner_radius=10)
        steps_frame.pack(fill="x", padx=20, pady=(0, 12))

        steps = [
            ("1", "아래 링크를 눌러 Google AI Studio를 엽니다"),
            ("2", "사용 중인 Google 계정으로 로그인합니다"),
            ("3", "\"API 키 만들기\" 버튼을 누릅니다"),
            ("4", "생성된 키를 복사해서 아래 입력창에 붙여넣습니다"),
        ]
        for num, text in steps:
            row = ctk.CTkFrame(steps_frame, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=6)
            ctk.CTkLabel(
                row, text=num, width=22, height=22, corner_radius=11, fg_color=COLOR_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold"), text_color="white",
            ).pack(side="left", padx=(0, 10))
            ctk.CTkLabel(row, fg_color="transparent", text=text, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color="white", anchor="w", justify="left", wraplength=340).pack(side="left", fill="x", expand=True)

        link_label = ctk.CTkLabel(
            dialog, fg_color="transparent", image=load_icon("external-link", size=14), compound="left", text=("aistudio.google.com/apikey 열기" if load_icon("external-link", size=14) else "🔗 aistudio.google.com/apikey 열기"),
            text_color=COLOR_PRIMARY, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold", underline=True), cursor="hand2",
        )
        link_label.pack(pady=(0, 14))
        link_label.bind("<Button-1>", lambda e: webbrowser.open("https://aistudio.google.com/apikey"))

        entry = ctk.CTkEntry(dialog, width=380, placeholder_text="API 키를 붙여넣으세요", show="•")
        entry.pack(padx=20, pady=(0, 5))
        existing = config_manager.get_api_key()
        if existing:
            entry.insert(0, existing)

        status_label = ctk.CTkLabel(dialog, fg_color="transparent", text="", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), wraplength=400)
        status_label.pack(pady=(6, 6))

        def do_test():
            key = entry.get().strip()
            if not key:
                status_label.configure(text="키를 먼저 입력해주세요.", text_color=COLOR_DANGER)
                return
            status_label.configure(text="확인 중...", text_color=COLOR_WARNING_ALT)
            test_btn.configure(state="disabled", text="확인 중...")

            def _test():
                try:
                    test_client = genai.Client(api_key=key)
                    test_client.models.generate_content(model="gemini-flash-lite-latest", contents="ping")
                    dialog.after(0, lambda: status_label.configure(text="✅ 정상적으로 확인된 키입니다.", text_color=COLOR_SUCCESS))
                except Exception as e:
                    msg = f"❌ 키 확인 실패: {e}"
                    dialog.after(0, lambda: status_label.configure(text=msg, text_color=COLOR_DANGER))
                finally:
                    # 성공/실패와 무관하게 버튼은 반드시 다시 눌러볼 수 있는 상태로
                    # 되돌린다 — 안 그러면 실패했을 때 재시도할 방법이 없어진다.
                    dialog.after(0, lambda: test_btn.configure(state="normal", text="테스트"))

            threading.Thread(target=_test, daemon=True).start()

        def do_save():
            key = entry.get().strip()
            if not key:
                status_label.configure(text="키를 먼저 입력해주세요.", text_color=COLOR_DANGER)
                return
            config_manager.save_api_key(key)
            dialog.destroy()
            if first_run:
                self.log_message("System", "API 키가 저장되었습니다. 온율을 시작합니다.")
                if on_saved:
                    on_saved()
            else:
                self.log_message("System", "API 키가 저장되었습니다. 새 키로 재연결합니다...")
                self.trigger_reconnect()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        test_btn = ctk.CTkButton(btn_frame, text="테스트", width=90, command=do_test)
        test_btn.pack(side="left", padx=5)
        ctk.CTkButton(
            btn_frame, text=("저장하고 시작" if first_run else "저장"), width=140,
            fg_color=COLOR_SUCCESS_BTN, text_color="white", hover_color=COLOR_SUCCESS_BTN_HOVER, command=do_save,
        ).pack(side="left", padx=5)
        if not first_run:
            ctk.CTkButton(btn_frame, text="취소", width=80, fg_color=COLOR_NEUTRAL_BTN, text_color="white", hover_color=COLOR_BORDER, command=dialog.destroy).pack(side="left", padx=5)

        if not first_run:
            data_link = ctk.CTkLabel(
                dialog, fg_color="transparent", image=load_icon("database", size=14), compound="left", text=("내 데이터 백업 / 삭제 관리" if load_icon("database", size=14) else "🗄️ 내 데이터 백업 / 삭제 관리"),
                text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION, underline=True), cursor="hand2",
            )
            data_link.pack(pady=(14, 10))
            data_link.bind("<Button-1>", lambda e: self.open_data_management_dialog())

    def open_onboarding_dialog(self):
        """
        최초 성공 실행 시 한 번만 뜨는 기능 둘러보기 카드.

        탭이 9개나 되고 도구도 20개 넘게 있어서, API 키 설정만 끝내고 나면
        사용자가 "이걸로 뭘 할 수 있는지" 스스로 발견해야 하는 부담이 있었다.
        카테고리별 예시 문장을 보여줘서 학습 곡선을 낮춘다.
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("온율과 처음 만나보세요")
        dialog.geometry("480x560")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, fg_color="transparent", text="👋 온율에게 이렇게 말해보세요",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold"),
        ).pack(pady=(20, 5), padx=20)
        ctk.CTkLabel(
            dialog, fg_color="transparent", text="마이크에 대고 편하게 말씀하시면 됩니다",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_MUTED,
        ).pack(pady=(0, 15))

        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        categories = [
            ("💬 마음 이야기", "#9B59B6", [
                "오늘 기분 5점이야, 좀 힘들었어",
                "발표를 망쳐서 나는 뭘 해도 안 되는 사람 같아",
                "숨쉬기 가이드 좀 해줘",
            ]),
            ("🎯 행동/할일", COLOR_WARNING, [
                "오늘 산책이라도 해볼까 — 작은 목표 하나 추천해줘",
                "다음 주 화요일까지 세금 신고서 제출해야 해",
                "저녁 8시에 약 먹으라고 알려줘",
            ]),
            ("🖥️ 일상 비서", COLOR_PRIMARY, [
                "메모장 열어줘",
                "지난주에 저장한 이력서 파일 찾아줘",
                "오늘 날씨 어때?",
                "굿모닝 브리핑 해줘",
            ]),
            ("💤 대기 모드", COLOR_SUCCESS, [
                "잠깐 대기해 → 조용해짐",
                "온율아! → 다시 대화 시작",
            ]),
        ]

        for cat_title, color, examples in categories:
            card = ctk.CTkFrame(scroll, fg_color="#242424", corner_radius=10)
            card.pack(fill="x", pady=6)
            ctk.CTkLabel(
                card, fg_color="transparent", text=cat_title, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color=color,
            ).pack(anchor="w", padx=14, pady=(12, 4))
            for ex in examples:
                ctk.CTkLabel(
                    card, fg_color="transparent", text=f"“{ex}”", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_SECONDARY,
                    anchor="w", justify="left", wraplength=400,
                ).pack(anchor="w", padx=20, pady=2)
            ctk.CTkFrame(card, fg_color="transparent", height=8).pack()

        ctk.CTkLabel(
            dialog, fg_color="transparent", text="언제든 우측 상단 ⚙/🗣️/📝 버튼과 상단 탭들에서 더 많은 기능을 찾을 수 있어요.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color=COLOR_TEXT_MUTED, wraplength=440, justify="center",
        ).pack(pady=(0, 8), padx=15)

        def _close():
            config_manager.mark_onboarding_seen()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", _close)
        ctk.CTkButton(
            dialog, text="시작하기", width=140, fg_color=COLOR_SUCCESS_BTN, text_color="white", hover_color=COLOR_SUCCESS_BTN_HOVER, command=_close,
        ).pack(pady=(0, 15))

    def open_data_management_dialog(self):
        """내 데이터 백업(내보내기) 및 영구 삭제를 위한 창."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("데이터 관리")
        dialog.geometry("420x360")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        ctk.CTkLabel(dialog, fg_color="transparent", image=load_icon("database", size=18), compound="left", text=("내 데이터 관리" if load_icon("database", size=18) else "🗄️ 내 데이터 관리"), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold")).pack(pady=(20, 5), padx=20)
        ctk.CTkLabel(
            dialog, fg_color="transparent",
            text="기분/사고기록, 퀘스트, 긍정 기억, 알림, 할 일 등 모든 데이터는\n"
                 "이 PC에만 저장되어 있습니다. PC를 바꾸거나 초기화하기 전에\n"
                 "미리 백업해두시는 걸 권장합니다.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_DISABLED, justify="left", wraplength=380,
        ).pack(padx=20, pady=(0, 20))

        status_label = ctk.CTkLabel(dialog, fg_color="transparent", text="", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), wraplength=380)

        def do_backup():
            src = config_manager.get_db_path()
            if not os.path.exists(src):
                status_label.configure(text="아직 백업할 데이터가 없습니다.", text_color=COLOR_WARNING_ALT)
                status_label.pack(pady=(0, 10))
                return
            dest = filedialog.asksaveasfilename(
                defaultextension=".db",
                initialfile=f"onyuul_backup_{datetime.datetime.now().strftime('%Y%m%d')}.db",
                filetypes=[("SQLite DB", "*.db"), ("모든 파일", "*.*")],
                title="백업 위치 선택",
            )
            if not dest:
                return
            try:
                shutil.copy2(src, dest)
                status_label.configure(text=f"✅ 백업 완료: {dest}", text_color=COLOR_SUCCESS)
            except Exception as e:
                status_label.configure(text=f"❌ 백업 실패: {e}", text_color=COLOR_DANGER)
            status_label.pack(pady=(0, 10))

        ctk.CTkButton(dialog, text="📦 내 데이터 백업하기", command=do_backup).pack(padx=20, pady=(0, 10), fill="x")

        def open_delete_confirm():
            self._open_delete_confirmation(dialog)

        ctk.CTkButton(
            dialog, text="🗑️ 모든 데이터 영구 삭제", fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
            command=open_delete_confirm,
        ).pack(padx=20, pady=(0, 10), fill="x")

        ctk.CTkButton(dialog, text="닫기", width=100, fg_color=COLOR_NEUTRAL_BTN, text_color="white", hover_color=COLOR_BORDER, command=dialog.destroy).pack(pady=(10, 15))

    def _open_delete_confirmation(self, parent_dialog):
        """
        데이터 영구 삭제 최종 확인 창.

        민감한 데이터(정서 기록, 위기 관련 기록 포함)를 되돌릴 수 없이 지우는
        동작이라, 버튼 한 번으로 끝나지 않게 "삭제"라는 단어를 직접 입력해야만
        실행되도록 한 단계 더 확인을 받는다.
        """
        confirm = ctk.CTkToplevel(self)
        confirm.title("정말 삭제하시겠습니까?")
        confirm.geometry("380x250")
        confirm.attributes("-topmost", True)
        confirm.grab_set()

        ctk.CTkLabel(
            confirm, fg_color="transparent",
            text="⚠️ 기분/사고기록, 퀘스트, 긍정 기억, 알림, 할 일 등\n모든 데이터가 영구적으로 삭제됩니다.\n이 작업은 되돌릴 수 없습니다.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY, weight="bold"), text_color=COLOR_DANGER, justify="left",
        ).pack(pady=(20, 10), padx=20)

        entry = ctk.CTkEntry(confirm, placeholder_text="확인하려면 '삭제'를 입력하세요")
        entry.pack(padx=20, pady=(0, 10), fill="x")

        status_label = ctk.CTkLabel(confirm, fg_color="transparent", text="", font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_DANGER)
        status_label.pack()

        def do_delete():
            if entry.get().strip() != "삭제":
                status_label.configure(text="'삭제'라고 정확히 입력해주세요.")
                return
            try:
                db_path = config_manager.get_db_path()
                for path in (db_path, db_path + "-wal", db_path + "-shm"):
                    if os.path.exists(path):
                        os.remove(path)
                confirm.destroy()
                parent_dialog.destroy()
                self.log_message("System", "🗑️ 모든 데이터가 삭제되었습니다. 변경 사항을 적용하려면 온율을 재시작해주세요.")
            except Exception as e:
                status_label.configure(text=f"삭제 실패: {e}")

        btn_frame = ctk.CTkFrame(confirm, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="영구 삭제", width=120, fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER, command=do_delete).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="취소", width=100, fg_color=COLOR_NEUTRAL_BTN, text_color="white", hover_color=COLOR_BORDER, command=confirm.destroy).pack(side="left", padx=8)

    def _confirm_close_dialog(self):
        """
        X 버튼을 누르면 곧바로 최소화하거나 종료하지 않고, 게임 런처들처럼
        "정말 종료하시겠어요?"를 먼저 물어서 최소화/완전 종료를 직접 고르게 한다.
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("잠시만요")
        dialog.geometry("380x220")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, fg_color="transparent", text="정말 종료하시겠어요?",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold"),
        ).pack(pady=(20, 5), padx=20)
        ctk.CTkLabel(
            dialog, fg_color="transparent",
            text="트레이로 최소화하면 알림/일정 확인이 계속 동작하고,\n"
                 "완전히 종료하면 온율이 완전히 꺼집니다.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL), text_color=COLOR_TEXT_DISABLED, justify="center", wraplength=340,
        ).pack(pady=(0, 15), padx=20)

        def _do_minimize():
            dialog.destroy()
            self.minimize_to_tray()

        def _do_full_quit():
            dialog.destroy()
            self.on_close_request()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=5)
        ctk.CTkButton(
            btn_frame, text="🔽 트레이로 최소화", width=160,
            fg_color=COLOR_PRIMARY, text_color="white", hover_color="#2980B9", command=_do_minimize,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            btn_frame, text="⏻ 완전히 종료", width=140,
            fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER, command=_do_full_quit,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            dialog, text="취소", width=80, fg_color=COLOR_NEUTRAL_BTN, text_color="white", hover_color=COLOR_BORDER, command=dialog.destroy,
        ).pack(pady=(12, 0))

    def minimize_to_tray(self):
        """
        X 버튼을 눌러도 앱을 완전히 종료하지 않고 트레이로 숨긴다.

        알림/일정처럼 백그라운드에서 계속 동작해야 하는 기능들이 있는데, 창을
        닫을 때마다 프로세스 자체가 죽어버리면 그 기능들이 의미가 없어진다.
        "항상 곁에 있는 비서"라는 컨셉에도 맞지 않고. 실제 종료는 트레이 메뉴의
        "종료"를 통해서만 이루어지며, 그때 기존의 안전 체크인 절차를 거친다.

        withdraw() 대신 iconify()를 쓰는 이유: withdraw()는 작업표시줄에서도
        완전히 사라져서, 트레이 아이콘(Windows 11에서는 "숨겨진 아이콘" 화살표
        안에 접혀 들어가 있기도 함)을 못 찾으면 창을 복구할 방법이 안 보이는
        접근성 문제가 있었다. iconify()는 표준 "최소화" 동작이라 작업표시줄에
        계속 아이콘이 남고, 거기서도 클릭 한 번으로 복구할 수 있다.
        """
        if not TRAY_AVAILABLE:
            # 트레이 라이브러리가 없으면 기존처럼(안전 체크인 후 완전 종료) 동작한다.
            self.on_close_request()
            return

        self.iconify()

        if getattr(self, "tray_icon", None) is None:
            image = self._create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("열기", self._tray_show_window, default=True),
                pystray.MenuItem("종료", self._tray_quit),
            )
            self.tray_icon = pystray.Icon("ONyuul", image, "온율 (ONyuul)", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

        self.log_message("System", "🔽 최소화되었습니다. 작업표시줄이나 트레이 아이콘에서 다시 열 수 있어요. 알림/일정은 계속 동작합니다.")

    def _create_tray_image(self):
        """외부 아이콘 파일 없이, 코드로 간단한 트레이 아이콘 이미지를 생성한다."""
        img = Image.new("RGB", (64, 64), color="#1a1a2e")
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=COLOR_PRIMARY)
        return img

    def _tray_show_window(self, icon=None, item=None):
        # pystray 콜백은 트레이 라이브러리의 별도 스레드에서 실행되므로,
        # Tkinter 위젯 조작은 반드시 after()로 메인 스레드에 위임해야 한다.
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_quit(self, icon=None, item=None):
        self.after(0, self.on_close_request)

    def on_close_request(self):
        """실제 앱 종료 확인 창. 트레이 메뉴의 '종료'를 통해서만 호출된다."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("잠시만요")
        dialog.geometry("380x180")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, fg_color="transparent", text="종료하기 전에, Master 지금 괜찮으신가요?",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SECTION, weight="bold"), wraplength=320
        ).pack(pady=(20, 10), padx=20)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        def _close():
            dialog.destroy()
            if getattr(self, "tray_icon", None):
                self.tray_icon.stop()
            # 앱이 완전히 꺼지기 직전, DB를 다시 암호화해서 "쉬고 있는 동안"에는
            # 평문으로 남아있지 않게 한다. 실패해도(라이브러리 미설치 등) 앱
            # 종료 자체는 막지 않는다 — 그냥 평문으로 남을 뿐이고, 다음 실행
            # 때도 core/db.py가 정상적으로 그 평문 파일을 그대로 쓴다.
            try:
                db_crypto.encrypt_db_on_shutdown(_db_plain_path, _db_encrypted_path, _db_config_dir)
            except Exception as e:
                print(f"⚠️ [DB 암호화] 종료 시 암호화 중 예외: {e}")
            self.destroy()

        def _need_help():
            self.on_emergency_button_click()
            dialog.destroy()
            self.log_message("System", "괜찮아요. 언제든 다시 이야기해요. 필요하면 109/1577-0199로도 연결해보세요.")

        ctk.CTkButton(
            btn_frame, text="네, 괜찮아요", width=130, fg_color=COLOR_SUCCESS_BTN, text_color="white", hover_color=COLOR_SUCCESS_BTN_HOVER, command=_close
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_frame, text="도움이 필요해요", width=150, fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER, command=_need_help
        ).pack(side="left", padx=8)

    def on_voice_change(self, choice: str):
        voice_map = {
            "Aoede (밝은 여성)": "Aoede",
            "Kore (부드러운 여성)": "Kore",
            "Puck (경쾌한 남성)": "Puck",
            "Fenrir (신뢰감 남성)": "Fenrir",
            "Charon (중후한 남성)": "Charon"
        }
        self.selected_voice = voice_map.get(choice, "Aoede")
        self.log_message("System", f"목소리가 [{self.selected_voice}](으)로 변경되었습니다. 새 목소리로 재연결합니다...")
        self.trigger_reconnect()

    def on_mode_change(self):
        """주/야간 케어 모드: AI 응답 톤(간결함 등)에만 영향을 준다.
        화면 테마는 이제 완전히 별개인 on_theme_change/theme_mode가 담당한다."""
        mode = self.mode_var.get()
        self.night_mode_override = mode
        if mode == "ON":
            self.log_message("System", "🌙 야간 케어 모드가 강제 활성화되었습니다.")
        elif mode == "OFF":
            self.log_message("System", "☀️ 주간 케어 모드가 강제 활성화되었습니다.")
        else:
            self.log_message("System", "🔄 주/야간 케어 모드가 자동(시간 기반)으로 설정되었습니다.")

    def on_theme_change(self, choice: str):
        """화면 테마 전용 핸들러. 케어 모드(night_mode_override)와 완전히 독립적으로 동작한다."""
        mode_map = {"다크": "Dark", "라이트": "Light", "자동": "AUTO"}
        self.theme_mode = mode_map.get(choice, "AUTO")
        config_manager.save_theme_mode(self.theme_mode)

        if self.theme_mode == "AUTO":
            now_hour = datetime.datetime.now().hour
            is_night = (now_hour >= 22 or now_hour < 6)
            ctk.set_appearance_mode("Dark" if is_night else "Light")
            self.log_message("System", "🎨 화면 테마가 자동(시간 기반)으로 설정되었습니다.")
        else:
            ctk.set_appearance_mode(self.theme_mode)
            self.log_message("System", f"🎨 화면 테마가 {choice}(으)로 변경되었습니다.")

        self._resync_scrollable_frame_backgrounds()

    def _resync_scrollable_frame_backgrounds(self):
        """
        CustomTkinter의 알려진 제약: CTkScrollableFrame은 내부적으로 일반
        Tkinter Canvas 위에 구현되어 있는데, 이 캔버스의 배경색은 위젯 생성
        시점에만 반영되고 이후 set_appearance_mode()로 테마를 바꿔도 자동으로
        따라가지 않는다. 그 결과 다른 요소는 전부 테마가 바뀌었는데 스크롤
        영역만 예전 테마의 어두운/밝은 배경이 그대로 남아있는 것처럼 보인다.

        처음 시도했던 방식(frame._apply_appearance_mode(frame._fg_color))이 안 먹힌
        이유: 이 스크롤 프레임들은 전부 fg_color="transparent"로 만들어져 있는데,
        "transparent"는 실제 색상이 아니라 CTk 전용 특수 값이라 _apply_appearance_mode가
        이걸로는 진짜 반영할 색을 못 뽑아낸다. 그래서 이번엔 테마 매니저에서
        "CTkFrame"의 실제 배경색(밝은/어두운 모드별 튜플)을 직접 가져와 쓴다 —
        "투명"이 실제로 비쳐 보여야 하는 배경이 바로 이 표준 프레임 색이다.

        추가로, 공개 API인 .configure(fg_color="transparent")도 한 번 더 호출해서
        위젯 스스로 내부 상태를 다시 계산하게 만든다 — 혹시 customtkinter 버전에
        따라 내부 캔버스 접근 방식이 다르더라도 이쪽이 먼저 통할 수 있다.

        customtkinter의 내부(private) 속성에 의존하는 부분이 있어 다소 취약하지만,
        실패해도 조용히 넘어간다 — 이것 때문에 앱이 죽으면 안 된다.
        """
        scrollable_frames = [
            getattr(self, name, None) for name in (
                "anchors_scroll", "quests_scroll", "thoughts_scroll",
                "journal_scroll", "reminders_scroll", "tasks_scroll",
            )
        ]

        try:
            frame_colors = ctk.ThemeManager.theme["CTkFrame"]["fg_color"]
            mode_idx = 0 if ctk.get_appearance_mode() == "Light" else 1
            resolved_color = frame_colors[mode_idx]
        except Exception as e:
            print(f"⚠️ [Theme Resync] 테마 매니저에서 배경색을 못 가져왔습니다: {e}")
            resolved_color = None

        for frame in scrollable_frames:
            if frame is None:
                continue
            try:
                frame.configure(fg_color="transparent")
            except Exception as e:
                print(f"⚠️ [Theme Resync] configure() 실패: {e}")
            if resolved_color is not None:
                try:
                    frame._parent_canvas.configure(bg=resolved_color)
                except Exception as e:
                    print(f"⚠️ [Theme Resync] 캔버스 배경 설정 실패: {e}")

    def on_autostart_toggle(self):
        enable = self.autostart_var.get()
        command = _get_startup_command()
        success = config_manager.set_autostart_enabled(enable, command)
        if success:
            self.log_message("System", "⏻ Windows 시작 시 자동 실행이 " + ("켜졌습니다." if enable else "꺼졌습니다."))
        else:
            # 실패했으면(권한 문제 등) 체크박스 상태를 원래대로 되돌려서
            # 실제 레지스트리 상태와 화면이 어긋나지 않게 한다.
            self.autostart_var.set(not enable)
            self.log_message("System", "자동 실행 설정에 실패했습니다.")

    def check_for_updates(self):
        """
        시작 시 한 번, 백그라운드 스레드에서 정적 버전 파일(UPDATE_CHECK_URL)을
        확인한다. 네트워크 오류/URL 미설정/JSON 형식 오류 등 어떤 이유로든
        실패해도 조용히 넘어간다 — 업데이트 확인은 부가 기능이지, 이것 때문에
        앱 시작이 늦어지거나 오류가 노출되면 안 된다.
        """
        def _check():
            try:
                import json
                req = urllib.request.Request(UPDATE_CHECK_URL, headers={"User-Agent": "ONyuul-UpdateChecker"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                remote_version = data.get("version", "")
                download_url = data.get("download_url", "")
                notes = data.get("notes", "")
                if remote_version and is_newer_version(remote_version):
                    self.after(0, lambda: self.show_update_banner(remote_version, download_url, notes))
            except Exception as e:
                # 조용히 무시 (콘솔에만 남겨서 디버깅은 가능하게 함)
                print(f"ℹ️ [Update Check] 확인 실패 또는 URL 미설정: {e}")

        threading.Thread(target=_check, daemon=True).start()

    def show_update_banner(self, version: str, download_url: str, notes: str = ""):
        # 아이콘(🎉)은 이미 update_banner_label 생성 시 이미지로 붙어있으니, 여기서는
        # 텍스트에 이모지를 다시 넣지 않는다 — 넣으면 이미지+이모지가 중복돼 보인다.
        has_icon = load_icon("sparkles", size=16) is not None
        text = f"새 버전 {version}이(가) 있습니다." if has_icon else f"🎉 새 버전 {version}이(가) 있습니다."
        if notes:
            text += f" ({notes})"
        self.update_banner_label.configure(text=text)
        self.update_download_btn.configure(command=lambda: webbrowser.open(download_url) if download_url else None)
        self.update_banner.pack(fill="x", side="top", before=self.header_frame)

    def _auto_theme_tick(self):
        """theme_mode가 AUTO일 때 시간에 따라 다크/라이트 테마를 주기적으로 재확인해서
        맞춘다. Dark/Light로 수동 고정된 경우엔 케어 모드와 무관하게 아무것도 건드리지
        않는다 (케어 모드 ↔ 테마가 완전히 분리됐다)."""
        if self.theme_mode == "AUTO":
            now_hour = datetime.datetime.now().hour
            is_night = (now_hour >= 22 or now_hour < 6)
            new_mode = "Dark" if is_night else "Light"
            if ctk.get_appearance_mode() != new_mode:
                ctk.set_appearance_mode(new_mode)
                self._resync_scrollable_frame_backgrounds()
        self.after(300000, self._auto_theme_tick)  # 5분마다 재확인

    def _reminder_check_tick(self):
        """30초마다 마감된 알림이 있는지 확인하고, 있으면 온율이가 자연스럽게
        말로 전달하도록 세션에 신호를 보낸다."""
        try:
            due = reminder_db.get_due_reminders()
        except Exception as e:
            print(f"⏰ [Reminder Check Error]: {e}")
            due = []

        for reminder in due:
            self._speak_reminder(reminder)

        # 탭을 직접 열어보지 않아도, 시간이 지나 마감이 새로 발생한 항목이
        # 있으면 배지가 따라오도록 이 주기 체크에서도 같이 갱신한다.
        self._update_tab_badges()

        self.after(30000, self._reminder_check_tick)

    def _safety_plan_check_tick(self):
        """
        24시간마다 안전 계획이 마지막으로 업데이트된 지 3개월(90일)이 넘었는지
        확인한다. 넘었으면 온율이가 부드럽게 재점검을 권하도록 알림을 예약한다.

        한 번도 안전 계획을 작성하지 않은 사용자에게는 "업데이트"를 재촉하는 게
        어색하므로(아직 만든 적도 없는데 다시 살펴보라는 건 맥락이 안 맞음)
        건드리지 않는다 — 최초 작성을 유도하는 건 별개의 UX로 다룰 문제다.
        """
        try:
            plan = memory_db.get_safety_plan()
            updated_at = plan.get("updated_at")
            if updated_at:
                try:
                    updated_dt = datetime.datetime.strptime(str(updated_at)[:19], "%Y-%m-%d %H:%M:%S")
                    stale = (datetime.datetime.now() - updated_dt).days >= 90
                except (ValueError, TypeError):
                    stale = False

                if stale:
                    existing = reminder_db.get_upcoming_reminders(limit=50)
                    already_scheduled = any("안전 계획" in str(r.get("title", "")) for r in existing)
                    if not already_scheduled:
                        remind_at = (datetime.datetime.now() + datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
                        reminder_db.create_reminder(
                            title=(
                                "안전 계획을 마지막으로 업데이트한 지 3개월이 지났어요. "
                                "요즘 상황이 바뀌었다면 Master에게 안전 계획을 다시 "
                                "살펴보시겠냐고 부담 없이 물어봐 주세요."
                            ),
                            remind_at=remind_at,
                            kind="schedule",
                        )
                        self.after(0, self.render_reminder_list)
        except Exception as e:
            print(f"⚠️ [Safety Plan Check Error]: {e}")

        self.after(86400000, self._safety_plan_check_tick)  # 24시간마다 재확인

    def _maybe_show_toast(self, title: str, message: str):
        """
        창이 최소화(트레이/작업표시줄)된 상태일 때만 Windows 토스트 알림을 띄운다.

        창이 이미 화면에 떠 있으면 채팅 로그에서 바로 보이니 토스트까지 띄우면
        중복이라, iconify() 상태(self.state() == "iconic")일 때만 알린다.
        pystray.Icon.notify()는 트레이 아이콘이 실제로 실행 중일 때만 동작하므로
        tray_icon이 없으면 조용히 넘어간다.
        """
        if not TRAY_AVAILABLE or getattr(self, "tray_icon", None) is None:
            return
        try:
            if self.state() == "iconic":
                self.tray_icon.notify(message, title)
        except Exception as e:
            print(f"⚠️ [Toast Notify Error]: {e}")

    def _speak_reminder(self, reminder: dict):
        """
        마감된 알림 하나를 실제로 전달한다.

        - 위기 개입 중(crisis_active)에는 절대 끼어들지 않는다 — 다음 체크 때
          다시 시도되도록 mark_reminder_notified를 호출하지 않고 그냥 반환한다.
        - 복약(medication) 알림은 건강과 직결되므로 대기 모드 중에도 전달한다.
        - 그 외 일반 일정(schedule)은 대기 모드를 존중해 조용히 다음 체크로 미룬다.
        """
        if self.app_state.crisis_active:
            return
        if reminder.get("kind") != "medication" and self.app_state.is_standby:
            return

        kind_label = "복약" if reminder.get("kind") == "medication" else "일정"
        title = reminder.get("title", "")
        prompt = f"[시스템 알림] 지금 Master에게 다음 {kind_label} 알림을 자연스럽게 전해주세요: {title}"

        if self.async_session and app_loop:
            asyncio.run_coroutine_threadsafe(
                self.async_session.send_realtime_input(text=prompt), app_loop
            )
        self.log_message("System", f"⏰ 알림 전달: {title}")
        self._maybe_show_toast(f"⏰ {kind_label} 알림", title)

        try:
            reminder_db.mark_reminder_notified(reminder["id"])
        except Exception as e:
            print(f"⏰ [Reminder Mark Error]: {e}")

        self.after(0, self.render_reminder_list)

    def render_reminder_list(self):
        """알림 관리 탭의 목록을 다시 그린다."""
        if not hasattr(self, "reminders_scroll"):
            return
        for widget in self.reminders_scroll.winfo_children():
            widget.destroy()

        try:
            rows = reminder_db.get_upcoming_reminders(limit=30)
        except Exception as e:
            print(f"⏰ [Reminder List Error]: {e}")
            rows = []

        self._update_tab_badges()

        if not rows:
            self._render_empty_state(
                self.reminders_scroll, "bell",
                "등록된 알림이 없습니다.\n"
                "💡 \"저녁 8시에 혈압약 먹으라고 알려줘\"처럼 말하거나, 아래에서 직접 등록해보세요.",
            )
            return

        for r in rows:
            icon = "💊" if r.get("kind") == "medication" else "📅"
            repeat_label = {"daily": " (매일)", "weekly": " (매주)"}.get(r.get("repeat_rule"), "")

            card = ctk.CTkFrame(self.reminders_scroll, corner_radius=8, fg_color=COLOR_CARD_BG)
            card.pack(fill="x", padx=5, pady=4)

            ctk.CTkLabel(
                card, fg_color="transparent", text=f"{icon} {r.get('remind_at', '')}{repeat_label}",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold"), text_color=COLOR_PRIMARY,
            ).pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(
                card, fg_color="transparent", text=r.get("title", ""), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY), text_color="white", anchor="w",
            ).pack(fill="x", padx=12, pady=(0, 4))

            ctk.CTkButton(
                card, text=("삭제" if load_icon("trash-2", size=14) else "🗑 삭제"), image=load_icon("trash-2", size=14), compound="left", width=70, height=22,
                fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
                command=lambda rid=r["id"], c=card: self.request_delete_with_undo(
                    c, "알림", lambda: reminder_db.delete_reminder(rid), self.render_reminder_list
                ),
            ).pack(anchor="e", padx=8, pady=(0, 8))

    def manual_add_reminder(self):
        title = self.reminder_title_entry.get().strip()
        date_str = self.reminder_date_entry.get().strip()
        time_str = self.reminder_time_entry.get().strip()
        kind = "medication" if self.reminder_kind_var.get() == "복약" else "schedule"
        repeat_map = {"없음": "", "매일": "daily", "매주": "weekly"}
        repeat_rule = repeat_map.get(self.reminder_repeat_var.get(), "")

        if not title or not date_str or not time_str:
            self.log_message("System", "알림 제목/날짜/시간을 모두 입력해주세요.")
            return

        remind_at = f"{date_str} {time_str}"
        result = reminder_db.create_reminder(title=title, remind_at=remind_at, kind=kind, repeat_rule=(repeat_rule or None))
        if result.get("status") == "success":
            self.reminder_title_entry.delete(0, "end")
            self.log_message("System", f"⏰ 알림을 등록했습니다: {title} ({remind_at})")
            self.render_reminder_list()
        else:
            self.log_message("System", f"알림 등록 실패: {result.get('message', '')}")

    def render_task_list(self):
        """할 일 탭의 목록을 다시 그린다. 지난 마감은 빨간색으로 강조한다."""
        if not hasattr(self, "tasks_scroll"):
            return
        for widget in self.tasks_scroll.winfo_children():
            widget.destroy()

        try:
            rows = task_db.get_pending_tasks(limit=50)
            overdue_ids = {t["id"] for t in task_db.get_overdue_tasks()}
        except Exception as e:
            print(f"✅ [Task List Error]: {e}")
            rows = []
            overdue_ids = set()

        self._update_tab_badges()

        if not rows:
            self._render_empty_state(
                self.tasks_scroll, "check-square",
                "등록된 할 일이 없습니다.\n"
                "💡 \"다음 주 화요일까지 보고서 제출해야 해\"처럼 말하거나, 아래에서 직접 등록해보세요.",
            )
            return

        priority_color = {"high": COLOR_DANGER, "medium": COLOR_WARNING, "low": "#7F8C8D"}
        priority_label = {"high": "높음", "medium": "보통", "low": "낮음"}

        for t in rows:
            is_overdue = t["id"] in overdue_ids
            due_text = t.get("due_date") or "마감 없음"
            if is_overdue:
                due_text = f"⚠️ 지남 ({due_text})"

            card = ctk.CTkFrame(self.tasks_scroll, corner_radius=8, fg_color=COLOR_CARD_BG)
            card.pack(fill="x", padx=5, pady=4)

            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=12, pady=(8, 0))

            ctk.CTkLabel(
                header_row, fg_color="transparent", text=due_text, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_LABEL, weight="bold"),
                text_color=COLOR_DANGER if is_overdue else COLOR_PRIMARY,
            ).pack(side="left")
            ctk.CTkLabel(
                header_row, fg_color="transparent", text=priority_label.get(t.get("priority"), "보통"),
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color=priority_color.get(t.get("priority"), COLOR_WARNING),
            ).pack(side="left", padx=(8, 0))

            ctk.CTkButton(
                header_row, text=("완료" if load_icon("check", size=14) else "✅ 완료"), image=load_icon("check", size=14), compound="left", width=60, height=22,
                fg_color=COLOR_SUCCESS_BTN, text_color="white", hover_color=COLOR_SUCCESS_BTN_HOVER,
                command=lambda tid=t["id"]: self.manual_complete_task(tid),
            ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(
                header_row, text=("" if load_icon("trash-2", size=14) else "🗑"), image=load_icon("trash-2", size=14), width=32, height=22,
                fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
                command=lambda tid=t["id"], c=card: self.request_delete_with_undo(
                    c, "할 일", lambda: task_db.delete_task(tid), self.render_task_list
                ),
            ).pack(side="right", padx=(4, 0))

            ctk.CTkLabel(
                card, fg_color="transparent", text=t.get("title", ""), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY), text_color="white", anchor="w",
            ).pack(fill="x", padx=12, pady=(2, 8))

    def manual_add_task(self):
        title = self.task_title_entry.get().strip()
        due_date = self.task_due_entry.get().strip()
        priority_map = {"낮음": "low", "보통": "medium", "높음": "high"}
        priority = priority_map.get(self.task_priority_var.get(), "medium")

        if not title:
            self.log_message("System", "할 일 제목을 입력해주세요.")
            return

        result = task_db.create_task(title=title, due_date=(due_date or None), priority=priority)
        if result.get("status") == "success":
            self.task_title_entry.delete(0, "end")
            self.task_due_entry.delete(0, "end")
            self.log_message("System", f"✅ 할 일을 추가했습니다: {title}")
            self.render_task_list()
        else:
            self.log_message("System", f"할 일 추가 실패: {result.get('message', '')}")

    def manual_complete_task(self, task_id: int):
        try:
            task_db.complete_task(task_id=task_id)
            self.render_task_list()
        except Exception as e:
            print(f"✅ [Manual Task Complete Error]: {e}")

    def manual_save_journal_entry(self):
        content = self.journal_entry_box.get("1.0", "end").strip()
        if not content:
            return
        try:
            result = memory_db.save_journal_entry(content=content)
            if result.get("status") == "success":
                self.journal_entry_box.delete("1.0", "end")
                self.render_journal_entries()
                self.log_message("System", "📔 일기가 저장되었습니다.")
            else:
                self.log_message("System", f"일기 저장 실패: {result.get('message', '')}")
        except Exception as e:
            print(f"📔 [Journal Save Error]: {e}")

    def render_journal_entries(self):
        if not hasattr(self, "journal_scroll"):
            return
        for widget in self.journal_scroll.winfo_children():
            widget.destroy()

        try:
            entries = memory_db.get_journal_entries(limit=30)
        except Exception as e:
            print(f"📔 [Journal List Error]: {e}")
            entries = []

        if not entries:
            self._render_empty_state(
                self.journal_scroll, "book-open",
                "아직 쓴 일기가 없습니다.\n💡 위 입력창에 편하게 적고 저장 버튼을 눌러보세요.",
            )
            return

        for e in entries:
            card = ctk.CTkFrame(self.journal_scroll, corner_radius=8, fg_color=COLOR_CARD_BG)
            card.pack(fill="x", padx=5, pady=4)

            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=12, pady=(8, 0))
            date_str = str(e.get("created_at", ""))[:16]
            ctk.CTkLabel(header_row, fg_color="transparent", text=date_str, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_CAPTION), text_color=COLOR_TEXT_MUTED).pack(side="left")
            ctk.CTkButton(
                header_row, text=("" if load_icon("trash-2", size=14) else "🗑"), image=load_icon("trash-2", size=14), width=28, height=22, fg_color=COLOR_DANGER_BTN, text_color="white", hover_color=COLOR_DANGER_BTN_HOVER,
                command=lambda eid=e["id"], c=card: self.request_delete_with_undo(
                    c, "일기", lambda: memory_db.delete_journal_entry(eid), self.render_journal_entries
                ),
            ).pack(side="right")

            ctk.CTkLabel(
                card, fg_color="transparent", text=e.get("content", ""), font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_BODY), text_color="white",
                anchor="w", justify="left", wraplength=520,
            ).pack(fill="x", padx=12, pady=(4, 10))

    def send_text_message(self):
        text = self.text_entry.get().strip()
        if not text:
            return
        self.text_entry.delete(0, "end")

        if not self.app_state.crisis_active and not self.app_state.is_standby:
            score_match = re.search(r"(\d{1,2})\s*점", text) or re.search(r"기분[^\d]*(\d{1,2})", text)
            if score_match:
                score_val = score_match.group(1)
                if 1 <= float(score_val) <= 10:
                    print(f"\n🎯 [텍스트 감지 성공] {score_val}점 포착 -> DB 저장 및 차트 즉시 반영!")
                    log_mood_and_sleep(mood_score=score_val)
                    self.after(0, self.render_mood_chart)

        if self.app_state.is_standby:
            if contains_wake_word(text):
                self.set_standby_mode(False)
                self.log_message("Master (Text)", text)
                if self.async_session and app_loop:
                    asyncio.run_coroutine_threadsafe(self.async_session.send_realtime_input(text=text), app_loop)
            else:
                self.log_message("System", "현재 대기 모드입니다. '온율'을 포함해 입력하세요.")
        else:
            if any(cmd in text for cmd in ["잠깐 대기", "잠시 대기", "대기해", "조용히 해"]):
                self.set_standby_mode(True)
            else:
                self.log_message("Master (Text)", text)
                if self.async_session and app_loop:
                    asyncio.run_coroutine_threadsafe(self.async_session.send_realtime_input(text=text), app_loop)

# ---------------------------------------------------------------------------
# 백그라운드 Asyncio Gemini Live 스트리밍 루프
# ---------------------------------------------------------------------------
app_loop = None

async def send_mic_audio(session, p, state: SessionState, gui: ONyuulGUI):
    input_stream = p.open(format=pyaudio.paInt16, channels=1, rate=INPUT_RATE, input=True, frames_per_buffer=CHUNK_SIZE)
    try:
        while True:
            data = input_stream.read(CHUNK_SIZE, exception_on_overflow=False)

            # 🔇 AI가 스피커로 말하는 중에는 마이크 입력을 세션에 보내지 않습니다.
            # (하드웨어 AEC 없이는 스피커 소리를 마이크가 다시 주워, AI가 자기 목소리에
            #  자기가 반응하는 에코 피드백 루프가 생길 수 있어 소프트웨어적으로 차단합니다.
            #  단, 이 동안은 사용자가 말로 끼어들어도(barge-in) AI가 즉시 반응하지 못하고
            #  AI 발화가 끝난 뒤에야 사용자 음성이 전달됩니다.)
            if state.is_speaking:
                gui.update_mic_level(0.0)
                await asyncio.sleep(0.01)
                continue

            if state.mic_hard_muted:
                # 대기 모드와 달리 웨이크워드 감지용 오디오조차 보내지 않는다 —
                # 사용자가 명시적으로 "마이크 끄기"를 눌렀을 때만 켜지는 상태라,
                # 서버로 아예 아무것도 나가지 않아야 한다.
                gui.update_mic_level(0.0)
                await asyncio.sleep(0.05)
                continue

            if not state.is_standby:
                audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = np.sqrt(np.mean(audio_data**2)) if len(audio_data) > 0 else 0
                normalized_level = min(1.0, float(rms / 4000.0))
                gui.update_mic_level(normalized_level)
            else:
                gui.update_mic_level(0.0)

            await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
            await asyncio.sleep(0.005)
    except (asyncio.CancelledError, websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedOK):
        pass
    except Exception as e:
        print(f"🎙️ [Mic Stream Error]: {e}")
    finally:
        try:
            input_stream.stop_stream()
            input_stream.close()
        except Exception:
            pass

async def handle_brain_dump(text: str, gui: "ONyuulGUI", state: SessionState = None):
    """
    이번 턴에 Gemini가 스스로 도구를 호출하지 않았을 때만 실행되는 백업 분류 경로.

    classify_brain_dump(순수 함수, productivity_manager.py)로 1차 분류한 뒤,
    카테고리에 맞는 core.mental_care 저장 래퍼(위의 save_user_memory 등)를 호출한다.
    호출부(receive_speaker_audio)에서 state.crisis_active가 아닐 때만 이 함수를
    create_task로 실행하므로, 정규식(1차) 필터를 통과한 텍스트만 여기 도달한다.

    다만 LLM(2차) 필터는 비동기·네트워크 왕복이 있어 이 함수보다 늦게 끝날 수 있다.
    퀘스트를 저장했다면 그 id와 원문을 state.last_brain_dump_quest에 남겨두고,
    나중에 LLM 필터가 같은 턴을 뒤늦게 위기로 확인하면(run_llm_safety_check 참고)
    이 저장을 자동으로 되돌릴 수 있게 한다.
    """
    result = classify_brain_dump(text)
    category = result["category"]
    extracted = result["extracted"]

    if category == "skip":
        return

    try:
        if category == "mood":
            await asyncio.to_thread(log_mood_and_sleep, **extracted)
            gui.after(0, gui.render_mood_chart)
            gui.log_message("System", "🧠 [브레인덤프] 기분/수면 기록을 자동으로 저장했습니다.")
        elif category == "quest":
            save_result = await asyncio.to_thread(create_micro_quest, **extracted)
            quest_id = save_result.get("quest_id") if isinstance(save_result, dict) else None
            if state is not None and quest_id is not None:
                state.last_brain_dump_quest = {"id": quest_id, "text": text}
            gui.after(0, gui.refresh_quest_progress)
            gui.log_message("System", f"🧠 [브레인덤프] 새 퀘스트를 자동 등록했습니다: {extracted['quest_title']}")
        elif category == "anchor":
            await asyncio.to_thread(save_positive_anchor, **extracted)
            gui.after(0, gui.render_positive_gallery)
            gui.log_message("System", "🧠 [브레인덤프] 긍정적인 기억을 자동으로 저장했습니다.")
        elif category == "memory":
            await asyncio.to_thread(save_user_memory, **extracted)
            gui.log_message("System", "🧠 [브레인덤프] 대화 내용을 메모리에 자동 저장했습니다.")
    except Exception as e:
        # DB 오류 등으로 여기서 예외가 나도 receive_speaker_audio의 메인 루프에는
        # 영향을 주지 않는다 (create_task로 분리 실행되므로). 그래도 조용히
        # 삼키지 않고 콘솔에 남긴다.
        print(f"⚠️ [브레인덤프 오류] category={category}: {e}")


async def run_llm_safety_check(interceptor: CrisisInterceptor, state: SessionState, text: str, gui: "ONyuulGUI"):
    """
    LLM 2차 필터를 실행하고, 뒤늦게 위기로 확인되면 같은 턴에 브레인덤프가 이미
    저장해버린 퀘스트가 있는지 확인해 자동으로 되돌린다(rollback).

    브레인덤프(로컬 저장, 빠름)와 LLM 필터(네트워크 왕복, 느림)가 각자 독립된
    백그라운드 태스크로 동시에 실행되기 때문에, 어떤 경우엔 저장이 먼저 끝나버릴
    수 있다 — 이 함수가 그 틈을 사후에 메운다. (근본적으로는 이런 문구 자체가
    1차 정규식 목록에 없었던 게 원인이라, 그쪽도 계속 보강해야 한다.)
    """
    triggered = await interceptor.maybe_intercept_llm(state, text)
    if not triggered:
        return

    pending = getattr(state, "last_brain_dump_quest", None)
    if pending and pending.get("text") == text:
        try:
            await asyncio.to_thread(memory_db.delete_quest, pending["id"])
            gui.after(0, gui.refresh_quest_progress)
            gui.log_message(
                "System",
                "⚠️ 방금 자동 저장된 퀘스트를 안전 필터가 뒤늦게 위기 신호로 확인해 자동으로 취소했습니다.",
            )
        except Exception as e:
            print(f"⚠️ [Auto Rollback Error]: {e}")
        state.last_brain_dump_quest = None


async def receive_speaker_audio(session, p, state: SessionState, interceptor: CrisisInterceptor, gui: ONyuulGUI):
    output_stream = p.open(format=pyaudio.paInt16, channels=1, rate=OUTPUT_RATE, output=True)
    model_audio_buffer = bytearray()
    loop = asyncio.get_running_loop()
    crisis_task = None
    llm_task = None  # LLM 2차 필터용 (문장이 끝나길 기다리지 않고 부분 텍스트에도 걸어둠)
    tool_called_this_turn = False  # 이번 턴에 Gemini가 스스로 도구를 호출했는지 (브레인덤프 중복 방지용)
    exit_intent_shown_this_turn = False  # 종료 의도 감지 시 확인창 중복으로 안 띄우기 위한 턴별 플래그

    if not hasattr(state, "user_speech_buffer"):
        state.user_speech_buffer = ""
    if not hasattr(state, "last_brain_dump_quest"):
        state.last_brain_dump_quest = None

    try:
        while True:
            async for response in session.receive():
                tool_call = getattr(response, "tool_call", None)
                if tool_call:
                    tool_called_this_turn = True
                    gui.update_status("🔵 생각 중...", COLOR_PRIMARY)
                    for function_call in tool_call.function_calls:
                        name = function_call.name
                        args = function_call.args
                        call_id = function_call.id

                        if state.crisis_active or state.is_standby:
                            result = "안전 인터셉터 또는 대기 모드 상태입니다."
                        else:
                            # ⚠️ 이 try/except가 없으면, 도구 하나(예: 시스템 프로그램 실행
                            # 실패, 일시적 DB 오류, 날씨 API 네트워크 오류)만 실패해도 예외가
                            # 그대로 전파되어 asyncio.gather 전체가 죽고, 대화 전체가 끊겨
                            # 재연결 배너가 뜨게 된다. 도구 실패는 흔히 있을 수 있는 일이니,
                            # 그 도구 하나만 실패로 처리하고 대화는 계속 이어지게 한다.
                            try:
                                if name == "save_user_memory":
                                    result = await asyncio.to_thread(save_user_memory, information=args.get("information", ""), category=args.get("category", "cbt_context"))
                                elif name == "log_mood_and_sleep":
                                    result = await asyncio.to_thread(log_mood_and_sleep, mood_score=args.get("mood_score", ""), sleep_hours=args.get("sleep_hours", ""), emotion_keywords=args.get("emotion_keywords", ""), notes=args.get("notes", ""))
                                    gui.after(0, gui.render_mood_chart)
                                elif name == "get_mood_history":
                                    result = await asyncio.to_thread(get_mood_history, days=int(args.get("days", 7)))
                                elif name == "add_thought_record":
                                    result = await asyncio.to_thread(
                                        add_thought_record,
                                        situation=args.get("situation", ""),
                                        automatic_thought=args.get("automatic_thought", ""),
                                        alternative_thought=args.get("alternative_thought", ""),
                                        emotion_before=int(args.get("emotion_before", 50)),
                                        emotion_after=int(args.get("emotion_after", 50)),
                                        cognitive_distortion=args.get("cognitive_distortion", ""),
                                    )
                                    gui.after(0, gui.render_thought_journal)
                                    gui.log_message("System", "🧠 사고기록이 저장되었습니다.")
                                elif name == "start_grounding_guide":
                                    result = await asyncio.to_thread(start_grounding_guide, technique=args.get("technique", "breathing"))
                                elif name == "create_reminder":
                                    result = await asyncio.to_thread(
                                        create_reminder,
                                        title=args.get("title", ""),
                                        remind_at=args.get("remind_at", ""),
                                        kind=args.get("kind", "schedule"),
                                        repeat_rule=args.get("repeat_rule", ""),
                                    )
                                    gui.after(0, gui.render_reminder_list)
                                elif name == "get_upcoming_reminders":
                                    result = await asyncio.to_thread(get_upcoming_reminders, limit=int(args.get("limit", 10)))
                                elif name == "create_task":
                                    result = await asyncio.to_thread(
                                        create_task,
                                        title=args.get("title", ""),
                                        due_date=args.get("due_date", ""),
                                        priority=args.get("priority", "medium"),
                                    )
                                    gui.after(0, gui.render_task_list)
                                elif name == "complete_task":
                                    result = await asyncio.to_thread(complete_task, task_title=args.get("task_title", ""))
                                    gui.after(0, gui.render_task_list)
                                elif name == "get_pending_tasks":
                                    result = await asyncio.to_thread(get_pending_tasks, limit=int(args.get("limit", 20)))
                                elif name == "log_grounding_session":
                                    result = await asyncio.to_thread(log_grounding_session, technique_type=args.get("technique_type", ""), feedback=args.get("feedback", ""))
                                elif name == "save_positive_anchor":
                                    result = await asyncio.to_thread(save_positive_anchor, content=args.get("content", ""), emotion_tag=args.get("emotion_tag", "소소한 기쁨"))
                                    gui.after(0, gui.render_positive_gallery)
                                elif name == "recall_positive_anchors":
                                    result = await asyncio.to_thread(recall_positive_anchors, limit=int(args.get("limit", 3)))
                                elif name == "create_micro_quest":
                                    q_title = args.get("quest_title", "")
                                    gui.log_message("ONyuul Quest", f"새 행동 활성화 미션: [{q_title}]")
                                    result = await asyncio.to_thread(create_micro_quest, quest_title=q_title)
                                    gui.after(0, gui.refresh_quest_progress)
                                elif name == "complete_micro_quest":
                                    q_title = args.get("quest_title", "")
                                    gui.log_message("ONyuul Quest", f"마이크로 퀘스트 달성 성공! -> [{q_title or '최근 퀘스트'}]")
                                    result = await asyncio.to_thread(complete_micro_quest, quest_title=q_title)
                                    gui.after(0, gui.refresh_quest_progress)
                                elif name == "get_pending_quests":
                                    result = await asyncio.to_thread(get_pending_quests)
                                elif name == "get_current_time":
                                    result = await asyncio.to_thread(get_current_time)
                                elif name == "get_system_status":
                                    result = await asyncio.to_thread(get_system_status)
                                elif name == "get_current_weather":
                                    result = await asyncio.to_thread(get_current_weather, location=args.get("location", "안성시"))
                                elif name == "get_daily_briefing":
                                    result = await asyncio.to_thread(get_daily_briefing, location=args.get("location", "안성시"))
                                elif name == "play_youtube_music":
                                    result = await asyncio.to_thread(play_youtube_music, query=args.get("query", "조용한 음악 플레이리스트"))
                                elif name == "open_program":
                                    result = await asyncio.to_thread(open_program, target=args.get("target", ""), confirmed=args.get("confirmed", False), state=state)
                                elif name == "find_and_open_file":
                                    result = await asyncio.to_thread(find_and_open_file, query=args.get("query", ""), location=args.get("location", ""), confirmed=args.get("confirmed", False))
                            except Exception as e:
                                print(f"⚠️ [Tool Dispatch Error] {name}: {e}")
                                result = f"'{name}' 도구 처리 중 오류가 발생했습니다. 다시 시도해주세요."

                        await session.send_tool_response(
                            function_responses=[types.FunctionResponse(name=name, id=call_id, response={"result": result})]
                        )

                server_content = response.server_content
                if not server_content:
                    continue

                transcription = server_content.input_transcription
                if transcription and transcription.text:
                    chunk_text = transcription.text
                    state.user_speech_buffer += chunk_text
                    full_user_speech = state.user_speech_buffer.strip()

                    # 주의: 여기서 gui.log_message를 매 청크마다 호출하면 안 된다.
                    # STT 델타 청크는 초당 여러 번 도착하는데, log_message는 호출될
                    # 때마다 새 채팅 줄을 추가하므로 "저" "는 오늘" "좀 힘들" "었어요"처럼
                    # 문장이 조각조각 흩어져 보이는 미관상 버그의 원인이었다. 완성된
                    # 문장은 turn_complete 시점에 한 번만 기록한다 (아래 turn_complete
                    # 처리부 참고).

                    # 실시간 반응성은 채팅 로그(여러 줄 쌓임) 대신 상태 배지(한 줄만
                    # 계속 갱신됨)로 보여준다 — 이러면 지저분해지지 않으면서도 "지금
                    # 듣고 있다"는 피드백은 유지된다.
                    preview = full_user_speech[-40:] if len(full_user_speech) > 40 else full_user_speech
                    gui.update_status(f"🎙️ 듣는 중: {preview}", COLOR_PRIMARY)

                    if state.is_standby:
                        if contains_wake_word(full_user_speech):
                            gui.set_standby_mode(False)
                            state.user_speech_buffer = ""
                        else:
                            continue

                    if any(cmd in full_user_speech for cmd in ["잠깐 대기", "잠시 대기", "대기해", "조용히 해"]):
                        gui.set_standby_mode(True)
                        model_audio_buffer.clear()
                        state.user_speech_buffer = ""
                        continue

                    if (
                        not exit_intent_shown_this_turn
                        and not state.crisis_active
                        and contains_exit_intent(full_user_speech)
                    ):
                        # 즉시 종료하지 않고, 항상 기존의 "정말 종료하시겠어요?" 확인창을
                        # 띄운다 (X 버튼과 완전히 동일한 흐름 — 최소화/종료/취소 선택 가능).
                        exit_intent_shown_this_turn = True
                        gui.after(0, gui._confirm_close_dialog)

                    if crisis_task is None or crisis_task.done():
                        # check_and_flag는 동기 함수라 여기서 즉시 state.crisis_active가
                        # 세팅된다. create_task(coroutine)로 예약만 해두면 실제 실행이
                        # 다음 await 지점까지 미뤄져서, 같은 turn_complete 처리 안의
                        # 브레인덤프 게이트가 그 사이 먼저 통과해버리는 레이스가 있었다.
                        if interceptor.check_and_flag(state, full_user_speech):
                            crisis_task = asyncio.create_task(
                                interceptor.run_popup_and_cooldown(state)
                            )

                    # 🛡️ 2차 LLM 필터는 turn_complete에서 문장당 정확히 1번만 호출한다.
                    # (예전엔 부분 텍스트가 갱신될 때마다 조기 시작해서 지연을 줄이려
                    # 했는데, 문장 하나에 STT 청크가 여러 번 오면 그만큼 LLM 호출도
                    # 여러 번 나가서 API 쿼터를 예상보다 훨씬 빨리 소모하는 문제가 있었다.
                    # 아래 turn_complete 처리부에서 한 번만 호출한다.)

                if server_content.interrupted:
                    state.is_speaking = False
                    state.user_speech_buffer = ""
                    model_audio_buffer.clear()
                    gui.update_status("⚡ 답변 중단됨", "#E67E22")

                if server_content.model_turn and not state.block_playback and not state.is_standby:
                    state.is_speaking = True
                    gui.update_status("🟣 온율 답변 중...", "#9B59B6")
                    for part in server_content.model_turn.parts:
                        if part.inline_data:
                            audio_chunk = apply_volume(part.inline_data.data, gui.tts_volume)
                            await asyncio.to_thread(output_stream.write, audio_chunk)
                            model_audio_buffer.extend(part.inline_data.data)  # 자막용 원본은 볼륨 조절 전 그대로 보관

                if server_content.turn_complete:
                    if state.user_speech_buffer.strip():
                        # 완성된 문장은 여기서 턴당 딱 한 번만 기록한다. 위기 개입/대기
                        # 모드 여부와 무관하게 항상 남겨서, 나중에 "그때 무슨 말을 했었는지"
                        # 대화 로그로 확인할 수 있게 한다.
                        #
                        # 주의: 이 로그는 반드시 아래 온율 자막 로그보다 먼저 나와야 한다.
                        # 온율 자막은 Whisper 재변환을 거치느라 시간이 좀 걸리는데, 예전엔
                        # 이 순서가 뒤바뀌어 있어서 "온율이 먼저 대답하고 나중에 Master가
                        # 질문한" 것처럼 채팅 로그가 거꾸로 보이는 문제가 있었다.
                        gui.log_message("Master (Voice)", state.user_speech_buffer.strip())

                    if model_audio_buffer and not state.is_standby:
                        audio_bytes = bytes(model_audio_buffer)
                        model_audio_buffer.clear()
                        subtitles = await loop.run_in_executor(None, transcribe_pcm24k, audio_bytes)
                        if subtitles:
                            gui.log_message("ONyuul", subtitles)
                    else:
                        model_audio_buffer.clear()

                    if state.user_speech_buffer and not state.crisis_active and not state.is_standby:
                        full_speech = state.user_speech_buffer.strip()
                        # 🛡️ 2차 LLM 필터: 완성된 문장으로 문장당 정확히 1번 호출한다.
                        # (llm_task 변수는 여전히 dedupe 용도로 남겨둔다 — 이론상
                        # 한 응답 메시지 안에 여러 turn_complete가 겹칠 가능성에 대비.)
                        if llm_task is None or llm_task.done():
                            llm_task = asyncio.create_task(
                                run_llm_safety_check(interceptor, state, full_speech, gui)
                            )

                        # 🧠 브레인덤프: 이번 턴에 Gemini가 스스로 도구를 호출하지 않았다면
                        # (= 자기 판단으로 이미 처리한 게 아니라면) 로컬 규칙으로 1차 분류해서
                        # 자동 저장을 시도한다. 위 crisis_task 트리거를 거쳤으므로(=block_playback/
                        # crisis_active 게이트를 통과한 뒤) 도달하는 지점이라 안전 원칙을 그대로 지킨다.
                        if not tool_called_this_turn:
                            asyncio.create_task(handle_brain_dump(full_speech, gui, state))
                    elif state.is_standby and state.user_speech_buffer.strip():
                        # 대기 모드 중 이번 턴 내내 웨이크워드가 한 번도 인식되지 않은
                        # 경우(=중간 처리부에서 계속 continue만 됨), 그 발화를 기록해
                        # 웨이크워드 설정 창에서 사용자가 직접 검토/추가할 수 있게 한다.
                        missed_text = state.user_speech_buffer.strip()
                        gui.after(0, lambda t=missed_text: gui.record_wake_word_miss(t))

                    state.is_speaking = False
                    state.user_speech_buffer = ""
                    tool_called_this_turn = False
                    exit_intent_shown_this_turn = False
                    if not state.is_standby:
                        gui.update_status("🟢 듣는 중...", COLOR_SUCCESS)
                    interceptor.on_turn_complete(state)
                    await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        pass
    finally:
        state.is_speaking = False
        output_stream.stop_stream()
        output_stream.close()

def start_async_pipeline(gui: ONyuulGUI):
    global app_loop
    app_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(app_loop)

    # 재연결 신호는 asyncio.Event로 주고받는다. 이 Event는 반드시 app_loop 위에서
    # 생성/조작돼야 하므로, GUI(메인 스레드)가 재연결을 요청할 땐 이 객체를 직접
    # 건드리지 않고 call_soon_threadsafe로 넘겨야 한다 (trigger_reconnect 참고).
    gui.reconnect_event = asyncio.Event()
    gui.app_loop_ref = app_loop

    async def run_session():
        """세션 1회 연결 + 유지. 정상 종료/예외 모두 호출부(connection_loop)가 처리한다.

        api_key, gui.selected_voice, gui.night_mode_override를 매번 새로 읽으므로,
        재연결할 때마다 그 시점의 최신 설정이 그대로 반영된다 (별도 캐시 없음)."""
        # 재연결 시 SessionState(gui.app_state)를 새로 만들지 않고 재사용하기 때문에,
        # 이전 세션이 비정상 종료된 타이밍에 따라 crisis_active/is_speaking 같은
        # 휘발성 플래그가 True로 남아있을 수 있다. 남아있으면 새 세션이 시작부터
        # "위기 개입 중"으로 오인돼 도구 호출/브레인덤프가 영구히 막히는 등의 문제가
        # 생길 수 있으므로, 매 연결 시작 시 명시적으로 깨끗한 상태로 되돌린다.
        state = gui.app_state
        state.crisis_active = False
        state.block_playback = False
        state.is_speaking = False
        state.user_speech_buffer = ""
        state.last_brain_dump_quest = None
        if state.is_standby:
            gui.set_standby_mode(False)

        api_key = config_manager.get_api_key()
        if not api_key:
            gui.log_message("Error", "Gemini API 키가 설정되어 있지 않습니다. 우측 상단 ⚙ 버튼으로 설정해주세요.")
            return

        client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
        p = pyaudio.PyAudio()
        interceptor = CrisisInterceptor(
            on_start=lambda: gui.set_crisis_mode(True),
            on_end=lambda: gui.set_crisis_mode(False),
            api_key=api_key,
        )

        now_hour = datetime.datetime.now().hour
        is_night = (gui.night_mode_override == "ON") or (gui.night_mode_override == "AUTO" and (now_hour >= 22 or now_hour < 6))

        retrieved_memories = memory_db.search_relevant_memories("고민 불면증 불안 스트레스 시험 건강", n_results=5)
        # search_relevant_memories는 dict 리스트를 반환한다({'id':.., 'content':.., ...}).
        # 문자열처럼 그대로 join하면 딕셔너리 repr이 통째로 시스템 프롬프트에 박혀서
        # Gemini에게 매 세션 전송된다 — content 필드만 뽑아 써야 한다.
        memory_lines = [
            (m.get("content", "") if isinstance(m, dict) else str(m))
            for m in retrieved_memories
        ]
        memory_context = "\n".join([f"- {line}" for line in memory_lines if line]) if memory_lines else "- 아직 저장된 기억이 없습니다."

        save_func_decl = types.FunctionDeclaration(name="save_user_memory", description="Master 기억 저장", parameters=types.Schema(type="OBJECT", properties={"information": types.Schema(type="STRING"), "category": types.Schema(type="STRING")}, required=["information"]))
        log_mood_decl = types.FunctionDeclaration(name="log_mood_and_sleep", description="기분 기록", parameters=types.Schema(type="OBJECT", properties={"mood_score": types.Schema(type="STRING"), "sleep_hours": types.Schema(type="STRING"), "emotion_keywords": types.Schema(type="STRING"), "notes": types.Schema(type="STRING")}))
        get_mood_hist_decl = types.FunctionDeclaration(name="get_mood_history", description="기록 조회", parameters=types.Schema(type="OBJECT", properties={"days": types.Schema(type="INTEGER")}))
        add_thought_record_decl = types.FunctionDeclaration(
            name="add_thought_record",
            description=(
                "CBT 인지 재구성 기록을 저장합니다. Master와 함께 (1) 상황 공감 (2) 자동적 사고 및 "
                "인지 오류 탐지 (3) 소크라테스식 질문으로 대안적 사고 도출까지 대화로 충분히 진행한 "
                "'뒤에만' 호출하세요. 대화 초반에 섣불리 호출하지 마세요."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "situation": types.Schema(type="STRING", description="어떤 상황이었는지"),
                    "automatic_thought": types.Schema(type="STRING", description="그 상황에서 즉각 떠오른 생각"),
                    "cognitive_distortion": types.Schema(type="STRING", description="해당되는 인지 오류(흑백논리, 재앙화, 과잉일반화 등, 없으면 생략)"),
                    "alternative_thought": types.Schema(type="STRING", description="대화를 통해 함께 찾은 더 균형 잡힌 대안적 사고"),
                    "emotion_before": types.Schema(type="INTEGER", description="대안적 사고를 찾기 전 감정 강도 (0~100)"),
                    "emotion_after": types.Schema(type="INTEGER", description="대안적 사고를 찾은 뒤 감정 강도 (0~100)"),
                },
                required=["situation", "automatic_thought", "alternative_thought"],
            ),
        )
        start_grounding_decl = types.FunctionDeclaration(name="start_grounding_guide", description="호흡 가이드", parameters=types.Schema(type="OBJECT", properties={"technique": types.Schema(type="STRING")}))
        create_reminder_decl = types.FunctionDeclaration(
            name="create_reminder",
            description=(
                "복약 알림이나 일반 일정 알림을 등록합니다. 오늘 날짜/현재 시각을 알고 있어야 "
                "정확한 remind_at을 계산할 수 있으니, 필요하면 먼저 get_current_time을 호출해 "
                "기준 시각을 확인한 뒤 계산하세요."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "title": types.Schema(type="STRING", description="무엇을 알려줄지 (예: '혈압약 복용', '병원 예약')"),
                    "remind_at": types.Schema(type="STRING", description="'YYYY-MM-DD HH:MM' 형식 (예: '2026-08-14 20:00')"),
                    "kind": types.Schema(type="STRING", description="'medication'(복약) 또는 'schedule'(일반 일정)"),
                    "repeat_rule": types.Schema(type="STRING", description="반복 없으면 생략, 'daily' 또는 'weekly'"),
                },
                required=["title", "remind_at"],
            ),
        )
        get_reminders_decl = types.FunctionDeclaration(
            name="get_upcoming_reminders", description="앞으로 등록된 알림 목록 조회",
            parameters=types.Schema(type="OBJECT", properties={"limit": types.Schema(type="INTEGER")}),
        )
        create_task_decl = types.FunctionDeclaration(
            name="create_task",
            description=(
                "마감일이 있는 실제 할 일(과제 제출, 서류 처리 등)을 등록합니다. "
                "행동 활성화 목적의 부담 없는 작은 미션은 create_micro_quest를 대신 쓰세요 — "
                "둘을 혼동하지 마세요."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "title": types.Schema(type="STRING", description="할 일 내용"),
                    "due_date": types.Schema(type="STRING", description="'YYYY-MM-DD' 형식, 마감이 없으면 생략"),
                    "priority": types.Schema(type="STRING", description="'low' | 'medium' | 'high', 기본 medium"),
                },
                required=["title"],
            ),
        )
        complete_task_decl = types.FunctionDeclaration(
            name="complete_task", description="할 일을 완료 처리",
            parameters=types.Schema(type="OBJECT", properties={"task_title": types.Schema(type="STRING")}),
        )
        get_tasks_decl = types.FunctionDeclaration(
            name="get_pending_tasks", description="마감 임박 순으로 정렬된 미완료 할 일 목록 조회",
            parameters=types.Schema(type="OBJECT", properties={"limit": types.Schema(type="INTEGER")}),
        )
        log_grounding_decl = types.FunctionDeclaration(name="log_grounding_session", description="가이드 저장", parameters=types.Schema(type="OBJECT", properties={"technique_type": types.Schema(type="STRING"), "feedback": types.Schema(type="STRING")}))
        save_positive_anchor_decl = types.FunctionDeclaration(name="save_positive_anchor", description="긍정 앵커 저장", parameters=types.Schema(type="OBJECT", properties={"content": types.Schema(type="STRING"), "emotion_tag": types.Schema(type="STRING")}, required=["content"]))
        recall_positive_anchors_decl = types.FunctionDeclaration(name="recall_positive_anchors", description="긍정 앵커 불러오기", parameters=types.Schema(type="OBJECT", properties={"limit": types.Schema(type="INTEGER")}))
        create_quest_decl = types.FunctionDeclaration(name="create_micro_quest", description="초소형 미션 제안", parameters=types.Schema(type="OBJECT", properties={"quest_title": types.Schema(type="STRING")}, required=["quest_title"]))
        complete_quest_decl = types.FunctionDeclaration(name="complete_micro_quest", description="미션 완료", parameters=types.Schema(type="OBJECT", properties={"quest_title": types.Schema(type="STRING")}))
        get_quests_decl = types.FunctionDeclaration(name="get_pending_quests", description="미션 목록 조회", parameters=types.Schema(type="OBJECT", properties={}))
        time_func_decl = types.FunctionDeclaration(name="get_current_time", description="현재 시각 조회", parameters=types.Schema(type="OBJECT", properties={}))
        sys_status_decl = types.FunctionDeclaration(
            name="get_system_status",
            description="현재 PC의 CPU/RAM 사용률을 조회합니다 (예: 'PC가 버벅여', '지금 얼마나 무거워?').",
            parameters=types.Schema(type="OBJECT", properties={}),
        )
        weather_func_decl = types.FunctionDeclaration(name="get_current_weather", description="날씨 조회", parameters=types.Schema(type="OBJECT", properties={"location": types.Schema(type="STRING")}))
        daily_briefing_decl = types.FunctionDeclaration(name="get_daily_briefing", description="아침 인사, 날씨, 오늘의 대기 퀘스트, 긍정 기억을 묶은 데일리 브리핑 생성", parameters=types.Schema(type="OBJECT", properties={"location": types.Schema(type="STRING")}))
        play_music_decl = types.FunctionDeclaration(name="play_youtube_music", description="유튜브 음악 검색 및 브라우저 열기", parameters=types.Schema(type="OBJECT", properties={"query": types.Schema(type="STRING")}, required=["query"]))
        open_prog_decl = types.FunctionDeclaration(name="open_program", description="프로그램 실행", parameters=types.Schema(type="OBJECT", properties={"target": types.Schema(type="STRING"), "confirmed": types.Schema(type="BOOLEAN")}, required=["target"]))
        find_file_decl = types.FunctionDeclaration(
            name="find_and_open_file",
            description=(
                "파일 또는 폴더를 검색해서 엽니다 (예: '어제 저장한 보고서 파일 찾아줘', "
                "'바탕화면에 있는 발표자료 열어줘', 'C드라이브 프로젝트 폴더에서 이력서 찾아줘', "
                "'다운로드에 있는 게임 폴더 열어줘'). "
                "Master가 위치를 언급하면 반드시 location에 그 표현을 그대로 전달하세요 — "
                "생략하면 기본 위치(바탕화면/문서/다운로드)만 검색합니다."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="찾을 파일/폴더명(전체 또는 일부). '파일'/'폴더'/'문서' 같은 "
                                     "군더더기 단어는 빼고 핵심 이름만 넘기세요 (예: 'OO 파일 찾아줘'라고 "
                                     "말했어도 query에는 'OO'만).",
                    ),
                    "location": types.Schema(
                        type="STRING",
                        description="Master가 말한 위치 (예: '바탕화면', '다운로드', 'C드라이브', 'C:\\프로젝트'). 위치 언급이 없었으면 생략.",
                    ),
                    "confirmed": types.Schema(type="BOOLEAN"),
                },
                required=["query"],
            ),
        )

        base_instruction = (
            "당신은 Master의 곁을 지키며 대화를 나누는 다정하고 유능한 AI 비서 '온율(ONyuul)'입니다. "
            "Master를 향해 친절하고 격식 있게 대하며, 항상 'Master'라고 부르세요.\n\n"
            "[Master 메모리 Context]\n"
            f"{memory_context}\n\n"
            "[CBT 마음 돌봄 및 동작 지침]\n"
            "1. 따뜻하고 공감해 주는 다정한 동반자 역할을 유지하세요.\n"
            "2. Master가 기분 점수(1~10점)나 수면 시간, 오늘의 감정을 이야기하면 즉시 `log_mood_and_sleep` 도구를 호출하여 저장하세요.\n"
            "3. `start_grounding_guide` 호출 시 숫자를 천천히 카운트다운하여 호흡을 직접 리드하세요.\n"
            "4. Master가 음악이나 노래를 틀어달라고 하면 반드시 `play_youtube_music` 도구를 호출하세요.\n"
            "5. Master가 프로그램/앱을 열어달라고 하면 `open_program`을 호출하세요. 만약 결과로 "
            "'REQUIRES_CONFIRMATION'이 돌아오면, 그 프로그램을 정말 실행할지 Master에게 다시 "
            "여쭤보고, 명확히 승낙을 받은 뒤에만 confirmed=true로 다시 호출하세요.\n"
            "6. Master가 '굿모닝', '브리핑', '오늘 하루 어때' 등으로 하루 요약을 요청하면 "
            "`get_daily_briefing` 도구를 호출해 결과를 자연스럽게 전해주세요.\n"
            "7. Master가 특정 상황 때문에 힘든 생각(예: '나는 실패자야', '다들 날 싫어해')을 "
            "이야기하면, 곧바로 반박하거나 도구부터 호출하지 마세요. 먼저 그 감정을 있는 그대로 "
            "충분히 공감하고, 그 다음 소크라테스식 질문으로(예: '그렇게 생각하시게 된 계기가 "
            "있을까요?', '다르게 볼 수 있는 여지는 없을까요?') 함께 그 생각을 살펴본 뒤에만, "
            "대화를 통해 찾은 대안적 사고를 `add_thought_record`로 저장하세요. 이 순서(공감 → "
            "인지 오류 탐지 → 소크라테스식 질문 → 대안적 사고)를 건너뛰고 성급하게 저장하지 마세요.\n"
            "8. Master가 '~시에 ~하는 거 알려줘', '약 먹는 시간 알려줘' 처럼 특정 시각에 뭔가를 "
            "상기시켜 달라고 하면 `create_reminder`를 호출하세요. 상대적 시간 표현('내일', '30분 "
            "뒤')이 나오면 먼저 `get_current_time`으로 기준 시각을 확인한 뒤 절대 시각(YYYY-MM-DD "
            "HH:MM)으로 계산해서 넘기세요. 복약 관련이면 kind를 'medication'으로, 그 외 일정은 "
            "'schedule'로 설정하세요.\n"
            "9. Master가 '~해야 해', '~까지 제출해야 돼' 처럼 **마감이 있는 실제 할 일**을 "
            "이야기하면 `create_task`를 쓰세요. 이건 부담 없는 작은 도전을 제안하는 "
            "`create_micro_quest`와는 다릅니다 — 이미 Master가 해야 한다고 스스로 말한 일을 "
            "그대로 기록하는 용도이니, `create_micro_quest`처럼 먼저 미션을 제안하지 말고 "
            "Master가 말한 내용을 있는 그대로 등록하세요.\n"
            "10. CBT/멘탈케어와 무관한 일반적인 질문(단어 뜻, 계산, 상식 등)도 "
            "자연스럽게 답하세요. 굳이 CBT 관련 화제로만 대화를 국한할 필요는 없습니다."
            + (
                " 최신 정보나 확실하지 않은 사실은 Google Search 도구로 확인한 뒤 답하세요.\n"
                if ENABLE_GOOGLE_SEARCH else
                " 다만 실시간 웹 검색 도구는 지금 비활성화되어 있으니, 최신 뉴스나 "
                "확인이 필요한 사실을 물으면 아는 범위에서 답하되 확실하지 않다고 솔직히 밝히세요.\n"
            ) +
            "11. Master가 '그 파일 어디 있지', '~찾아서 열어줘', 'OO 폴더 열어줘' 처럼 PC에 있는 "
            "파일이나 폴더를 찾아달라고 하면 `find_and_open_file`을 호출하세요. query에는 핵심 "
            "이름만 넘기고(\"OO 파일 찾아줘\"에서 \"파일\"은 빼고 \"OO\"만), Master가 위치(바탕화면, "
            "다운로드, 특정 드라이브나 폴더명 등)를 언급하면 location 인자에 그대로 전달하세요. "
            "결과로 'REQUIRES_CONFIRMATION'이 오면 찾은 목록을 Master에게 읽어주고, 어떤 걸 열지 "
            "확인받은 뒤에만 confirmed=true로 다시 호출하세요.\n"
            "12. Master가 'PC가 버벅여', '지금 컴퓨터 상태 어때' 처럼 시스템 성능을 물으면 "
            "`get_system_status`를 호출해 CPU/RAM 사용률을 알려주세요.\n"
        )
        if is_night:
            base_instruction += "\n[🌙 야간 모드]: 대답은 1~2문장 이내로 매우 간결하고 평온하게 하세요."

        config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": gui.selected_voice
                    }
                }
            },
            "input_audio_transcription": {},
            "tools": [
                types.Tool(function_declarations=[
                    save_func_decl, log_mood_decl, get_mood_hist_decl, add_thought_record_decl,
                    start_grounding_decl, create_reminder_decl, get_reminders_decl,
                    create_task_decl, complete_task_decl, get_tasks_decl, log_grounding_decl,
                    save_positive_anchor_decl, recall_positive_anchors_decl,
                    create_quest_decl, complete_quest_decl, get_quests_decl,
                    time_func_decl, sys_status_decl, weather_func_decl, daily_briefing_decl, play_music_decl,
                    open_prog_decl, find_file_decl,
                ]),
            ] + (
                # Google Search 그라운딩: 세션이 정상 연결된 직후 "1008 invalid
                # authentication credentials, expected OAuth 2 access token"으로
                # 끊기는 문제가 이 도구를 켠 뒤부터 발생해서, 원인이 확정될 때까지
                # 임시로 비활성화해둔다. 단순 API 키가 아니라 OAuth 기반 Cloud 프로젝트
                # 인증이 필요한 계정/등급일 가능성이 있다. 원인이 확인되면
                # ENABLE_GOOGLE_SEARCH를 True로 되돌릴 것.
                [types.Tool(google_search=types.GoogleSearch())] if ENABLE_GOOGLE_SEARCH else []
            ),
            "system_instruction": base_instruction,
        }

        gui.after(0, gui.hide_reconnect_banner)
        gui.update_status("🟢 듣는 중...", COLOR_SUCCESS)
        gui.log_message("System", f"온율 음성 엔진 연결 완료 (선택된 목소리: {gui.selected_voice})")

        try:
            async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
                gui.async_session = session
                await asyncio.gather(
                    send_mic_audio(session, p, gui.app_state, gui),
                    receive_speaker_audio(session, p, gui.app_state, interceptor, gui),
                )
        finally:
            # p.terminate()를 안 하면, 재연결할 때마다 새 PyAudio() 인스턴스가 계속
            # 쌓여 리소스가 샌다 (예전엔 앱 생애주기 동안 한 번만 연결해서 문제되지
            # 않았지만, 재연결을 지원하는 지금은 반드시 정리해야 한다).
            p.terminate()
            gui.async_session = None

    async def connection_loop():
        """
        세션을 계속 유지하다가, (1) 연결이 끊기면 재연결 배너를 띄우고 사용자가
        재연결 버튼을 누를 때까지 기다리거나, (2) 세션이 건강하게 유지되는 중에도
        설정 변경(목소리/API 키) 등으로 reconnect_event가 세팅되면 현재 세션을
        정리하고 즉시 새 설정으로 재연결한다.
        """
        while True:
            session_task = asyncio.ensure_future(run_session())
            reconnect_wait_task = asyncio.ensure_future(gui.reconnect_event.wait())

            done, _pending = await asyncio.wait(
                {session_task, reconnect_wait_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if reconnect_wait_task in done and session_task not in done:
                # 세션이 건강하게 살아있는 중에 재연결 요청이 들어온 경우(설정 변경 등):
                # 기존 세션을 취소하고 새로 연결한다.
                gui.reconnect_event.clear()
                session_task.cancel()
                try:
                    await session_task
                except (asyncio.CancelledError, Exception):
                    pass

                # 로컬에서 await session_task로 정리를 기다리긴 하지만, 서버 쪽이
                # 이전 Live 세션을 완전히 해제하는 데 걸리는 시간까지는 보장이 안 된다.
                # 그 틈에 곧바로 새 연결을 시도하면 "이전 세션이 아직 안 끝났다"는
                # 409 Conflict로 거절당할 수 있어, 짧은 유예를 둔다.
                await asyncio.sleep(1.0)
                continue

            # 여기 도달했다는 건 session_task가 (정상/비정상으로) 끝났다는 뜻이다.
            reconnect_wait_task.cancel()
            try:
                exc = session_task.exception() if session_task.done() else None
            except asyncio.CancelledError:
                exc = None

            if exc:
                print(f"⚠️ [Connection Loop] 세션이 예기치 않게 종료됨: {exc}")
                gui.show_reconnect_banner(friendly_connection_error(exc))
                # 사용자가 재연결 버튼을 누르거나(=reconnect_event.set) 설정을
                # 바꿔 저장할 때까지 여기서 대기한다.
                await gui.reconnect_event.wait()
                gui.reconnect_event.clear()
                await asyncio.sleep(1.0)  # 서버 측 이전 세션 정리 유예 (409 방지)
                continue
            else:
                # run_session이 예외 없이 정상적으로 끝난 경우(API 키 미설정 등으로
                # 조기 반환된 경우 포함) — 재연결 배너를 띄우고 동일하게 대기한다.
                gui.show_reconnect_banner("설정을 확인하고 재연결해주세요.")
                await gui.reconnect_event.wait()
                gui.reconnect_event.clear()
                await asyncio.sleep(1.0)
                continue

    app_loop.run_until_complete(connection_loop())


if __name__ == "__main__":
    app = ONyuulGUI()
    refresh_wake_word_cache()  # 사용자가 추가해둔 웨이크워드 변형을 런타임 캐시로 미리 로드

    if whisper_load_error:
        app.after(500, lambda: app.log_message(
            "System",
            f"⚠️ 자막 엔진(Whisper) 로딩에 실패했습니다: {whisper_load_error}\n"
            "온율이의 음성 응답 자막 표시만 비활성화되고, 나머지 기능은 정상 동작합니다. "
            "인터넷 연결을 확인한 뒤 앱을 재시작하면 다시 시도됩니다."
        ))

    def _launch_pipeline():
        async_thread = threading.Thread(target=start_async_pipeline, args=(app,), daemon=True)
        async_thread.start()

    def _maybe_show_onboarding():
        # 최초 성공 실행(=키가 있어서 파이프라인이 뜬 순간)에만 한 번 보여준다.
        # API 키 다이얼로그와 겹치지 않도록 살짝 늦춰서 띄운다.
        if not config_manager.has_seen_onboarding():
            app.after(800, app.open_onboarding_dialog)

    if config_manager.get_api_key():
        _launch_pipeline()
        _maybe_show_onboarding()
    else:
        # 저장된 키도, 환경변수(.env)도 없는 최초 실행: 설정 창을 먼저 띄우고,
        # 저장이 완료된 뒤에야 파이프라인을 시작한다 (키 없이 조용히 지나가지 않게).
        def _after_key_saved():
            _launch_pipeline()
            _maybe_show_onboarding()

        app.after(300, lambda: app.open_api_key_dialog(on_saved=_after_key_saved, first_run=True))

    app.mainloop()