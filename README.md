# 🌙 온율 (Onyuul) - CBT 기반 AI 심리 케어 동반자

> Gemini Live API 기반의 실시간 음성 대화를 통해 마음 상태를 점검하고, 인지행동치료(CBT) 기법으로 심리적 안정을 돕는 AI 음성 어시스턴트입니다.

---

## ⚠️ 중요 안내

**온율은 전문적인 심리 치료·상담을 대체하지 않습니다.** 정서적 지지와 CBT 원리를 활용한 대화를 통해 일상적인 마음 돌봄을 돕는 동반자 도구이며, 의사·상담사·심리 치료 전문가의 진단과 치료를 대체할 수 없습니다. 지속적으로 힘든 시간이 이어진다면 반드시 전문가와 상담해보시길 권해드립니다.

위기 상황이라면 아래로 연락해주세요.

- 자살예방상담전화 **109** (24시간)
- 정신건강 위기상담전화 **1577-0199** (24시간)
- 긴급 상황 **112**

---

## ✨ 주요 기능 (Key Features)

### 실시간 대화
* **실시간 양방향 음성 대화**: Google Gemini Live API를 활용하여 딜레이 없는 자연스러운 음성 상호작용 제공
* **커스텀 웨이크워드**: "온율아" 등 호출어로 대화 시작, 사용자가 직접 변형 발음을 등록해 인식률 개선 가능
* **대기 모드 / 마이크 끄기**: 대화를 잠시 멈추고 싶을 때 웨이크워드만 듣는 대기 모드, 혹은 마이크 자체를 완전히 차단하는 모드를 상황에 맞게 선택 가능

### CBT 기반 심리 지원
* **자동적 사고 기록 (Thought Records)**: 부정적 생각 패턴과 인지 오류 식별, 대안적 사고를 함께 찾아가는 CBT식 인지 재구성 지원
* **마음 안정 가이드 (Grounding & Breathing)**: 급작스러운 불안/스트레스 완화를 위한 4-7-8 호흡 및 그라운딩 세션 제공
* **긍정 기억 앵커 (Positive Anchors)**: 소소한 기쁨이나 긍정적 기억을 기록하고 필요할 때 다시 꺼내볼 수 있음
* **마이크로 퀘스트 (Micro Quests)**: 무기력감 극복을 위한 아주 작은 일상 미션 부여 및 진행률 관리
* **기분 & 수면 로그 (Mood & Sleep Tracking)**: 일별 기분 점수와 수면 시간을 기록하고, 기간별 추이를 차트로 확인
* **자유 일기**: AI 개입 없이 순수하게 생각을 적어두는 공간

### 안전 관리
* **2단계 위기 감지**: 정규식 기반 즉각 감지 + LLM 기반 문맥 판단의 이중 안전장치
* **나만의 안전 계획**: 경고 신호, 대처법, 비상 연락처를 미리 작성해두고 위기 시 즉시 확인
* **위기 이후 팔로우업**: 위기 개입이 있었던 다음 날, 부드럽게 안부를 확인하는 자동 리마인더

### 일상 비서
* **알림 & 복약 관리**: 반복 일정(매일/매주) 등록 및 자동 음성 알림
* **할 일 관리**: 마감일·우선순위 기반 태스크 관리, 마감 임박/초과 항목 강조
* **파일·프로그램 검색**: 음성으로 PC 내 파일/폴더를 찾아 열거나 프로그램 실행 (안전을 위한 확인 절차 포함)
* **데일리 브리핑**: 날씨, 오늘의 할 일, 최근 긍정적인 순간을 한 번에 정리

### 데이터 보안 & 개인정보
* **로컬 중심 데이터 저장**: 개인의 내밀한 감정 및 대화 데이터를 외부 서버가 아닌 기기 내부 SQLite DB에 저장
* **휴지 상태 암호화 (At-rest Encryption)**: 앱이 꺼져 있는 동안에는 Windows DPAPI로 보호되는 키를 이용해 DB 파일 자체를 암호화, 파일을 그대로 복사해가도 열람 불가
* **백업 & 완전 삭제**: 언제든 데이터를 백업하거나 영구 삭제 가능

---

## 🛠️ 기술 스택 (Tech Stack)

