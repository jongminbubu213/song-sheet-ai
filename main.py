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

        # 유튜브 제목 추출
        real_title = title
        try:
            ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': True, 'socket_timeout': 5}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                if info and 'title' in info:
                    real_title = info['title']
        except Exception as yt_err:
            print(f"유튜브 추출 기본값 사용: {yt_err}")

        # 🎵 오선지, 박자, 마디, 코드, 멜로디, 가사가 결합된 ABC Notation 데이터
        abc_code = f"""
X:1
T:{real_title}
M:4/4
L:1/4
K:G
"G" G2 "D/F#" B2 | "Em" E2 "Bm" B2 | "C" c2 "G/B" e2 | "Am7" A2 "D7" d2 |
w: 주 님 을 바 라 보 는 자 마 다
"G" G B d g | "C" e d B G | "Am7" A2 "D7" F2 | "G" G4 |]
w: 새 힘 을 얻 으 리 라 주 님 안 에 -
"""

        return jsonify({
            "success": True,
            "data": {
                "title": real_title,
                "abcNotation": abc_code
            }
        }), 200

    except Exception as e:
        return jsonify({"success": False, "detail": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
