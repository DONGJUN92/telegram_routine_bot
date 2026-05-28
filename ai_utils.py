import aiohttp
import asyncio
import json
import os
import subprocess

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/api/generate"
MODEL_NAME = os.environ.get("OLLAMA_MODEL_NAME", "gemma4:e2b")
OLLAMA_BIN = os.environ.get("OLLAMA_BIN", "ollama")
AUTO_PULL_OLLAMA_MODEL = os.environ.get("AUTO_PULL_OLLAMA_MODEL", "true").lower() in ("1", "true", "yes", "y")

async def _is_ollama_server_ready(session: aiohttp.ClientSession) -> bool:
    try:
        async with session.get(f"{OLLAMA_BASE_URL}/api/tags") as response:
            return response.status == 200
    except Exception:
        return False

async def _is_model_available(session: aiohttp.ClientSession, model_name: str) -> bool:
    try:
        async with session.get(f"{OLLAMA_BASE_URL}/api/tags") as response:
            if response.status != 200:
                return False
            data = await response.json()
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models if isinstance(m, dict)]
            return model_name in model_names
    except Exception:
        return False

async def _pull_model(session: aiohttp.ClientSession, model_name: str) -> bool:
    try:
        async with session.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": model_name, "stream": False}
        ) as response:
            return response.status == 200
    except Exception as e:
        print(f"Ollama 모델 다운로드 에러: {e}")
        return False

def _start_ollama_server() -> bool:
    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        subprocess.Popen([OLLAMA_BIN, "serve"], **popen_kwargs)
        print("🤖 Ollama 서버 자동 실행을 시도합니다...")
        return True
    except FileNotFoundError:
        print("⚠️ ollama 실행 파일을 찾지 못했습니다. Ollama 설치 또는 OLLAMA_BIN 경로를 확인해주세요.")
        return False
    except Exception as e:
        print(f"⚠️ Ollama 서버 자동 실행 실패: {e}")
        return False

async def ensure_ollama_ready(wait_seconds: int = 20, pull_model: bool = AUTO_PULL_OLLAMA_MODEL) -> bool:
    """Ollama 서버와 모델 준비 상태를 확인하고, 필요 시 자동으로 실행/다운로드합니다."""
    async with aiohttp.ClientSession() as session:
        is_ready = await _is_ollama_server_ready(session)
        if not is_ready:
            if not _start_ollama_server():
                return False

            for _ in range(wait_seconds):
                await asyncio.sleep(1)
                if await _is_ollama_server_ready(session):
                    is_ready = True
                    break

        if not is_ready:
            print("⚠️ Ollama 서버가 준비되지 않았습니다. AI 기능은 비활성 상태로 동작합니다.")
            return False

        if await _is_model_available(session, MODEL_NAME):
            return True

        if not pull_model:
            print(f"⚠️ 모델 {MODEL_NAME} 이(가) 없어 AI 기능을 건너뜁니다. AUTO_PULL_OLLAMA_MODEL=true로 설정하면 자동 다운로드됩니다.")
            return False

        print(f"⏳ 모델 {MODEL_NAME} 이(가) 없어 자동 다운로드를 시작합니다...")
        pulled = await _pull_model(session, MODEL_NAME)
        if not pulled:
            print("⚠️ 모델 자동 다운로드에 실패했습니다. AI 기능은 비활성 상태로 동작합니다.")
            return False

        return await _is_model_available(session, MODEL_NAME)

async def generate_insight_keywords(text: str) -> str:
    prompt = f"""Extract 3 keywords. No intro. Comma separated.
Input: 아침 조깅 30분. 뿌듯하다.
Output: 조깅, 아침, 뿌듯함
Input: {text}
Output:"""
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_k": 10,
            "top_p": 0.5
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    response_text = data.get("response", "").strip()
                    return response_text
    except Exception as e:
        print(f"Ollama API 에러(키워드): {e}")
    
    return ""