* **Language**: Python 3.10+
* **AI Model**: Google Gemini Live API (`google-genai`)
* **STT (자막)**: `faster-whisper`
* **Audio I/O**: PyAudio (16kHz Input / 24kHz Output PCM Streaming)
* **UI Framework**: `customtkinter`
* **Database**: SQLite3 (Local DB, WAL 모드)
* **DB 암호화**: `cryptography` (Fernet) + `pywin32` (Windows DPAPI)
* **차트**: `matplotlib` (기분 리포트)
* **트레이 아이콘**: `pystray`
* **오디오 신호 처리**: `numpy` (볼륨 조절)

---

## 📁 프로젝트 구조

```
jarvis_cbt_project/
├── jarvis_ui.py              # 메인 진입점 — GUI, Gemini Live API 연동, 도구(tool) 디스패치
├── config_manager.py         # API 키/테마/볼륨/자동실행 등 설정 저장·조회
├── guardrail_interceptor.py  # 위기 감지(정규식 1차 + LLM 2차), SessionState
├── cbt_memory.py              # core/mental_care.py로 위임하는 파사드
│
├── core/
│   ├── db.py                  # SQLite 연결 관리 (WAL 모드)
│   ├── db_crypto.py           # DB 암호화(휴지 상태) — Fernet + Windows DPAPI
│   ├── safety.py              # 안전 계획 관리
│   ├── mental_care.py         # 기분/사고기록/퀘스트/긍정기억/자유일기 등 CBT 데이터 관리
│   ├── reminders.py           # 알림/복약 일정
│   └── tasks.py                # 마감 있는 할 일
│
├── productivity/
│   └── productivity_manager.py  # 브레인덤프 분류, 데일리 브리핑 텍스트 생성
│
└── assets/
    └── icons/                  # UI 아이콘 (Lucide, PNG)
```

---

## 🚀 시작하기 (Getting Started)

### 1. 사전 요구사항 (Prerequisites)

* Python 3.10 이상
* PyAudio 동작을 위한 시스템 오디오 라이브러리 (PortAudio)
* [Google AI Studio](https://aistudio.google.com/apikey)에서 발급받은 Gemini API 키 (무료로 발급 가능)

### 2. 프로젝트 클론 및 패키지 설치

```bash
# 레포지토리 클론
git clone https://github.com/사용자이름/onyul-cbt-ai.git
cd onyul-cbt-ai

# (권장) 가상환경 생성 및 활성화
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # macOS/Linux

# 필요 라이브러리 설치
pip install -r requirements.txt
```

### 3. 실행

```bash
python jarvis_ui.py
```

최초 실행 시 API 키 입력 창이 뜹니다. 안내에 따라 키를 붙여넣으면 바로 시작됩니다.

---

## 📦 실행 파일(.exe)로 빌드하기

Windows용 단일 실행 파일이 필요하다면 PyInstaller를 사용합니다.

```bash
pip install pyinstaller

pyinstaller jarvis_ui.py ^
  --name ONyuul ^
  --console ^
  --collect-data customtkinter ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all pystray ^
  --collect-all cryptography ^
  --hidden-import=google.genai ^
  --hidden-import=google.genai.types ^
  --hidden-import=PIL ^
  --hidden-import=win32crypt ^
  --hidden-import=numpy
```

빌드가 끝나면 `dist/ONyuul/` 폴더에 실행 파일이 생성됩니다. **`assets` 폴더는 자동으로 포함되지 않으므로, 빌드 후 `dist/ONyuul/` 안에 직접 복사**해주세요.

---

## 🔒 데이터와 개인정보

- 모든 대화·기분·사고기록 데이터는 사용자 PC에만 저장되며, Google Gemini API 호출 외에는 외부로 전송되지 않습니다.
- 앱이 실행 중이 아닐 때는 DB 파일이 암호화된 상태로 보관됩니다.
- 앱 내 설정에서 데이터를 언제든 백업하거나 완전히 삭제할 수 있습니다.

---

## 🗺️ 로드맵

- [ ] 수면 기록 전용 조회 탭
- [ ] 사고기록 통계/패턴 분석
- [ ] 자동화 테스트 스위트 도입

---

## 🤝 기여 (Contributing)

버그 제보나 기능 제안은 이슈로 남겨주세요. Pull Request도 환영합니다.

## 📄 라이선스

이 프로젝트는 [MIT License](LICENSE)를 따릅니다.

## 💬 피드백

사용해보시고 느끼신 점이 있다면 이슈나 디스커션으로 편하게 남겨주세요.
