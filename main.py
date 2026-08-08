import os
import json
import glob
import mimetypes
import tempfile
import traceback
from urllib.parse import urlparse

from flask import Flask, request, jsonify
from flask_cors import CORS

import yt_dlp

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# =========================================================
# 기본 설정
# =========================================================

app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)


# =========================================================
# Gemini 결과 구조
# =========================================================

class ScoreResult(BaseModel):
    title: str = Field(
        description="곡 제목"
    )

    artist: str = Field(
        description="아티스트 또는 가수. 모르면 빈 문자열"
    )

    bpm: float = Field(
        description="추정 BPM. 알 수 없으면 0"
    )

    key: str = Field(
        description="곡의 조성. 예: G Major, A minor"
    )

    time_signature: str = Field(
        description="박자. 예: 4/4"
    )

    chords: list[str] = Field(
        description="곡에서 사용되는 주요 코드 목록"
    )

    sections: list[str] = Field(
        description="곡 구조. 예: Intro, Verse, Chorus, Bridge, Outro"
    )

    lyrics: str = Field(
        description="가능한 범위의 가사. 불확실하면 빈 문자열"
    )

    abcNotation: str = Field(
        description="ABCjs에서 바로 렌더링할 수 있는 전체 ABC notation"
    )

    confidence: str = Field(
        description="high, medium, low 중 하나"
    )

    notes: str = Field(
        description="분석상 주의사항이나 불확실한 부분"
    )


# =========================================================
# 유틸리티
# =========================================================

def is_youtube_url(url: str) -> bool:
    """
    YouTube URL인지 검사합니다.
    """
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        allowed = [
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "www.youtu.be"
        ]

        return any(
            host == item or host.endswith("." + item)
            for item in allowed
        )

    except Exception:
        return False


def get_mime_type(file_path: str) -> str:
    """
    Gemini에 전달할 MIME type을 결정합니다.
    """
    ext = os.path.splitext(file_path)[1].lower()

    mapping = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
        ".flac": "audio/flac"
    }

    return mapping.get(
        ext,
        mimetypes.guess_type(file_path)[0] or "audio/mpeg"
    )


def clean_abc(abc: str, title: str) -> str:
    """
    Gemini가 반환한 ABC 문자열을 기본적으로 정리합니다.
    """

    if not abc:
        return create_fallback_abc(title)

    abc = abc.strip()

    # Markdown code fence 제거
    if abc.startswith("```"):
        lines = abc.splitlines()

        cleaned = []

        for line in lines:
            if line.strip().startswith("```"):
                continue

            if line.strip().lower() in ["abc", "abcjs"]:
                continue

            cleaned.append(line)

        abc = "\n".join(cleaned).strip()

    # X: 헤더가 없으면 추가
    if not abc.startswith("X:"):
        abc = "X:1\n" + abc

    # Title 헤더가 없으면 추가
    if "\nT:" not in abc and not abc.startswith("T:"):
        abc = abc.replace(
            "X:1",
            "X:1\nT:" + title,
            1
        )

    # 최소 기본 설정이 없는 경우 추가
    if "\nM:" not in abc:
        abc = abc.replace(
            "X:1",
            "X:1\nM:4/4",
            1
        )

    if "\nL:" not in abc:
        abc = abc.replace(
            "X:1",
            "X:1\nL:1/4",
            1
        )

    if "\nK:" not in abc:
        abc = abc.replace(
            "X:1",
            "X:1\nK:C",
            1
        )

    return abc


def create_fallback_abc(title: str) -> str:
    """
    AI 결과가 ABC를 만들지 못했을 경우에도
    웹 화면이 깨지지 않도록 최소한의 악보를 반환합니다.
    """

    return (
        "X:1\n"
        f"T:{title}\n"
        "M:4/4\n"
        "L:1/4\n"
        "K:C\n"
        '"C" C2 E2 | "G" G2 B2 | '
        '"Am" A2 c2 | "F" F2 A2 |]\n'
    )


