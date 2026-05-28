"""
카드뉴스 생성 모듈
- 배경 이미지 위에 텍스트를 합성하여 6장의 카드뉴스 이미지를 생성합니다.
- 1장: 인트로 (타이틀)
- 2~5장: 이번 주 주목 루틴 4개 소개
- 6장: 아웃트로 (다음 주 독려)
"""

import os
import textwrap
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ============================
# 설정
# ============================
BG_IMAGE_PATH = os.path.join(
    os.path.dirname(__file__),
    "assests",
    "ChatGPT Image 2026년 5월 26일 오후 01_42_19.png",
)

CARD_WIDTH = 1080
CARD_HEIGHT = 1080

# 폰트 경로 (Windows 기본 맑은 고딕)
FONT_BOLD_PATH = "C:/Windows/Fonts/malgunbd.ttf"
FONT_REGULAR_PATH = "C:/Windows/Fonts/malgun.ttf"

# 색상 팔레트
COLOR_WHITE = (255, 255, 255, 255)
COLOR_SHADOW = (0, 0, 0, 180)
COLOR_OVERLAY_DARK = (15, 15, 40, 160)
COLOR_ACCENT = (200, 180, 255, 255)  # 연보라 (배경과 어울리는)
COLOR_HIGHLIGHT = (255, 220, 120, 255)  # 골드 강조
COLOR_SOFT_WHITE = (220, 220, 235, 220)  # 부드러운 흰색


def _strip_emoji(text: str) -> str:
    """이모지를 제거하여 맑은 고딕 폰트에서 깨지지 않도록 합니다."""
    import re
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # 이모티콘
        "\U0001F300-\U0001F5FF"  # 기호 및 픽토그래프
        "\U0001F680-\U0001F6FF"  # 교통 및 지도
        "\U0001F1E0-\U0001F1FF"  # 국기
        "\U0001F900-\U0001F9FF"  # 보충 이모지
        "\U0001FA00-\U0001FA6F"  # 체스 기호
        "\U0001FA70-\U0001FAFF"  # 기호 확장
        "\U00002702-\U000027B0"  # Dingbats
        "\U0000FE00-\U0000FE0F"  # Variation Selectors
        "\U0000200D"             # Zero Width Joiner
        "\U00002600-\U000026FF"  # 잡다 기호
        "\U00002700-\U000027BF"  # Dingbats
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _load_background() -> Image.Image:
    """배경 이미지를 로드하고 CARD_WIDTH x CARD_HEIGHT로 리사이즈합니다."""
    bg = Image.open(BG_IMAGE_PATH).convert("RGBA")
    bg = bg.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)
    return bg


def _apply_overlay(bg: Image.Image, opacity: int = 160) -> Image.Image:
    """배경 이미지 위에 반투명 어두운 오버레이를 적용합니다."""
    overlay = Image.new("RGBA", bg.size, (15, 15, 40, opacity))
    return Image.alpha_composite(bg, overlay)


def _get_font(bold: bool = False, size: int = 48) -> ImageFont.FreeTypeFont:
    """폰트 객체를 반환합니다."""
    path = FONT_BOLD_PATH if bold else FONT_REGULAR_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        # 폴백: 기본 폰트
        return ImageFont.load_default()


def _draw_text_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill=COLOR_WHITE,
    shadow: bool = True,
    max_width: int = None,
):
    """텍스트를 수평 중앙 정렬로 그립니다. 필요 시 자동 줄 바꿈합니다."""
    if max_width is None:
        max_width = CARD_WIDTH - 120  # 좌우 패딩 60px

    # 이모지 제거
    text = _strip_emoji(text)

    # 텍스트 줄바꿈 처리
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line.strip():
            lines.append("")
            continue
        # 자동 줄바꿈 (글자 단위)
        wrapped = _wrap_text_by_pixel(draw, raw_line, font, max_width)
        lines.extend(wrapped)

    current_y = y
    for line in lines:
        if not line.strip():
            current_y += font.size // 2
            continue

        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (CARD_WIDTH - text_width) // 2

        if shadow:
            draw.text((x + 2, current_y + 2), line, font=font, fill=(0, 0, 0, 120))
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += text_height + 12

    return current_y


def _wrap_text_by_pixel(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list:
    """텍스트를 픽셀 기준으로 줄바꿈합니다 (한글 지원)."""
    if not text:
        return [""]

    # 먼저 전체 텍스트가 max_width 안에 들어가는지 확인
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return [text]

    lines = []
    current_line = ""
    for char in text:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] > max_width:
            if current_line:
                lines.append(current_line)
            current_line = char
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)
    return lines


