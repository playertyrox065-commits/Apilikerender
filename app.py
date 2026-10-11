from flask import Flask, request, jsonify
import asyncio
import aiohttp
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from google.protobuf.json_format import MessageToJson
import binascii
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
import os
import random
import urllib3
from datetime import datetime, timedelta
import pytz
import threading
import time
import subprocess
from protobuf import my_message_pb2
from VsTeam import VsTeam
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
app = Flask(__name__)
ADMIN_ACCOUNT = "admin@080"

KEY_FILE = "VsKey.json"

VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
def token_update_loop():
    while True:
        try:
            print(f"[{datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')}]")
            result = subprocess.run(
                ["python3", "gettk.py"],
                capture_output=True,
                text=True
            )
            print(f"Hoàn Tất GetToken")
        except Exception as e:
            print(f"Lỗi GetToken: {e}")
        #time.sleep(4 * 60 * 60)
#threading.Thread(target=token_update_loop, daemon=True).start()
def load_keys():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_keys(data):
    with open(KEY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

keys_data = load_keys()
def is_admin(admin_param):
    return admin_param == ADMIN_ACCOUNT

def get_today_vn():
    today = datetime.now(VN_TZ).date()
    return today.strftime("%d/%m/%Y")

def reset_if_new_day(key_info):
    today = get_today_vn()
    if key_info.get("last_reset") != today:
        key_info["used_today"]   = 0 
        key_info["used_visits"]  = 0  
        key_info["last_reset"]   = today
        key_info.pop("used_likes", None)
        key_info.pop("used_today_old", None)
    return key_info
def load_tokens():
    file_path = "tokenlikes.txt"
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tokens = [line.strip() for line in f if line.strip()]
        if not tokens:
            return None
        return tokens
    except Exception as e:
        return None
def load_tokensview():
    file_path = "tokenlikes.txt"
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tokens = [line.strip() for line in f if line.strip()]
        if not tokens:
            return None
        return tokens
    except Exception as e:
        return None
def load_tokensviewlikes():
    file_path = "viewlikes.txt"
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tokens = [line.strip() for line in f if line.strip()]
        if not tokens:
            return None
        return tokens
    except Exception as e:
        return None
def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        return None
token_lock = threading.Lock()
def deltoken(token: str):
    file_path = "tokenlikes.txt"
    token = token.strip()
    if not token:
        return

    try:
        with token_lock:
            if not os.path.exists(file_path):
                return

            with open(file_path, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]

            if token not in lines or len(lines) <= 1:
                return

            lines.remove(token)

            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(l + "\n" for l in lines)

    except Exception:
        pass

async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.12f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                response_text = await response.text()
                if response.status != 200:
                    app.logger.warning(f"Trạng Thái: {response.status} - Token: {token[:20]}...")
                    print(await response.text())
                    if "BR_ACCOUNT_DAILY_LIKE_PROFILE_LIMIT" in response_text:
                        app.logger.info(f"Xóa token do đạt giới hạn ngày: {token[:20]}...")

                    return None
                if "BR_ACCOUNT_DAILY_LIKE_PROFILE_LIMIT" in response_text:
                    app.logger.info(f"Xóa token do đạt giới hạn ngày (status 200 nhưng lỗi): {token[:20]}...")
                    return None
                print(response_text)
                return response_text

    except Exception as e:
        app.logger.error(f"Exception in send_request (token: {token[:20]}...): {e}")
        return None

async def send_multiple_requests(uid, url):
    try:
        region = "BD"
        protobuf_message = create_protobuf_message(uid, region)
        if not protobuf_message:
            return None

        encrypted_uid = encrypt_message(protobuf_message)
        if not encrypted_uid:
            return None

        tokens = load_tokens()
        if not tokens:
            app.logger.error("Thất Bại Khi Load Token.")
            return None
        random.shuffle(tokens)
        target_likes = 360
        success_count = 0
        processed_index = 0
        
        while success_count < target_likes and processed_index < len(tokens):
            batch_size = 420
            if processed_index + batch_size > len(tokens):
                current_batch = tokens[processed_index:]
            else:
                current_batch = tokens[processed_index : processed_index + batch_size]

            tasks = [send_request(encrypted_uid, token, url) for token in current_batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            batch_success = sum(1 for r in results if r is not None and not isinstance(r, Exception))
            success_count += batch_success
            processed_index += len(current_batch)
            
            app.logger.info(f"Tiến độ: {success_count}/{target_likes} Likes (Đã thử {processed_index} token)")

            if success_count >= target_likes:
                break

        return success_count
    except Exception as e:
        app.logger.error(f"Báo Cáo Tmr Lỗi Khi Gửi Likes: {e}")
        return None
def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Báo Cáo Tmr Lỗi Khi Tạo UID Protobuf: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    return encrypt_message(protobuf_data) if protobuf_data else None
def make_request(encrypt):
    tokens = load_tokens()
    if not tokens: return None
    random.shuffle(tokens)
    for token in tokens:
        try:
            headers = {
                'Authorization': f'Bearer {token}',
                'User-Agent': "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
                'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
                'Content-Type': "application/x-www-form-urlencoded", 'Expect': "100-continue",
                'X-Unity-Version': "2018.4.12f1", 'X-GA': "v1 1", 'ReleaseVersion': "OB55"
            }
            r = requests.post("https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow", 
                              data=bytes.fromhex(encrypt), headers=headers, verify=False, timeout=10)
            if r.status_code == 200: return decode_protobuf(r.content)
        except Exception: continue
    return None

def get_request(encrypt):
    tokens = load_tokens()
    if not tokens: return None
    random.shuffle(tokens)
    for token in tokens:
        try:
            headers = {
                'Authorization': f'Bearer {token}',
                'User-Agent': "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
                'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
                'Content-Type': "application/x-www-form-urlencoded", 'Expect': "100-continue",
                'X-Unity-Version': "2018.4.12f1", 'X-GA': "v1 1", 'ReleaseVersion': "OB55"
            }
            r = requests.post("https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow", 
                              data=bytes.fromhex(encrypt), headers=headers, verify=False, timeout=10)
            if r.status_code == 200: 
                
                return VsTeam().parsed_results_to_dict(Parser().parse(r.content.hex()))
        except Exception: continue
    return None
def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"Lỗi Decode Protobuf: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Báo Cáo DucTri Lỗi Phần [decode_protobuf] Nha: {e}")
        return None
def calculate_remaining_days(expiry_str):
    try:
        expiry_date = datetime.strptime(expiry_str, "%d/%m/%Y").date()
        today = datetime.now().date()
        remaining = (expiry_date - today).days
        if remaining > 0:
            return f"{remaining} Days Left"
        elif remaining == 0:
            return "Expires Today"
        else:
            return f"Expired ({abs(remaining)} Days Ago)"
    except Exception:
        return "Invalid Expiry Date"
@app.route('/likes', methods=['GET'])
def handle_requests():
    try:
        uid = request.args.get("uid")
        key = request.args.get("key")

        if not uid:
            return app.response_class(
                response=json.dumps(
                    {"status": 3, "message": "Bro, please enter your UID!!"},
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 400

        if not uid.isdigit() or not (8 <= len(uid) <= 13):
            return app.response_class(
                response=json.dumps(
                    {"status": 3, "message": "Are you kidding me? The UID must contain between 8 and 13 digits!"},
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 400

        if not key:
            return app.response_class(
                response=json.dumps(
                    {"status": 3, "message": "Bro, please enter your KEY!!"},
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 400

        keys_data = load_keys()
        if key not in keys_data:
            return app.response_class(
                response=json.dumps(
                    {"status": 3, "message": "Bro, the key doesn’t exist or has expired!"},
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 403

        key_info = keys_data[key]
        key_info = reset_if_new_day(key_info)
        try:
            expiry_str = key_info["expiry"].strip()
            
            if '-' in expiry_str and len(expiry_str.split('-')[0]) == 4:
                expiry_date_obj = datetime.fromisoformat(expiry_str)
            else:
                expiry_date_obj = datetime.strptime(expiry_str, "%d/%m/%Y")
            
            expiry_date = expiry_date_obj.date()
            today_date = datetime.now(VN_TZ).date()
            if today_date > expiry_date:
                return app.response_class(
                    response=json.dumps(
                        {"status": 3, "message": f"Bro, your key has expired since {key_info['expiry']}..."},
                        ensure_ascii=False, indent=2
                    ),
                    mimetype="application/json"
                ), 403
        except:
            return app.response_class(
                response=json.dumps(
                    {"status": 3, "message": "Bro, your key is invalid or something went wrong!"},
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 500

        if key_info["used_today"] >= key_info["daily_limit"]:
            return app.response_class(
                response=json.dumps(
                    {
                        "status": 3,
                        "message": f"Bro has used up all your daily attempts! The key only allows {key_info['daily_limit']} tries per day. Please come back tomorrow!"
                    },
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 429
        tokens = load_tokens()

        check_token = random.choice(tokens)
        encrypted_uid = enc(uid)
        if not encrypted_uid:
            return app.response_class(
                response=json.dumps(
                    {
                        "status": 3, "error": "ENCRYPTER_UID",
                        "message": "Oh shit, an error occurred, please report it to DucTri immediately!!",
                        "telegram": "@ductri3667"
                    },
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 500
        before = make_request(encrypted_uid)
        if not before:
            return app.response_class(
                response=json.dumps(
                    {
                        "status": 3, "error": "BEFORE",
                        "message": "Oh shit, an error occurred, please report it to DucTri immediately!!",
                        "telegram": "@guncpw"
                    },
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 404
        data_before = json.loads(MessageToJson(before))
        before_like = int(data_before.get('AccountInfo', {}).get('Likes', 0))
        start = time.time()
        asyncio.run(send_multiple_requests(uid, "https://clientbp.ppmainecoonghj.com/LikeProfile"))
        end = time.time()
        after = make_request(encrypted_uid)
        if not after:
            return app.response_class(
                response=json.dumps(
                    {
                        "status": 3, "error": "AFTER",
                        "message": "Oh shit, an error occurred, please report it to DucTri immediately!!",
                        "telegram": "@ductri3667"
                    },
                    ensure_ascii=False, indent=2
                ),
                mimetype="application/json"
            ), 500
        data_after = json.loads(MessageToJson(after))
        resp = get_request(encrypted_uid)
        after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
        player_uid = int(data_after.get('AccountInfo', {}).get('UID', 0))
        player_name = str(data_after.get('AccountInfo', {}).get('PlayerNickname', ''))
        region_kv = str(resp.get(1, {}).get(5))
        level = str(resp.get(1, {}).get(6))
        like_given = after_like - before_like
        tts_like = f"{(end - start):.2f}"
        success = like_given > 0

        if success:
            key_info["used_today"] += 1
            keys_data[key] = key_info
            save_keys(keys_data)
        used = key_info["used_today"]
        limit = key_info["daily_limit"]
        expiry_raw = key_info["expiry"].strip().replace('-', '/')
        expiry_date_obj = datetime.strptime(expiry_raw, "%d/%m/%Y")
        expiry_str = expiry_date_obj.strftime("%d/%m/%Y")
        remaining_days = (expiry_date_obj.date() - datetime.now(VN_TZ).date()).days
        remaining_text = f"{remaining_days}" if remaining_days >= 0 else "Expired"
        tenkey = key_info.get("ten", "Anonymous")
        purchase_date = key_info.get("purchase_date", "Unknown")
        response_data = {
            "status": 0 if success else 1,
            "message": "Likes Sent Successfully" if success else f"Account with UID {player_uid} has reached the maximum likes for today. Please try again tomorrow.",
            "data": {
                "UID": player_uid,
                "Player Nickname": player_name,
                "Level": level,
                "Region": region_kv,
            },
            "info": {
                "Name": tenkey,
                "Used Turn": f"{used}/{limit}",
                "Purchase Date": purchase_date,
                "Expired Date": f"{expiry_str} ({remaining_text} Days Left)"
            }
        }

        if success:
            response_data["data"].update({
                "Time Sent": f"{tts_like} sec",
                "Likes Before Command": before_like,
                "Likes After Command": after_like,
                "Likes Given By API": like_given
            })
        else:
            response_data["data"]["Likes Before Command"] = before_like

        return app.response_class(
            response=json.dumps(
                response_data,
                ensure_ascii=False,
                indent=2
            ),
            mimetype="application/json"
        ), 200 if success else 429

    except Exception as e:
        app.logger.error(f"Báo Cáo Gun Có Lỗi: {e}")
        return app.response_class(
            response=json.dumps(
                {
                    "status": 3,
                    "error": "ALL",
                    "message": "Oh shit, an error occurred, please report it to ductri3667  immediately!!",
                    "telegram": "@ductri3667"
                },
                ensure_ascii=False,
                indent=2
            ),
            mimetype="application/json"
        ), 500

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=25695)