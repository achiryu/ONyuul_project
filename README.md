#  온율 (Onyuul) - CBT 기반 AI 심리 케어 동반자

> Gemini Live API 기반의 실시간 음성 대화를 통해 마음 상태를 점검하고, 인지행동치료(CBT) 기법으로 심리적 안정을 돕는 AI 음성 어시스턴트입니다.

---

##  주요 기능 (Key Features)

*  **실시간 양방향 음성 대화**: Google Gemini Live API를 활용하여 딜레이 없는 자연스러운 음성 상호작용 제공
*  **CBT 기반 심리 지원 기능**:
  * **자동적 사고 기록 (Thought Records)**: 부정적 생각 패턴 식별 및 인지적 재구성 지원
  * **마음 안정 가이드 (Grounding & Breathing)**: 급작스러운 불안/스트레스 완화를 위한 호흡 및 5-4-3-2-1 그라운딩 세션 제공
  * **긍정 기억 앵커 (Positive Anchors)**: 소소한 기쁨이나 긍정적 기억을 기록하고 필요시 환원
  * **마이크로 퀘스트 (Micro Quests)**: 무기력감 극복을 위한 아주 작은 일상 미션 부여 및 관리
  * **기분 & 수면 로그 (Mood & Sleep Tracking)**: 일별 기분 및 수면 패턴 모니터링
*  **로컬 중심 데이터 저장**: 개인의 내밀한 감정 및 대화 데이터를 외부 서버가 아닌 기기 내부 SQLite DB에 안전하게 관리

---

## 🛠️ 기술 스택 (Tech Stack)

* **Language**: Python 3.10+
* **AI Model**: Google Gemini Live API (`google-genai`)
* **Audio I/O**: PyAudio (16kHz Input / 24kHz Output PCM Streaming)
* **Database**: SQLite3 (Local DB - CBT Memory Management)
* **UI**: Tkinter / Custom Python GUI Framework

---

## 🚀 시작하기 (Getting Started)

### 1. 사전 요구사항 (Prerequisites)
* Python 3.10 이상
* PyAudio 동작을 위한 시스템 오디오 라이브러리 (PortAudio)

### 2. 프로젝트 클론 및 패키지 설치
```bash
# 레포지토리 클론
git clone [https://github.com/사용자이름/onyul-cbt-ai.git](https://github.com/사용자이름/onyul-cbt-ai.git)
cd onyul-cbt-ai

# 필요 라이브러리 설치
pip install -r requirements.txt
