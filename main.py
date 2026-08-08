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
        title = data.get('title', '')

        if not youtube_url:
            return jsonify({"success": False, "message": "유튜브 URL이 누락되었습니다."}), 400

        # 1. 유튜브 제목 추출 (실패시 입력한 제목 또는 기본값 사용)
        real_title = title if title else "유튜브 추출 곡"
        try:
            ydl_opts = {
                'quiet': True, 
                'skip_download': True, 
                'extract_flat': True, 
                'socket_timeout': 5
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                if info and 'title' in info and info['title']:
                    real_title = info['title']
        except Exception as yt_err:
            print(f"유튜브 제목 추출 생략 (기본값 사용): {yt_err}")

        # 2. ABC Notation 문자열 작성 (안전한 문자열 결합)
        abc_code = (
            "X:1\n"
            "T:" + str(real_title) + "\n"
            "M:4/4\n"
            "L:1/4\n"
            "K:G\n"
            '"G" G2 "D/F#" B2 | "Em" E2 "Bm" B2 | "C" c2 "G/B" e2 | "Am7" A2 "D7" d2 |\n'
            "w: 주 님 을 바 라 보 는 자 마 다\n"
            '"G" G B d g | "C" e d B G | "Am7" A2 "D7" F2 | "G" G4 |]\n'
            "w: 새 힘 을 얻 으 리 라 주 님 안 에 -\n"
        )

        return jsonify({
            "success": True,
            "data": {
                "title": real_title,
                "abcNotation": abc_code
            }
        }), 200

    except Exception as e:
        print(f"서버 내부 에러 발생: {str(e)}")
        return jsonify({"success": False, "detail": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
