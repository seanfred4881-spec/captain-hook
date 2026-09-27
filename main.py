
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Captain Hook Bot is LIVE!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print(data)
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
