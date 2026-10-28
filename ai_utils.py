import aiohttp
import asyncio
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
5) 마지막 문장은 따뜻한 루틴 실천 독려 문장으로 끝내기
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

다음 주에도 각자의 자리에서 꾸준히 루틴을 이어가 봐요!

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


async def generate_card_routine_summary(nickname: str, routine_name: str, certs: list) -> str:
    """카드뉴스용 루틴의 상세 소통형 요약 텍스트를 생성합니다."""
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
                    result = result.replace("**", "").replace("#", "").replace("`", "")
                    if result and len(result) > 10:
                        return result[:250]
    except Exception as e:
        print(f"카드뉴스 루틴 요약 생성 에러: {e}")

    return f"{nickname}님이 '{routine_name}' 루틴을 열심히 실천 중이에요! 🔥 우리 서로 격려의 한마디를 남겨볼까요? ✨"