async def generate_routine_recommendation(logs_text: str) -> dict:
    prompt = f"""현재 루틴 데이터를 바탕으로 완전히 새로운 루틴 1개만 추천하세요.
반드시 한국어로만 답하세요. ONLY valid JSON.
규칙:
- "routine": 기존 루틴 목록에 없는 구체적이고 수치화된 루틴 이름
- "rationale": 이모지 넘버링으로 3문장 이하 (1️⃣ 문장. 2️⃣ 문장. 3️⃣ 문장.)
형식: {{"routine":"이름","rationale":"1️⃣ 이유1. 2️⃣ 이유2. 3️⃣ 이유3."}}
예시 입력: 현재루틴: 아침조깅,독서10쪽 / 인증: 오늘 책 읽으며 집중력이 좋아졌다
예시 출력: {{"routine":"저녁 5분 마인드맵 정리","rationale":"1️⃣ 독서 인사이트를 시각화해 기억을 강화합니다. 2️⃣ 하루를 정리해 수면의 질이 높아집니다. 3️⃣ 그룹원에게 공유하면 서로 영감을 줄 수 있습니다."}}
입력: {logs_text}
출력:"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.5
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    response_text = data.get("response", "").strip()
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError:
                        print("JSON 파싱 에러:", response_text)
    except Exception as e:
        print(f"Ollama API 에러(추천): {e}")
    
    return None

async def generate_weekly_insight_briefing(insights_text: str) -> str:
    prompt = f"""당신은 산스 AI루틴클럽 운영 코치입니다.
아래 입력은 이번 주 클럽원 인사이트 목록입니다.

목표:
- 읽는 즉시 "나도 참여하고 싶다"는 마음이 들게 만드는 주간 브리핑 작성
- 내용은 충분히 풍부하게, 가독성은 높게 작성