def _draw_decorative_line(draw: ImageDraw.ImageDraw, y: int, width: int = 400):
    """장식선을 그립니다."""
    x_start = (CARD_WIDTH - width) // 2
    x_end = x_start + width
    # 그라데이션 효과를 위해 중앙이 밝은 선
    for offset in range(-1, 2):
        alpha = 255 if offset == 0 else 100
        draw.line(
            [(x_start, y + offset), (x_end, y + offset)],
            fill=(200, 180, 255, alpha),
            width=1,
        )


def _draw_diamond_separator(draw: ImageDraw.ImageDraw, y: int):
    """다이아몬드 장식 구분자를 그립니다."""
    cx = CARD_WIDTH // 2
    # 좌측 선
    draw.line([(cx - 180, y), (cx - 20, y)], fill=COLOR_ACCENT, width=1)
    # 다이아몬드
    diamond = [(cx, y - 6), (cx + 6, y), (cx, y + 6), (cx - 6, y)]
    draw.polygon(diamond, fill=COLOR_HIGHLIGHT)
    # 우측 선
    draw.line([(cx + 20, y), (cx + 180, y)], fill=COLOR_ACCENT, width=1)


def create_intro_card() -> BytesIO:
    """1장: 인트로 카드 - '루틴클럽, 당신의 성장을 응원합니다'"""
    bg = _load_background()
    img = _apply_overlay(bg, opacity=140)
    draw = ImageDraw.Draw(img)

    # 상단 라벨
    label_font = _get_font(bold=True, size=26)
    _draw_text_centered(draw, "- 산스 AI루틴클럽 Weekly Report -", 180, label_font, fill=COLOR_ACCENT)

    # 장식선
    _draw_decorative_line(draw, 228, width=520)

    # 메인 타이틀
    title_font = _get_font(bold=True, size=56)
    _draw_text_centered(draw, "루틴클럽,", 290, title_font, fill=COLOR_WHITE)
    _draw_text_centered(draw, "당신의 성장을", 365, title_font, fill=COLOR_WHITE)
    _draw_text_centered(draw, "응원합니다", 440, title_font, fill=COLOR_HIGHLIGHT)

    # 다이아몬드 구분자
    _draw_diamond_separator(draw, 530)

    # 하단 서브 텍스트
    sub_font = _get_font(bold=False, size=26)
    _draw_text_centered(
        draw,
        "이번 주 우리 멤버들의 빛나는 루틴 이야기를 소개합니다",
        565,
        sub_font,
        fill=COLOR_SOFT_WHITE,
    )

    # 하단 브랜딩
    brand_font = _get_font(bold=False, size=22)
    _draw_text_centered(draw, "꾸준함이 실력이 되는 곳", 900, brand_font, fill=(180, 180, 200, 180))

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


def create_routine_card(
    card_number: int,
    nickname: str,
    routine_name: str,
    summary_text: str,
    auth_count: int = 0,
) -> BytesIO:
    """2~5장: 루틴 소개 카드"""
    bg = _load_background()
    img = _apply_overlay(bg, opacity=170)
    draw = ImageDraw.Draw(img)

    # 상단 번호 뱃지
    badge_font = _get_font(bold=True, size=24)
    _draw_text_centered(draw, f"ROUTINE #{card_number}", 120, badge_font, fill=COLOR_ACCENT)

    # 구분선
    _draw_decorative_line(draw, 165, width=300)

    # 루틴 이름 (하이라이트) - 이모지 제거됨
    clean_routine_name = _strip_emoji(routine_name)
    routine_font = _get_font(bold=True, size=44)
    y_after = _draw_text_centered(draw, clean_routine_name, 210, routine_font, fill=COLOR_HIGHLIGHT)

    # 닉네임
    name_font = _get_font(bold=True, size=30)
    y_after = _draw_text_centered(draw, f"by {nickname}", y_after + 10, name_font, fill=COLOR_WHITE)

    # 인증 횟수 (있는 경우)
    if auth_count > 0:
        count_font = _get_font(bold=False, size=24)
        y_after = _draw_text_centered(
            draw,
            f"[이번 주 {auth_count}회 인증 달성]",
            y_after + 10,
            count_font,
            fill=COLOR_ACCENT,
        )

    # 다이아몬드 구분자
    _draw_diamond_separator(draw, y_after + 20)

    # 요약 텍스트 (AI 생성 또는 캡션 기반)
    clean_summary = _strip_emoji(summary_text)
    summary_font = _get_font(bold=False, size=28)
    _draw_text_centered(
        draw,
        clean_summary,
        y_after + 50,
        summary_font,
        fill=COLOR_SOFT_WHITE,
        max_width=CARD_WIDTH - 180,
    )

    # 하단 브랜딩
    brand_font = _get_font(bold=False, size=20)
    _draw_text_centered(draw, "산스 AI루틴클럽 | Weekly Highlights", 1000, brand_font, fill=(160, 160, 180, 160))

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


