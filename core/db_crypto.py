"""
core.db_crypto
===============
로컬 SQLite DB를 "앱이 꺼져 있는 동안"에는 암호화된 상태로 보관하기 위한 모듈.

## 왜 SQLCipher가 아닌가
SQLite 엔진 자체를 암호화 지원 버전(SQLCipher)으로 통째로 바꾸는 방법도 있지만,
그건 네이티브 바이너리 의존성이 생겨서 PyInstaller 빌드가 훨씬 불안정해질
위험이 크다. 대신 이 모듈은 "실행 중엔 지금까지 써온 평범한 평문 sqlite3 파일을
그대로 쓰고, 앱을 시작할 때 암호화된 백업을 복호화해서 이 평문 파일을 만들고,
앱을 깨끗하게 종료할 때 다시 암호화해서 평문 파일을 지운다"는 방식을 쓴다.
즉 "실행 중" 보호가 아니라 "휴지 상태(at rest)" 보호다.

## 키 관리
암호화 키(Fernet 대칭키)는 Windows DPAPI(CryptProtectData)로 보호해서 디스크에
저장한다. 이러면:
- 사용자가 별도 비밀번호를 만들거나 기억할 필요가 없다. 심리 케어 앱에서
  "비밀번호를 잊어버려서 몇 달치 기록을 영영 못 연다"는 최악의 시나리오를
  피하려고 의도적으로 이렇게 설계했다.
- DPAPI 보호 데이터는 "현재 로그인한 Windows 사용자 계정 + 이 PC"에 묶여있어서,
  키 파일과 암호화된 DB 파일을 통째로 복사해 다른 PC나 다른 계정으로 가져가도
  복호화가 안 된다.

## 비정상 종료(크래시) 대비
앱이 비정상 종료되면(정전, 강제 종료 등) 평문 파일이 그대로 디스크에 남는다.
다음 실행 시, 평문 파일이 이미 존재하면 암호화된 백업이 더 오래된 것일 수
있으므로(그 사이 기록된 데이터가 암호화 백업엔 없을 수 있음) **절대 덮어쓰지
않는다**. 평문을 그대로 두고, 이번 세션이 끝날 때 정상적으로 다시 암호화한다.

## 한계
pywin32(win32crypt)나 cryptography 패키지가 없는 환경에서는 암호화 기능
자체가 조용히 비활성화되고, 기존처럼 평문으로 동작한다. 이 프로젝트는 Windows
전용이라 실질적으로 문제되지 않지만, 개발 환경(예: 이 코드가 검증되는 리눅스
샌드박스)에서도 앱이 죽지 않도록 하기 위한 안전장치다.
"""
import os
from pathlib import Path

try:
    import win32crypt
    DPAPI_AVAILABLE = True
except ImportError:
    DPAPI_AVAILABLE = False

try:
    from cryptography.fernet import Fernet, InvalidToken
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False

ENCRYPTION_AVAILABLE = DPAPI_AVAILABLE and FERNET_AVAILABLE

_KEY_FILENAME = "db.key"


def _key_path(config_dir: Path) -> Path:
    return Path(config_dir) / _KEY_FILENAME


def _load_or_create_key(config_dir: Path) -> bytes:
    """DPAPI로 보호된 Fernet 키를 불러오거나, 없으면 새로 만들어 저장한다."""
    key_path = _key_path(config_dir)
    if key_path.exists():
        protected = key_path.read_bytes()
        # CryptUnprotectData는 (description, data) 튜플을 반환한다.
        _, raw_key = win32crypt.CryptUnprotectData(protected, None, None, None, 0)
        return raw_key

    raw_key = Fernet.generate_key()
    protected = win32crypt.CryptProtectData(raw_key, "ONyuul DB Encryption Key", None, None, None, 0)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(protected)
    return raw_key


def decrypt_db_on_startup(encrypted_path: Path, plain_path: Path, config_dir: Path) -> bool:
    """
    앱 시작 시 호출한다.

    - encrypted_path(.enc)가 없으면(최초 실행 등) 아무것도 하지 않고 False 반환
      → core/db.py가 평문 경로에 새 DB를 만들거나, 이미 있는 평문을 그대로 씀.
    - plain_path가 이미 존재하면(지난 세션이 비정상 종료된 경우) 절대 덮어쓰지
      않는다. 그 평문이 암호화 백업보다 최신일 수 있어서, 덮어쓰면 데이터를
      잃을 위험이 있다. 이 경우 그대로 두고 False를 반환한다 — 어차피 이번
      세션이 끝날 때 다시 암호화되니 문제없다.
    - 정상적으로 복호화에 성공하면 True를 반환한다.
    """
    if not ENCRYPTION_AVAILABLE:
        return False
    if not encrypted_path.exists():
        return False
    if plain_path.exists():
        print("ℹ️ [DB 암호화] 이전 세션의 평문 파일이 남아있어 그대로 사용합니다 (비정상 종료 후 복구).")
        return False

    try:
        key = _load_or_create_key(config_dir)
        fernet = Fernet(key)
        encrypted_data = encrypted_path.read_bytes()
        decrypted_data = fernet.decrypt(encrypted_data)
        plain_path.parent.mkdir(parents=True, exist_ok=True)
        plain_path.write_bytes(decrypted_data)
        return True
    except InvalidToken:
        print("⚠️ [DB 암호화] 복호화 실패(키 불일치). 암호화된 백업을 열 수 없습니다.")
        return False
    except Exception as e:
        print(f"⚠️ [DB 암호화] 복호화 중 오류: {e}")
        return False


def encrypt_db_on_shutdown(plain_path: Path, encrypted_path: Path, config_dir: Path) -> bool:
    """
    앱을 깨끗하게 종료할 때 호출한다. plain_path(평문 DB)를 암호화해서
    encrypted_path(.enc)에 쓰고, 평문 파일과 WAL 사이드카(-wal, -shm)를 지운다.

    암호화 직전에 WAL 체크포인트를 실행해서, 아직 메인 DB 파일에 반영 안 된
    최신 기록이 WAL 파일에만 남아있다가 그대로 삭제되는 일이 없게 한다.
    """
    if not ENCRYPTION_AVAILABLE:
        return False
    if not plain_path.exists():
        return False

    try:
        # WAL 모드에서 아직 메인 파일에 반영 안 된 내용이 있을 수 있으므로,
        # 암호화 대상으로 파일을 읽기 전에 반드시 체크포인트로 합쳐준다.
        import sqlite3
        conn = sqlite3.connect(str(plain_path))
        try:
            conn.execute("PRAGMA wal_checkpoint(FULL);")
            conn.commit()
        finally:
            conn.close()

        key = _load_or_create_key(config_dir)
        fernet = Fernet(key)
        plain_data = plain_path.read_bytes()
        encrypted_data = fernet.encrypt(plain_data)
        encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted_path.write_bytes(encrypted_data)

        # 평문 파일과 WAL 사이드카를 정리한다. 그대로 두면 "쉬고 있는 동안
        # 암호화돼 있어야 한다"는 목적 자체가 무의미해진다.
        for p in (plain_path, Path(str(plain_path) + "-wal"), Path(str(plain_path) + "-shm")):
            if p.exists():
                os.remove(p)
        return True
    except Exception as e:
        print(f"⚠️ [DB 암호화] 암호화 실패, 평문 파일이 그대로 남아있습니다: {e}")
        return False
