import aiohttp
import json

OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "gemma3:1b"

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