def download_youtube_audio(youtube_url: str, temp_dir: str):
    """
    yt-dlp를 이용해 YouTube의 오디오 스트림을 다운로드합니다.

    가능한 경우 m4a를 우선 사용하고,
    없으면 bestaudio를 사용합니다.

    오디오 변환을 강제로 하지 않기 때문에
    FFmpeg 의존성을 최소화합니다.
    """

    output_template = os.path.join(
        temp_dir,
        "audio.%(ext)s"
    )

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(
            youtube_url,
            download=True
        )

        if not info:
            raise RuntimeError(
                "YouTube 정보를 가져오지 못했습니다."
            )

        title = info.get("title") or "유튜브 추출 곡"
        uploader = info.get("uploader") or ""

    files = []

    for path in glob.glob(
        os.path.join(temp_dir, "audio.*")
    ):
        if os.path.isfile(path):
            files.append(path)

    if not files:
        raise RuntimeError(
            "YouTube 오디오 파일을 다운로드하지 못했습니다."
        )

    audio_path = files[0]

    return {
        "path": audio_path,
        "title": title,
        "artist": uploader
    }


# =========================================================
# Gemini 음악 분석
# =========================================================

def analyze_audio_with_gemini(
    audio_path: str,
    title_hint: str,
    artist_hint: str
):
    """
    다운로드된 오디오 파일을 Gemini Files API로 업로드하고
    음악 구조 + 코드 + 멜로디 + 가사 + ABC notation을 요청합니다.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Render 환경변수 GEMINI_API_KEY가 설정되어 있지 않습니다."
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    mime_type = get_mime_type(audio_path)

    print(
        f"[Gemini] audio upload: {audio_path}"
    )
    print(
        f"[Gemini] mime type: {mime_type}"
    )

    uploaded_file = None

    try:

        uploaded_file = client.files.upload(
            file=audio_path,
            config={
                "mime_type": mime_type
            }
        )

        print(
            f"[Gemini] uploaded file: {uploaded_file.name}"
        )

        prompt = f"""
당신은 전문 음악 채보 및 악보 편집 AI입니다.

첨부된 오디오 파일을 실제로 듣고 음악을 분석하십시오.

사용자가 입력한 정보:
- 제목: {title_hint}
- 아티스트: {artist_hint}

목표:
이 곡을 사람이 연주할 수 있는 악보 초안으로 변환합니다.

반드시 다음 항목을 분석하십시오.

1. 곡 제목
2. 아티스트
3. BPM
4. Key
5. 박자
6. 주요 코드
7. 곡의 구조
8. 가능한 범위의 가사
9. 보컬 멜로디
10. ABCjs에서 렌더링 가능한 ABC notation

중요한 원칙:

- 실제 오디오를 기준으로 분석하십시오.
- 알 수 없는 정보는 억지로 만들지 마십시오.
- 불확실한 경우 confidence와 notes에 명시하십시오.
- 코드 진행은 가능한 한 실제 반주를 기준으로 추정하십시오.
- 멜로디는 가능한 한 주 멜로디를 중심으로 작성하십시오.
- ABC notation은 ABCjs 6.x에서 렌더링할 수 있는 일반적인 ABC 형식을 사용하십시오.
- ABC notation 안에는 설명문을 넣지 마십시오.
- ABC notation은 반드시 X:1부터 시작하십시오.
- M:, L:, K: 헤더를 포함하십시오.
- 코드가 있는 경우 "C", "G", "Am" 같은 ABC chord annotation을 사용하십시오.
- 가사가 확실한 경우 w: 줄을 사용하십시오.
- 전체 곡을 가능한 한 많이 채보하십시오.
- 일부 구간이 불확실하더라도 분석을 중단하지 말고 가장 합리적인 초안을 작성하십시오.

ABC notation 예:

X:1
T:Song
M:4/4
L:1/4
K:G
"G" G2 B2 | "D" A2 F2 | "Em" E2 G2 | "C" c4 |
w: sample lyrics here