def create_outro_card(
    total_auths: int = 0,
    total_members: int = 0,
    next_week_msg: str = "",
) -> BytesIO:
    """6장: 아웃트로 카드 - 다음 주 독려"""
    bg = _load_background()
    img = _apply_overlay(bg, opacity=140)
    draw = ImageDraw.Draw(img)

    # 상단 라벨
    label_font = _get_font(bold=True, size=28)
    _draw_text_centered(draw, "- 이번 주도 함께 달려왔습니다 -", 160, label_font, fill=COLOR_ACCENT)

    _draw_decorative_line(draw, 210, width=500)

    # 이번 주 성과 요약
    if total_auths > 0:
        stat_font = _get_font(bold=True, size=38)
        _draw_text_centered(
            draw,
            f"총 {total_auths}개의 루틴 인증 달성!",
            260,
            stat_font,
            fill=COLOR_HIGHLIGHT,
        )
    if total_members > 0:
        member_font = _get_font(bold=False, size=28)
        _draw_text_centered(
            draw,
            f"함께 한 멤버 {total_members}명",
            320,
            member_font,
            fill=COLOR_WHITE,
        )

    # 다이아몬드 구분자
    _draw_diamond_separator(draw, 375)

    # 다음 주 독려 메시지
    encourage_title_font = _get_font(bold=True, size=44)
    _draw_text_centered(draw, "다음 주도,", 420, encourage_title_font, fill=COLOR_WHITE)
    _draw_text_centered(draw, "함께 성장해요!", 480, encourage_title_font, fill=COLOR_HIGHLIGHT)

    if next_week_msg:
        msg_font = _get_font(bold=False, size=26)
        _draw_text_centered(
            draw, _strip_emoji(next_week_msg), 560, msg_font, fill=COLOR_SOFT_WHITE, max_width=CARD_WIDTH - 180
        )
    else:
        msg_font = _get_font(bold=False, size=26)
        default_msg = (
            "작은 습관이 큰 변화를 만듭니다.\n"
            "다음 주에도 여러분의 루틴을 기록하고\n"
            "서로의 성장을 응원해주세요!"
        )
        _draw_text_centered(draw, default_msg, 560, msg_font, fill=COLOR_SOFT_WHITE)

    # 하단 CTA
    cta_font = _get_font(bold=True, size=24)
    _draw_text_centered(
        draw,
        "[봇 1:1 대화에서 사진+캡션으로 간편 인증!]",
        780,
        cta_font,
        fill=COLOR_ACCENT,
    )

    # 하단 브랜딩
    brand_font = _get_font(bold=False, size=22)
    _draw_text_centered(draw, "- 산스 AI루틴클럽 -", 900, brand_font, fill=(180, 180, 200, 200))
    _draw_text_centered(draw, "꾸준함이 실력이 되는 곳", 935, brand_font, fill=(160, 160, 180, 160))

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


def generate_card_news(
    top_routines: list,
    total_auths: int = 0,
    total_members: int = 0,
    next_week_msg: str = "",
) -> list:
    """
    카드뉴스 6장을 생성합니다.

    Args:
        top_routines: 상위 루틴 4개의 리스트. 각 항목은 dict:
            {
                "nickname": str,
                "routine_name": str,
                "summary": str,      # 루틴 요약 텍스트
                "auth_count": int,    # 이번 주 인증 횟수
            }
        total_auths: 이번 주 총 인증 수
        total_members: 참여 멤버 수
        next_week_msg: 아웃트로 다음 주 독려 메시지

    Returns:
        list of BytesIO: 6장의 이미지 바이트 스트림
    """
    cards = []

    # 1장: 인트로
    cards.append(create_intro_card())

    # 2~5장: 루틴 소개 (최대 4장)
    for i, routine_data in enumerate(top_routines[:4]):
        card_buf = create_routine_card(
            card_number=i + 1,
            nickname=routine_data.get("nickname", "회원"),
            routine_name=routine_data.get("routine_name", "루틴"),
            summary_text=routine_data.get("summary", "꾸준히 노력 중입니다!"),
            auth_count=routine_data.get("auth_count", 0),
        )
        cards.append(card_buf)

    # 6장: 아웃트로
    cards.append(create_outro_card(total_auths, total_members, next_week_msg))

    return cards
