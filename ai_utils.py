import asyncio
import logging
import os
import re
import time
import aiohttp

LOGGER = logging.getLogger("routine_bot.ai")

OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"

# 모델 리스트 캐시 (단시간 내 연속 호출 시 불필요한 중복 조회를 줄이되, 기본 매 실행 시 갱신 가능)
_CACHED_FREE_MODELS: list[dict] = []
_CACHED_AT: float = 0.0
_CACHE_TTL_SECONDS = float(os.environ.get("OPENROUTER_MODEL_CACHE_TTL_SECONDS", "0"))

_FALLBACK_FREE_TEXT_MODELS = [
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "thinkingmachines/inkling:free",
]
_FALLBACK_FREE_VISION_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "thinkingmachines/inkling:free",
    "dots-studio/dots-3-note-preview:free",
]

_NON_GENERATIVE_KEYWORDS = (
    "safety",
    "guard",
    "moderation",
    "embed",
    "rerank",
    "whisper",
    "tts",
)


def _get_openrouter_api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def _extract_param_billions(model_id: str, model_name: str = "") -> float:
    """모델 ID/이름에서 파라미터 크기(단위: B)를 추출합니다."""
    combined = f"{model_id} {model_name}".lower()
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", combined)
    if not matches:
        return 15.0  # 표기 없는 중대형 모델 기본 추정치
    try:
        return max(float(m) for m in matches)
    except ValueError:
        return 15.0


def _supports_vision(model_dict: dict) -> bool:
    arch = model_dict.get("architecture") or {}
    input_mods = [str(m).lower() for m in (arch.get("input_modalities") or ())]
    if "image" in input_mods:
        return True
    modality = str(arch.get("modality") or "").lower()
    if "image" in modality:
        return True
    model_id = str(model_dict.get("id") or "").lower()
    return any(tok in model_id for tok in ("vl", "vision", "gemma-4", "gemma-3", "gemini", "pixtral"))


def _is_generative_text_model(model_dict: dict) -> bool:
    model_id = str(model_dict.get("id") or "").lower()
    if not model_id.endswith(":free"):
        return False
    if any(bad in model_id for bad in _NON_GENERATIVE_KEYWORDS):
        return False
    arch = model_dict.get("architecture") or {}
    output_mods = [str(m).lower() for m in (arch.get("output_modalities") or ["text"])]
    return "text" in output_mods


def _score_free_model(model_dict: dict, *, require_vision: bool = False) -> float:
    """
    OpenRouter의 :free 모델의 한국어 및 생성 성능을 추정해 점수를 부여합니다.
    높은 점수일수록 먼저 시도됩니다.
    """
    model_id = str(model_dict.get("id") or "").lower()
    model_name = str(model_dict.get("name") or "").lower()
    score = 100.0

    # 1. 검증된 글로벌/다국어(한국어 우수) 플래그십 패밀리 가중치
    if any(k in model_id for k in ("google/gemini", "google/gemma-4", "google/gemma-3")):
        score += 780.0
    elif any(k in model_id for k in ("openai/", "anthropic/", "deepseek/", "qwen/")):
        score += 650.0
    elif "meta-llama/" in model_id:
        score += 480.0
    elif "nvidia/nemotron" in model_id:
        score += 400.0
    elif "thinkingmachines/inkling" in model_id:
        score += 370.0
    elif any(k in model_id for k in ("mistralai/", "cohere/", "xingchen")):
        score += 330.0

    # 2. 파라미터 규모 가중치 (대형 모델 우선)
    param_b = _extract_param_billions(model_id, model_name)
    score += min(param_b * 3.5, 280.0)

    # 3. 모델 등급 키워드 보정
    if any(tok in model_id for tok in ("ultra", "super", "pro", "large")):
        score += 75.0
    if any(tok in model_id for tok in ("nano", "xs", "mini", "small", "lightning", "tiny")):
        score -= 45.0
    if "code" in model_id and not require_vision:
        score -= 30.0  # 코딩 특화 모델보다 일반 대화/코칭 모델 우선

    # 4. 컨텍스트 길이 보너스
    try:
        ctx_len = int(model_dict.get("context_length") or 0)
    except (TypeError, ValueError):
        ctx_len = 0
    score += min(ctx_len / 10000.0, 100.0)

    # 5. 멀티모달 요청 시 이미지 지원 모델 최우선
    if require_vision and _supports_vision(model_dict):
        score += 300.0

    return round(score, 2)


