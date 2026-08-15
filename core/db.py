"""
core.db
=======
SQLite 연결 생성 공통 헬퍼.

안전(safety)과 멘탈케어(mental_care) 모듈이 같은 DB 파일을 쓰되,
연결 생성 로직만 공유하고 테이블/쿼리는 서로 건드리지 않도록 분리했습니다.
"""
import sqlite3
from contextlib import contextmanager


def get_connection(db_path: str) -> sqlite3.Connection:
    """Row factory가 설정된 SQLite 연결을 반환합니다.

    journal_mode=WAL: 이 프로젝트는 Tkinter 메인 스레드(차트/갤러리 렌더링)와
    asyncio 백그라운드 스레드(도구 실행)가 동시에 같은 DB 파일에 접근한다.
    기본 롤백 저널 모드는 쓰기 중 다른 연결의 읽기/쓰기를 막아 최대 busy timeout
    만큼 그쪽 스레드가 멈춘 것처럼 보일 수 있다. WAL 모드는 읽기가 쓰기를
    거의 막지 않아 이런 경합을 크게 줄여준다.
    """
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def connection_scope(db_path: str):
    """
    연결을 열고, with 블록이 끝나면 커밋(예외 시 롤백)까지 마친 뒤 반드시 닫는다.

    sqlite3.Connection을 그대로 `with conn:`으로 쓰면 트랜잭션만 커밋/롤백될 뿐
    커넥션 자체는 닫히지 않는다(파이썬 공식 문서에 명시된 동작). 이 프로젝트는
    메서드 호출마다 매번 새 커넥션을 여는 구조라, 그렇게 두면 닫히지 않은
    커넥션이 계속 쌓인다. 이 헬퍼가 그 누수를 막는다.

    호출부는 그대로 `with self._conn() as conn:` 형태를 유지하면 되고,
    각 파일의 `_conn()`이 get_connection 대신 이 함수를 반환하도록만 바꾸면 된다.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