절대 규칙:
- 한국어만 사용
- 영어 단어, 알파벳, 영문 약어 사용 금지
- 한국어와 영어 병기 금지 (예: 효율성(Efficiency) 형태 금지)
- 영어 개념이 필요하면 자연스러운 한국어 표현으로 순화
- 텔레그램 가독성을 위한 마크다운은 허용: **굵게**, 줄바꿈, 빈 줄, 불릿 목록(-), 번호 목록(1. 2. 3.)
- 단, `#`, `##`, `###` 형태 헤더와 코드블록(```)은 금지
- 중요한 단어/문장만 **굵게** 처리 (최대 8회)
- 딱딱한 "합니다/했습니다"체 대신 친근한 "~요"체 사용
- 12~20문장, 700~1200자

반드시 포함:
1) **이번 주 흐름 요약** 섹션: 2~3문장
2) **인사이트를 남긴 클럽원** 섹션: 이름 3~7명 언급 (입력에 있는 이름만 사용)
3) **이번 주 핵심 키워드** 섹션: 불릿 3개
4) **다음 주 실천 제안** 섹션: 번호 목록 1. 2. 3.
5) 마지막 문장은 참여 독려 문장으로 끝내기 (/insight 자연스럽게 유도)
6) 섹션 사이 빈 줄 1줄로 문단을 분리

출력 형식 예시(형식만 참고):
**이번 주 흐름 요약**
이번 주에는 ...

**인사이트를 남긴 클럽원**
...님, ...님, ...님

**이번 주 핵심 키워드**
- ...
- ...
- ...

**다음 주 실천 제안**
1. ...
2. ...
3. ...

... /insight 로 한 줄 공유해봐요!

입력:
{insights_text}

출력:"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.55,
            "top_p": 0.7
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("response", "").strip()
    except Exception as e:
        print(f"Ollama API 에러(주간 인사이트 브리핑): {e}")

    return ""

async def generate_image_analysis(base64_image: str, user_caption: str, routine_name: str) -> str:
    prompt = f"""당신은 산스 AI루틴클럽의 코치입니다.
멤버가 다음 루틴을 달성하여 인증 사진을 보냈습니다.

- 루틴명: {routine_name}
- 멤버의 다짐/메시지: {user_caption}

목표:
- 이 인증 사진(이미지)을 보고 어떤 훌륭한 노력이 있었는지 구체적이고 칭찬이 넘치는 2~3문장의 따뜻한 코멘트를 한국어로 작성해주세요.
- 이미지가 공부하는 책, 컴퓨터 화면, 홈트레이닝 모습, 건강한 식단 등 무엇인지 인식하고 그 내용을 격려에 포함해주세요.
- 절대 격식 차리지 말고 친근한 "~요"체로 작성해주세요.
- 영어나 병기 표현은 제외하고 자연스러운 한국어로만 작성하세요."""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "images": [base64_image],
        "options": {
            "temperature": 0.6
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("response", "").strip()
    except Exception as e:
        print(f"Ollama 멀티모달 API 에러(이미지 분석): {e}")
    
    return ""

async def generate_insight_summary(text: str) -> dict:
    prompt = f"""아래 텔레그램 루틴 인사이트를 읽고, 알맞은 대카테고리 1개(예: AI 활용, 업무 효율화, 자기계발, 건강, 생활 꿀팁 등)를 선정하고, 본문 내용을 1줄로 강렬하게 요약한 JSON 객체만 리턴하세요.
반드시 한국어로만 작성하고, 오직 유효한 JSON 형식만 출력해야 합니다.
형식: {{"category":"대카테고리명", "summary":"1줄 요약문"}}
예시 입력: 이번에 텔레그램 봇 코드를 파이썬 비동기로 짰는데 속도가 2배 빨라졌다. AI API 호출할 때 asyncio.create_task 적극 추천한다.
예시 출력: {{"category":"AI 활용", "summary":"비동기 프로그래밍(create_task)을 활용한 AI API 응답 성능 극대화 노하우"}}

입력: {text}
출력:"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.4
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    response_text = data.get("response", "").strip()
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError:
                        print("JSON 파싱 에러(인사이트 요약):", response_text)
    except Exception as e:
        print(f"Ollama API 에러(인사이트 요약): {e}")
        
    return None

async def generate_catalyst_mission(mission_theme: str = "") -> str:
    prompt = f"""당신은 루틴클럽 코치입니다.
월요일, 금요일, 토요일 오후 3시 반에 커뮤니티 활성화를 위한 AI 연계 번개 미션을 제안합니다.

오늘의 고정 미션 유형:
{mission_theme}

미션 조건:
- 반드시 오늘의 고정 미션 유형을 따르고, 다른 유형의 미션을 제안하지 마세요.
- 월요일은 글쓰기, 금요일은 이미지 혹은 동영상 생성, 토요일은 내게 필요한 간단한 토이 서비스 만들기로만 제안하세요.
- 반드시 AI 서비스/툴(ChatGPT, Claude, Midjourney, Cursor 등)을 활용·접목한 사소하고 재밌는 미션 1개 제안.
- 예시: AI로 5문장 회고 쓰기, 한 주를 상징하는 이미지 만들기, 나만의 작은 체크리스트 웹앱 만들기 등.
- 글자 수 150~300자 이내, 가독성 높은 이모지 활용, 친근한 "~요"체 한국어.
- 말미에 "사소한 AI 캡처나 작은 AI 결과물이라도 좋으니 지금 바로 이 방에 공유해주세요! 👇" 문구 필수 포함.
- 영어 병기 금지, 마크다운은 '**굵게**'만 사용. (샵'#' 및 코드블록'```' 금지).

출력:"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.8
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("response", "").strip()
    except Exception as e:
        print(f"Ollama API 에러(소소한 챌린지 촉매제): {e}")
        
    return ""


async def generate_card_routine_summary(nickname: str, routine_name: str, certs: list) -> str:
    """카드뉴스용 루틴의 상세 소통형 요약 텍스트를 생성합니다."""
    # 최대 3개의 인증만 참고하여 프롬프트 길이를 조절하고 토큰을 아낍니다.
    cert_lines = []
    for idx, cert in enumerate(certs[:3]):
        cap = cert.get("caption", "내용 없음")
        img = cert.get("image_url", "이미지 없음")
        if len(cap) > 100:
            cap = cap[:100] + "..."
        cert_lines.append(f"- 인증 {idx+1}: {cap} ({img})")
    certs_text = "\n".join(cert_lines) if cert_lines else "인증 기록 없음"

    prompt = f"""루틴클럽 멤버 {nickname}님의 이번 주 루틴 '{routine_name}' 인증 기록입니다.
이 기록을 바탕으로 {nickname}님이 어떤 종류의 활동(글쓰기, 이미지 제작, 코딩 등)을 하였는지 2문장으로 요약하고, 다른 클럽원들이 소통이나 질문을 할 수 있도록 친근한 '~요' 체로 유도하는 코멘트를 한국어로만 작성하세요. (이모지 1~2개 포함)

[멤버 인증 기록]
{certs_text}

출력 예시: {nickname}님은 이번 주 코딩 활동을 통해 알고리즘을 성실히 풀어주셨어요! 어떤 문제를 해결하셨는지 정말 궁금하네요. 우리 함께 응원하고 댓글로 이야기 나눠요!

응원 요약 코멘트:"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.6,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=90)) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("response", "").strip()
                    # 불필요한 마크다운 제거
                    result = result.replace("**", "").replace("#", "").replace("`", "")
                    if result and len(result) > 10:
                        return result[:250]
    except Exception as e:
        print(f"카드뉴스 루틴 요약 생성 에러: {e}")

    return f"{nickname}님이 '{routine_name}' 루틴에 열심히 실천 중이에요! 🔥 우리 서로 격려의 한마디를 남겨볼까요? ✨"