async def fetch_ranked_free_models(
    session: aiohttp.ClientSession | None = None,
    *,
    require_vision: bool = False,
    force_refresh: bool = True,
) -> list[str]:
    """
    OpenRouter API에서 현재 사용 가능한 ':free' 모델을 실시간 조회하고,
    성능 점수 내림차순으로 정렬한 모델 ID 리스트를 반환합니다.
    """
    global _CACHED_FREE_MODELS, _CACHED_AT

    now = time.monotonic()
    raw_models = None
    if not force_refresh and _CACHED_FREE_MODELS:
        raw_models = _CACHED_FREE_MODELS

    if raw_models is None:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True
        try:
            headers = {}
            api_key = _get_openrouter_api_key()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with session.get(
                OPENROUTER_MODELS_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 200:
                    payload = await response.json()
                    data = payload.get("data", [])
                    if isinstance(data, list) and data:
                        raw_models = data
                        _CACHED_FREE_MODELS = data
                        _CACHED_AT = now
                else:
                    LOGGER.warning("OpenRouter models API returned status %s", response.status)
        except Exception as error:
            LOGGER.warning("Failed to fetch live :free models from OpenRouter: %s", error)
        finally:
            if close_session:
                await session.close()

    if not raw_models:
        raw_models = _CACHED_FREE_MODELS

    if raw_models:
        candidates = []
        for m in raw_models:
            if not isinstance(m, dict) or not _is_generative_text_model(m):
                continue
            if require_vision and not _supports_vision(m):
                continue
            candidates.append(m)

        candidates.sort(
            key=lambda item: (
                -_score_free_model(item, require_vision=require_vision),
                str(item.get("id", "")),
            )
        )
        ranked_ids = [str(m["id"]) for m in candidates if m.get("id")]
        if ranked_ids:
            return ranked_ids

    return list(_FALLBACK_FREE_VISION_MODELS if require_vision else _FALLBACK_FREE_TEXT_MODELS)


async def ensure_ollama_ready(wait_seconds: int = 20, pull_model: bool = True) -> bool:
    """
    봇 시작 시 OpenRouter ':free' 모델 리스트업 및 API 키 상태를 점검합니다.
    (기존 main.py의 호출 인터페이스 호환을 위해 함수명을 유지합니다.)
    """
    ranked_text = await fetch_ranked_free_models(require_vision=False, force_refresh=True)
    ranked_vision = await fetch_ranked_free_models(require_vision=True, force_refresh=False)
    api_key = _get_openrouter_api_key()

    LOGGER.info(
        "OpenRouter :free models ready (total=%s, vision=%s) | Top text: %s | Top vision: %s",
        len(ranked_text),
        len(ranked_vision),
        ", ".join(ranked_text[:3]),
        ", ".join(ranked_vision[:3]),
    )
    if not api_key:
        print("⚠️ OPENROUTER_API_KEY가 설정되지 않았습니다. .env 또는 Render 환경변수에 OPENROUTER_API_KEY를 설정하면 AI 기능이 활성화됩니다.")
        return False

    print(f"✅ OpenRouter :free 모델 {len(ranked_text)}개 리스트업 완료! (1순위: {ranked_text[0] if ranked_text else 'N/A'})")
    return bool(ranked_text)


async def _call_openrouter_with_fallback(
    messages: list[dict],
    *,
    require_vision: bool = False,
    temperature: float = 0.55,
    max_attempts: int = 8,
    min_response_length: int = 5,
    timeout_seconds: int = 60,
    label: str = "OpenRouter AI",
) -> str:
    """
    실행 직전 OpenRouter에서 ':free' 모델을 성능 순으로 리스트업하고,
    1순위 모델부터 호출하여 실패 시 다음 순위 모델로 자동 전환(Fallback)합니다.
    """
    api_key = _get_openrouter_api_key()
    if not api_key:
        LOGGER.warning("Skipped %s because OPENROUTER_API_KEY is not configured", label)
        return ""

    async with aiohttp.ClientSession() as session:
        ranked_models = await fetch_ranked_free_models(
            session,
            require_vision=require_vision,
            force_refresh=True,
        )
        if not ranked_models:
            LOGGER.warning("No :free models available on OpenRouter for %s", label)
            return ""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/DONGJUN92/telegram_routine_bot",
            "X-Title": "Sans AI Routine Club Bot",
        }

        models_to_try = ranked_models[: max(1, max_attempts)]
        for attempt_idx, model_id in enumerate(models_to_try, start=1):
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
            }
            try:
                async with session.post(
                    OPENROUTER_CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as response:
                    data = await response.json(content_type=None)
                    if response.status != 200 or (isinstance(data, dict) and "error" in data):
                        err_detail = data.get("error") if isinstance(data, dict) else f"HTTP {response.status}"
                        LOGGER.warning(
                            "[%s] Attempt %s/%s failed on model %s (%s); trying next :free model",
                            label,
                            attempt_idx,
                            len(models_to_try),
                            model_id,
                            err_detail,
                        )
                        continue

                    choices = data.get("choices") if isinstance(data, dict) else None
                    if not choices or not isinstance(choices, list):
                        LOGGER.warning(
                            "[%s] Attempt %s/%s returned no choices on model %s; trying next :free model",
                            label,
                            attempt_idx,
                            len(models_to_try),
                            model_id,
                        )
                        continue

                    message_obj = choices[0].get("message") or {}
                    content = str(message_obj.get("content") or "").strip()
                    if len(content) < min_response_length:
                        LOGGER.warning(
                            "[%s] Attempt %s/%s returned empty/short content on model %s; trying next :free model",
                            label,
                            attempt_idx,
                            len(models_to_try),
                            model_id,
                        )
                        continue

                    LOGGER.info(
                        "[%s] Succeeded with model %s (attempt %s/%s)",
                        label,
                        model_id,
                        attempt_idx,
                        len(models_to_try),
                    )
                    return content
            except Exception as error:
                LOGGER.warning(
                    "[%s] Attempt %s/%s exception on model %s: %s; trying next :free model",
                    label,
                    attempt_idx,
                    len(models_to_try),
                    model_id,
                    error,
                )
                continue

    LOGGER.error("[%s] All %s :free model attempts failed", label, len(models_to_try))
    return ""


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

입력:
{insights_text}

출력:"""

    return await _call_openrouter_with_fallback(
        [{"role": "user", "content": prompt}],
        require_vision=False,
        temperature=0.55,
        min_response_length=30,
        timeout_seconds=60,
        label="주간 인사이트 브리핑",
    )


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

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                },
            ],
        }
    ]
    return await _call_openrouter_with_fallback(
        messages,
        require_vision=True,
        temperature=0.6,
        min_response_length=10,
        timeout_seconds=45,
        label="인증 이미지 멀티모달 코칭",
    )


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

    result = await _call_openrouter_with_fallback(
        [{"role": "user", "content": prompt}],
        require_vision=False,
        temperature=0.6,
        min_response_length=10,
        timeout_seconds=60,
        label="카드뉴스 루틴 요약",
    )
    if result:
        cleaned = result.replace("**", "").replace("#", "").replace("`", "").strip()
        if len(cleaned) > 10:
            return cleaned[:250]

    return f"{nickname}님이 '{routine_name}' 루틴을 열심히 실천 중이에요! 🔥 우리 서로 격려의 한마디를 남겨볼까요? ✨"
