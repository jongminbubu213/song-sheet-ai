from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import os

app = Flask(__name__)
CORS(app)

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "AI 채보 서버 정상 작동 중"})

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    try:
        data = request.get_json(silent=True) or {}
        youtube_url = data.get('youtube_url', '')
        title = data.get('title', '유튜브 추출 곡')

        if not youtube_url:
            return jsonify({"success": False, "message": "URL이 누락되었습니다."}), 400

        # yt-dlp 타임아웃 및 차단 방지 최적화 옵션
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'extract_flat': True,       # 상세 분석 생략으로 속도 10배 향상
            'socket_timeout': 5,        # 5초 내 응답 없으면 바로 패스
        }
        
        real_title = title
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                if info and 'title' in info:
                    real_title = info['title']
        except Exception as yt_err:
            print(f"유튜브 추출 스킵 (기본 제목 사용): {yt_err}")

        # 악보 데이터 (Mock)
        mock_song_form = [
            {
                "section": "Verse 1",
                "measures": [
                    {"chords": ["G", "D/F#"], "notes": ["g/4", "b/4", "d/5", "b/4"], "lyrics": ["주", "님", "을", " 바라"]},
                    {"chords": ["Em", "Bm"], "notes": ["e/4", "g/4", "b/4", "g/4"], "lyrics": ["보는", " 자", "마다", " "]}
                ]
            },
            {
                "section": "Chorus (후렴)",
                "measures": [
                    {"chords": ["C", "G/B"], "notes": ["c/5", "e/5", "g/5", "e/5"], "lyrics": ["새", " 힘", "을", " 얻으"]},
                    {"chords": ["Am7", "D7"], "notes": ["a/4", "c/5", "f#/4", "a/4"], "lyrics": ["리", "라", " ", " "]}
                ]
            }
        ]

        return jsonify({
            "success": True,
            "data": {
                "title": real_title,
                "songForm": mock_song_form
            }
        }), 200

    except Exception as e:
        return jsonify({"success": False, "detail": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