반드시 JSON 구조에 맞춰 응답하십시오.
"""

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                prompt,
                uploaded_file
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScoreResult,
            )
        )

        print("[Gemini] response received")

        if not response.text:
            raise RuntimeError(
                "Gemini가 빈 응답을 반환했습니다."
            )

        parsed = ScoreResult.model_validate_json(
            response.text
        )

        result = parsed.model_dump()

        result["abcNotation"] = clean_abc(
            result.get("abcNotation", ""),
            result.get("title") or title_hint or "AI 채보"
        )

        return result

    finally:

        # Gemini Files API에 업로드된 파일 삭제
        if uploaded_file is not None:

            try:
                client.files.delete(
                    name=uploaded_file.name
                )

                print(
                    f"[Gemini] deleted file: {uploaded_file.name}"
                )

            except Exception as delete_error:

                print(
                    "[Gemini] uploaded file cleanup failed:",
                    delete_error
                )


# =========================================================
# Health Check
# =========================================================

@app.route("/", methods=["GET", "HEAD"])
def health_check():

    return jsonify({
        "status": "ok",
        "service": "AI Song Sheet Server",
        "message": "AI 채보 서버 정상 작동 중",
        "model": GEMINI_MODEL,
        "gemini_configured": bool(GEMINI_API_KEY)
    })


@app.route("/api/health", methods=["GET"])
def api_health():

    return jsonify({
        "success": True,
        "status": "healthy",
        "gemini_configured": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL
    })


# =========================================================
# 실제 채보 API
# =========================================================

@app.route("/api/transcribe", methods=["POST"])
def transcribe():

    print("=" * 70)
    print("[API] POST /api/transcribe")
    print("=" * 70)

    temp_dir = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        youtube_url = (
            data.get("youtube_url") or ""
        ).strip()

        title_hint = (
            data.get("title") or ""
        ).strip()

        artist_hint = (
            data.get("artist") or ""
        ).strip()

        print(
            "[API] youtube_url:",
            youtube_url
        )

        print(
            "[API] title:",
            title_hint
        )

        if not youtube_url:

            return jsonify({
                "success": False,
                "message": "유튜브 URL이 누락되었습니다."
            }), 400

        if not is_youtube_url(
            youtube_url
        ):

            return jsonify({
                "success": False,
                "message": "YouTube URL만 입력할 수 있습니다."
            }), 400

        if not GEMINI_API_KEY:

            return jsonify({
                "success": False,
                "message": "Render에 GEMINI_API_KEY가 설정되어 있지 않습니다.",
                "detail": "Render Dashboard → Environment Variables에서 GEMINI_API_KEY를 추가하세요."
            }), 500

        # 임시 작업 폴더
        temp_dir = tempfile.mkdtemp(
            prefix="song_sheet_"
        )

        print(
            "[API] temp directory:",
            temp_dir
        )

        # -------------------------------------------------
        # 1. YouTube 오디오 다운로드
        # -------------------------------------------------

        print(
            "[API] downloading YouTube audio..."
        )

        download_result = download_youtube_audio(
            youtube_url,
            temp_dir
        )

        audio_path = download_result["path"]

        real_title = (
            title_hint
            or download_result["title"]
            or "유튜브 추출 곡"
        )

        real_artist = (
            artist_hint
            or download_result["artist"]
            or ""
        )

        print(
            "[API] downloaded:",
            audio_path
        )

        print(
            "[API] real title:",
            real_title
        )

        # -------------------------------------------------
        # 2. Gemini 음악 분석
        # -------------------------------------------------

        print(
            "[API] sending audio to Gemini..."
        )

        analysis = analyze_audio_with_gemini(
            audio_path,
            real_title,
            real_artist
        )

        # -------------------------------------------------
        # 3. 결과 보정
        # -------------------------------------------------

        if not analysis.get("title"):
            analysis["title"] = real_title

        if not analysis.get("artist"):
            analysis["artist"] = real_artist

        if not analysis.get("abcNotation"):
            analysis["abcNotation"] = (
                create_fallback_abc(
                    analysis["title"]
                )
            )

        print(
            "[API] analysis complete"
        )

        print(
            "[API] confidence:",
            analysis.get("confidence")
        )

        return jsonify({
            "success": True,
            "message": "AI 악보 분석이 완료되었습니다.",
            "data": analysis
        }), 200

    except Exception as e:

        print("=" * 70)
        print("[API ERROR]")
        print(str(e))
        print("=" * 70)

        traceback.print_exc()

        return jsonify({
            "success": False,
            "message": "AI 악보 분석 중 오류가 발생했습니다.",
            "detail": str(e)
        }), 500

    finally:

        # 임시 오디오 삭제
        if temp_dir:

            try:

                for file_path in glob.glob(
                    os.path.join(
                        temp_dir,
                        "*"
                    )
                ):

                    try:
                        os.remove(file_path)

                    except Exception:
                        pass

                try:
                    os.rmdir(temp_dir)

                except Exception:
                    pass

            except Exception:
                pass


# =========================================================
# 서버 실행
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
