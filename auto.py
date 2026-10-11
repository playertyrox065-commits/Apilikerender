import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from flask import Flask, request, jsonify
import asyncio
import threading
import time
import json
import os
import binascii
import random
import urllib.parse
import jwt
import warnings
from datetime import datetime, timezone, timedelta, time as dtime
from collections import defaultdict

import requests
import aiohttp
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad as aes_pad
from google.protobuf.json_format import MessageToJson
from urllib3.exceptions import InsecureRequestWarning

import like_pb2
import like_count_pb2
import uid_generator_pb2

BOT_TOKEN = "8917310231:AAEmCLz56dM0DbPF5SORTAl0ydMSb_sw3Sc"
AUTO_FILE = "auto_like.json"
GROUPS_FILE = "allowed_groups.json"
LIMIT_FILE = "like_limit.json"
USER_USAGE_FILE = "user_usage.json"
LOCK_FILE = "bot_lock_state.json"
ADMINS_FILE = "admins.json"
TOKEN_FILE = "token.json"

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'
VALID_REGIONS = {"IND", "BR", "US", "SAC", "NA", "SG", "BD", "TH", "ID", "MY", "PK", "VN", "TW", "RU", "CIS"}
VN_TZ = timezone(timedelta(hours=7))
AUTO_LIKE_HOUR = 5
AUTO_LIKE_MINUTE = 5
DEFAULT_ADMIN_IDS = {8830951108}
ADMIN_IDS = set(DEFAULT_ADMIN_IDS)

_global_like_usage = {"date": "", "count": 0}
TOKEN_CACHE = {}
liked_cache = defaultdict(set)
user_usage = {}
IS_BOT_MANUALLY_LOCKED = False

GROUP_ID = -1004312899731
CHANNEL_ID = -1004414491085

GROUP_LINK = "https://t.me/pwchat2"
GROUPP_LINK = "https://t.me/tyro03"
CHANNEL_LINK = "https://t.me/tyrox36sex"
ADMIN_CONTACT = "@nhansinh36"
VERIFY_CALLBACK = "verify_join"

telebot.apihelper.ENABLE_MIDDLEWARE = True

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)
warnings.filterwarnings("ignore", category=InsecureRequestWarning)


def load_admins():
    global ADMIN_IDS
    if os.path.exists(ADMINS_FILE):
        try:
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                ADMIN_IDS = set(data) | DEFAULT_ADMIN_IDS
        except:
            ADMIN_IDS = set(DEFAULT_ADMIN_IDS)
    else:
        ADMIN_IDS = set(DEFAULT_ADMIN_IDS)
        save_admins()

def save_admins():
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ADMIN_IDS), f, indent=2)


def load_lock_state():
    global IS_BOT_MANUALLY_LOCKED
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                IS_BOT_MANUALLY_LOCKED = data.get("locked", False)
        except:
            IS_BOT_MANUALLY_LOCKED = False

def save_lock_state():
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump({"locked": IS_BOT_MANUALLY_LOCKED}, f, indent=2)


def load_user_usage():
    global user_usage
    if os.path.exists(USER_USAGE_FILE):
        try:
            with open(USER_USAGE_FILE, "r", encoding="utf-8") as f:
                user_usage = json.load(f)
        except:
            user_usage = {}
    else:
        user_usage = {}

def save_user_usage():
    with open(USER_USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(user_usage, f, indent=2, ensure_ascii=False)


def check_join(user_id: int) -> bool:
    try:
        g = bot.get_chat_member(GROUP_ID, user_id)
        c = bot.get_chat_member(CHANNEL_ID, user_id)
        ok = ["member", "administrator", "creator"]
        return g.status in ok and c.status in ok
    except:
        return False

def build_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("👥 Tham gia nhóm", url=GROUP_LINK),
        InlineKeyboardButton("📢 Tham gia nhóm", url=GROUPP_LINK),
        InlineKeyboardButton("📢 Tham gia kênh", url=CHANNEL_LINK),
        InlineKeyboardButton("✅ Tôi đã tham gia", callback_data=VERIFY_CALLBACK)
    )
    return markup


def _load_allowed_groups() -> set:
    if not os.path.exists(GROUPS_FILE):
        return set()
    try:
        with open(GROUPS_FILE, "r") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except:
        return set()

def _save_allowed_groups(groups: set):
    with open(GROUPS_FILE, "w") as f:
        json.dump(list(groups), f, indent=2)

def _is_allowed_chat(msg: Message) -> bool:
    if msg.from_user and msg.from_user.id in ADMIN_IDS:
        return True
    if msg.chat.type == "private":
        return True
    allowed = _load_allowed_groups()
    return msg.chat.id in allowed


def _get_daily_limit() -> int:
    if not os.path.exists(LIMIT_FILE):
        return 2
    try:
        with open(LIMIT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("daily_limit", 2)
    except:
        return 2

def _set_daily_limit(limit_number: int):
    with open(LIMIT_FILE, "w", encoding="utf-8") as f:
        json.dump({"daily_limit": limit_number}, f, indent=2)

def _check_like_limit(user_id: int) -> tuple:
    if user_id in ADMIN_IDS:
        return True, -1
    daily_limit = _get_daily_limit()
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    uid_str = str(user_id)
    if uid_str not in user_usage or user_usage[uid_str].get("date") != today:
        user_usage[uid_str] = {"date": today, "count": 0}
        save_user_usage()
    used = user_usage[uid_str]["count"]
    remaining = daily_limit - used
    return remaining > 0, remaining

def _increment_like_usage(user_id: int):
    if user_id in ADMIN_IDS:
        return
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    uid_str = str(user_id)
    if uid_str not in user_usage or user_usage[uid_str].get("date") != today:
        user_usage[uid_str] = {"date": today, "count": 0}
    user_usage[uid_str]["count"] += 1
    save_user_usage()


def is_bot_locked_time() -> bool:
    now_time = datetime.now(VN_TZ).time()
    start_lock = dtime(4, 50)
    end_lock = dtime(6, 0)
    return start_lock <= now_time < end_lock

@bot.middleware_handler(update_types=['message'])
def global_bot_guard(bot_instance, message: Message):
    if IS_BOT_MANUALLY_LOCKED or is_bot_locked_time():
        if message.from_user and message.from_user.id in ADMIN_IDS:
            return
        if message.text and message.text.startswith('/'):
            markup = InlineKeyboardMarkup()
            btn_vip = InlineKeyboardButton(text="💎 Mua Vip", url="https://t.me/nhansinh36")
            markup.add(btn_vip)
            msg_txt = "⏳ <b>Hệ thống đang tạm khóa!</b> Vui lòng quay lại sau hoặc liên hệ Admin để nâng cấp VIP." if IS_BOT_MANUALLY_LOCKED else \
                      "⏳ <b>Hệ thống đang tạm khóa từ 04:50 đến 06:00</b> để thực hiện tiến trình Auto Buff Like daily.\nVui lòng quay lại sau 6h00 hoặc mua gói VIP để không bị gián đoạn!"
            try:
                bot.send_message(
                    message.chat.id,
                    msg_txt,
                    reply_markup=markup,
                    parse_mode="HTML"
                )
            except:
                pass
            return False


@bot.my_chat_member_handler()
def bot_added_to_group(event: ChatMemberUpdated):
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
        chat_id = event.chat.id
        allowed = _load_allowed_groups()
        if chat_id not in allowed:
            try:
                bot.send_message(
                    chat_id,
                    "⚠️ <b>CẢNH BÁO: Bot chưa được phép hoạt động tại nhóm này!</b>\n\n"
                    "🔒 Tất cả các lệnh đã bị vô hiệu hóa.\n"
                    "👉 Vui lòng liên hệ Admin <b>@nhansinh36</b> để cấp quyền sử dụng.",
                    parse_mode="HTML"
                )
            except:
                pass


def auto_load() -> dict:
    if not os.path.exists(AUTO_FILE): return {}
    try:
        with open(AUTO_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except:
        return {}

def auto_save(data: dict):
    tmp = AUTO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, AUTO_FILE)

def auto_add(uid: str, region: str, chat_id: int, mode: str = "forever", target_value: int = 0):
    data = auto_load()
    data[uid] = {
        "region": region.upper(),
        "chat_id": chat_id,
        "mode": mode,
        "target_value": target_value,
        "created_at": datetime.now(VN_TZ).strftime("%Y-%m-%d")
    }
    auto_save(data)

def auto_remove(uid: str) -> bool:
    data = auto_load()
    if uid in data:
        del data[uid]
        auto_save(data)
        return True
    return False

def auto_list_for_chat(chat_id: int) -> list:
    data = auto_load()
    return [(uid, v) for uid, v in data.items() if v.get("chat_id") == chat_id or chat_id in ADMIN_IDS]


def load_accounts():
    target_files = ["account_vn.txt", "account_bd.txt", "acc.json", "accc.json"]
    accounts_dict = {}
    for filename in target_files:
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if not content:
                    continue
                data = json.loads(content)
                if isinstance(data, dict):
                    if "rows" in data and isinstance(data["rows"], list):
                        for item in data["rows"]:
                            if isinstance(item, dict):
                                u_id = item.get("login_uid") or item.get("uid")
                                pwd = item.get("password")
                                if u_id and pwd:
                                    accounts_dict[str(u_id)] = str(pwd)
                    else:
                        for u_id, pwd in data.items():
                            if u_id != "rows" and pwd:
                                accounts_dict[str(u_id)] = str(pwd)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            u_id = item.get("login_uid") or item.get("uid")
                            pwd = item.get("password")
                            if u_id and pwd:
                                accounts_dict[str(u_id)] = str(pwd)
            except Exception:
                pass
    accounts = [{"uid": u, "password": p} for u, p in accounts_dict.items()]
    return accounts


def load_token_cache():
    global TOKEN_CACHE
    if not os.path.exists(TOKEN_FILE):
        return
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, entry in data.items():
            TOKEN_CACHE[uid] = {
                "token": entry["token"],
                "expires_at": datetime.fromisoformat(entry["expires_at"])
            }
    except:
        pass

def save_token_cache():
    try:
        data = {}
        for uid, entry in TOKEN_CACHE.items():
            data[uid] = {
                "token": entry["token"],
                "expires_at": entry["expires_at"].isoformat()
            }
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except:
        pass


async def generate_jwt_token(u_id, pwd):
    try:
        encoded_password = urllib.parse.quote(str(pwd))
        url = f"https://ff-jwt-gen-api.lovable.app/api/public/token?uid={u_id}&password={encoded_password}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict):
                        return data.get('jwt_token') or data.get('token')
                return None
    except:
        return None

async def get_valid_token(u_id, pwd):
    if u_id in TOKEN_CACHE:
        cached = TOKEN_CACHE[u_id]
        if (cached["expires_at"] - datetime.utcnow()).total_seconds() > 1800:
            return cached["token"]
    jwt_token = await generate_jwt_token(u_id, pwd)
    if not jwt_token:
        return None
    try:
        payload = jwt.decode(jwt_token, options={"verify_signature": False})
        exp = payload.get("exp")
        TOKEN_CACHE[u_id] = {"token": jwt_token, "expires_at": datetime.utcfromtimestamp(exp)}
    except:
        TOKEN_CACHE[u_id] = {"token": jwt_token, "expires_at": datetime.utcnow() + timedelta(hours=5)}
    save_token_cache()
    return jwt_token


def encrypt_message(plaintext):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(aes_pad(plaintext, AES.block_size))).decode('utf-8')

def enc(u_id):
    message = uid_generator_pb2.uid_generator()
    message.krishna_ = int(u_id)
    message.teamXdarks = 1
    return encrypt_message(message.SerializeToString())

def create_protobuf_message(user_id, region):
    message = like_pb2.like()
    message.uid = int(user_id)
    message.region = region
    return message.SerializeToString()

async def send_like(encrypted_uid, jwt_token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Authorization': f"Bearer {jwt_token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers, timeout=3) as response:
                return response.status
    except:
        return 500

async def process_account(target_uid, encrypted_uid, account, url, semaphore):
    async with semaphore:
        jwt_token = await get_valid_token(account['uid'], account['password'])
        if not jwt_token:
            return 500, account['uid']
        status = await send_like(encrypted_uid, jwt_token, url)
        if status == 200:
            liked_cache[target_uid].add(account['uid'])
        return status, account['uid']

async def send_all_likes(target_uid, server_name, url):
    protobuf_message = create_protobuf_message(target_uid, server_name)
    encrypted_uid = encrypt_message(protobuf_message)
    accounts = load_accounts()
    total_accs = len(accounts)
    if not accounts:
        return {'success': 0, 'total': 0}
    already_liked = liked_cache.get(target_uid, set())
    fresh_accounts = [acc for acc in accounts if acc['uid'] not in already_liked]
    if not fresh_accounts:
        fresh_accounts = accounts
    random.shuffle(fresh_accounts)
    semaphore = asyncio.Semaphore(120)
    tasks = [process_account(target_uid, encrypted_uid, acc, url, semaphore) for acc in fresh_accounts]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for r in results if isinstance(r, tuple) and r[0] == 200)
    return {'success': successful, 'total': total_accs}

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except:
        return None

def get_player_info(encrypted_uid, server_name, jwt_token):
    if server_name == "IND":
        url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
    edata = bytes.fromhex(encrypted_uid)
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {jwt_token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB55"
    }
    try:
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=6)
        return decode_protobuf(response.content)
    except:
        return None

def do_like_process(uid: str, region: str) -> dict:
    accounts = load_accounts()
    if not accounts:
        return {"error": "no_accounts_found"}
    check_token = None
    for acc in accounts[:15]:
        t = asyncio.run(get_valid_token(acc['uid'], acc['password']))
        if t:
            check_token = t
            break
    if not check_token:
        return {"error": "token_generation_failed"}
    encrypted_uid = enc(uid)
    before = get_player_info(encrypted_uid, region, check_token)
    if not before:
        return {"error": "fetch_before_failed"}
    try:
        before_data = json.loads(MessageToJson(before))
        before_like = int(before_data.get('AccountInfo', {}).get('Likes', 0))
        nickname = before_data.get('AccountInfo', {}).get('PlayerNickname', 'Unknown')
        real_uid = before_data.get('AccountInfo', {}).get('UID', uid)
    except:
        return {"error": "parse_data_failed"}
    if region == "IND":
        like_url = "https://client.ind.freefiremobile.com/LikeProfile"
    elif region in {"BR", "US", "SAC", "NA"}:
        like_url = "https://client.us.freefiremobile.com/LikeProfile"
    else:
        like_url = "https://clientbp.ggpolarbear.com/LikeProfile"
    res_like = asyncio.run(send_all_likes(uid, region, like_url))
    after = get_player_info(encrypted_uid, region, check_token)
    if not after:
        return {"error": "fetch_after_failed"}
    try:
        after_data = json.loads(MessageToJson(after))
        after_like = int(after_data.get('AccountInfo', {}).get('Likes', 0))
        like_given = after_like - before_like
    except:
        like_given = 0
        after_like = before_like
    return {
        "nickname": nickname,
        "uid": real_uid,
        "before": before_like,
        "after": after_like,
        "added": like_given,
        "status": 1 if like_given > 0 else 2,
        "total_accounts": res_like['total']
    }


def auto_like_scheduler():
    print(f"🕐 Auto-like scheduler khởi động ({AUTO_LIKE_HOUR:02}:{AUTO_LIKE_MINUTE:02} AM VN mỗi ngày)")
    while True:
        try:
            now = datetime.now(VN_TZ)
            target = now.replace(hour=AUTO_LIKE_HOUR, minute=AUTO_LIKE_MINUTE, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait_sec = (target - now).total_seconds()
            time.sleep(wait_sec)
            data = auto_load()
            if not data:
                continue
            for uid, info in list(data.items()):
                region = info.get("region", "BD")
                chat_id = info.get("chat_id")
                mode = info.get("mode", "forever")
                target_val = info.get("target_value", 0)
                try:
                    result = do_like_process(uid, region)
                    if "error" not in result:
                        current_likes = result['after']
                        should_remove = False
                        msg_suffix = ""
                        if mode == "days":
                            target_val -= 1
                            if target_val <= 0:
                                should_remove = True
                                msg_suffix = "\n⚠️ <i>Đã hoàn thành đủ số ngày cài đặt, tự động gỡ UID khỏi Auto.</i>"
                            else:
                                data[uid]["target_value"] = target_val
                                auto_save(data)
                        elif mode == "likes":
                            if current_likes >= target_val:
                                should_remove = True
                                msg_suffix = f"\n⚠️ <i>Đã đạt đủ mốc {target_val:,} likes, tự động gỡ UID khỏi Auto.</i>"
                        if should_remove:
                            auto_remove(uid)
                        if chat_id:
                            bot.send_message(
                                chat_id,
                                f"✅ <b>Auto Buff Like 5:00 AM Thành Công!</b>\n"
                                f"<blockquote>"
                                f"👤 <b>Player:</b> {result['nickname']}\n"
                                f"🆔 <b>UID:</b> <code>{result['uid']}</code>\n"
                                f"📦 <b>Tổng số acc đã chạy:</b> <i>{result['total_accounts']:,} accs</i>\n"
                                f"📉 <b>Before:</b> <i>{result['before']:,}</i>\n"
                                f"📈 <b>After:</b> <i>{result['after']:,}</i>\n"
                                f"♥️ <b>Added:</b> <i>+{result['added']} like</i>"
                                f"{msg_suffix}"
                                f"</blockquote>",
                                parse_mode="HTML"
                            )
                except Exception:
                    pass
                time.sleep(2)
        except Exception:
            time.sleep(60)


def broadcast_promo_scheduler():
    promo_text = (
        "📢 <b>THÔNG BÁO DỊCH VỤ BUFF LIKE FREE FIRE</b> 📢\n\n"
        "• Auto like ff đến hết ob : <b>50k</b> (ngày 200-220like)\n"
        "• Auto like ff Vĩnh viễn : <b>130k</b> (ngày 200-220like)\n\n"
        "👉 Bấm vào nút bên dưới để liên hệ Admin ngay!"
    )
    markup = InlineKeyboardMarkup()
    btn_vip = InlineKeyboardButton(text="💎 Mua Vip", url="https://t.me/nhansinh36")
    markup.add(btn_vip)
    while True:
        time.sleep(1200)
        try:
            allowed_groups = _load_allowed_groups()
            for chat_id in allowed_groups:
                try:
                    bot.send_message(chat_id, promo_text, reply_markup=markup, parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            pass


@bot.message_handler(content_types=['new_chat_members'])
def welcome_new_member(msg: Message):
    if not _is_allowed_chat(msg):
        return
    for new_user in msg.new_chat_members:
        full_name = new_user.first_name
        if new_user.last_name:
            full_name += f" {new_user.last_name}"
        username_str = f"@{new_user.username}" if new_user.username else "Không có"
        welcome_text = (
            f"Xin chào: {full_name} ✅\n"
            f" 🆔ID: <code>{new_user.id}</code>\n"
            f"   ☑️\n"
            f"😀 Username: {username_str}\n\n"
            f"👩‍💻   🤔 Dùng lệnh /menu để xem danh sách lệnh nhé. 📢"
        )
        markup = InlineKeyboardMarkup()
        btn_vip = InlineKeyboardButton(text="💎 Mua Vip", url="https://t.me/nhansinh36")
        markup.add(btn_vip)
        bot.send_message(msg.chat.id, welcome_text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(content_types=['left_chat_member'])
def goodbye_member(msg: Message):
    if not _is_allowed_chat(msg):
        return
    left_user = msg.left_chat_member
    full_name = left_user.first_name
    if left_user.last_name:
        full_name += f" {left_user.last_name}"
    bot.send_message(
        msg.chat.id,
        f"👋 Thành viên <b>{full_name}</b> (<code>{left_user.id}</code>) đã rời khỏi nhóm!"
    )


@bot.callback_query_handler(func=lambda call: call.data == VERIFY_CALLBACK)
def cb_verify_join(call):
    if check_join(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Xác nhận thành công! Dùng /menu để bắt đầu.")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
    else:
        bot.answer_callback_query(call.id, "❌ Bạn chưa tham gia đủ nhóm và kênh!", show_alert=True)


@bot.message_handler(commands=["menu"])
def cmd_menu(msg: Message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 Lệnh", callback_data="menu_commands"),
        InlineKeyboardButton("👤 Thông tin", callback_data="menu_myinfo"),
        InlineKeyboardButton("🔗 Mời bạn bè", callback_data="menu_refer"),
    )
    bot.reply_to(
        msg,
        "🎛 <b>MENU CHÍNH</b>\nChọn chức năng bên dưới:",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == "menu_commands")
def cb_menu_commands(call):
    text = (
        "📋 <b>DANH SÁCH LỆNH</b>\n\n"
        "• <code>/like &lt;UID&gt; [Region]</code> - Buff like\n"
        "• <code>/myid</code> - Xem ID\n"
        "• <code>/menu</code> - Menu chính\n"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "menu_myinfo")
def cb_menu_myinfo(call):
    u = call.from_user
    text = (
        f"👤 <b>THÔNG TIN CỦA BẠN</b>\n\n"
        f"• Tên: <b>{u.first_name or ''} {u.last_name or ''}</b>\n"
        f"• Username: @{u.username if u.username else 'Không có'}\n"
        f"• User ID: <code>{u.id}</code>\n"
        f"• Chat ID: <code>{call.message.chat.id}</code>"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "menu_refer")
def cb_menu_refer(call):
    bot_username = bot.get_me().username
    link = f"https://t.me/{bot_username}?start=ref_{call.from_user.id}"
    text = (
        f"🔗 <b>MỜI BẠN BÈ</b>\n\n"
        f"Link mời của bạn:\n<code>{link}</code>"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode="HTML")


@bot.message_handler(commands=["addmin", "addadmin"])
def cmd_add_admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split()
    target_id = None
    if len(parts) >= 2 and parts[1].isdigit():
        target_id = int(parts[1])
    elif msg.reply_to_message and msg.reply_to_message.from_user:
        target_id = msg.reply_to_message.from_user.id

    if not target_id:
        bot.reply_to(msg, "⚠️ <b>Cú pháp không hợp lệ!</b>\n• Cú pháp: <code>/addmin &lt;User_ID&gt;</code> hoặc reply tin nhắn của người cần thêm.")
        return

    if target_id in ADMIN_IDS:
        bot.reply_to(msg, f"⚠️ User <code>{target_id}</code> đã là Admin từ trước.")
        return

    ADMIN_IDS.add(target_id)
    save_admins()
    bot.reply_to(
        msg,
        f"✅ <b>Thêm Admin thành công!</b>\n"
        f"User ID <code>{target_id}</code> hiện đã có toàn quyền sử dụng tất cả các lệnh Admin."
    )

@bot.message_handler(commands=["deladmin"])
def cmd_del_admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split()
    target_id = None
    if len(parts) >= 2 and parts[1].isdigit():
        target_id = int(parts[1])
    elif msg.reply_to_message and msg.reply_to_message.from_user:
        target_id = msg.reply_to_message.from_user.id

    if not target_id:
        bot.reply_to(msg, "⚠️ <b>Cú pháp không hợp lệ!</b>\n• Cú pháp: <code>/deladmin &lt;User_ID&gt;</code> hoặc reply tin nhắn của người cần xóa.")
        return

    if target_id in DEFAULT_ADMIN_IDS:
        bot.reply_to(msg, "❌ Không thể xóa Admin hệ thống mặc định!")
        return

    if target_id not in ADMIN_IDS:
        bot.reply_to(msg, f"⚠️ User <code>{target_id}</code> không có trong danh sách Admin.")
        return

    ADMIN_IDS.remove(target_id)
    save_admins()
    bot.reply_to(msg, f"🗑 <b>Đã hạ quyền Admin của User ID:</b> <code>{target_id}</code>.")

@bot.message_handler(commands=["listadmin"])
def cmd_list_admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    lines = [f"• <code>{aid}</code>" + (" (Mặc định)" if aid in DEFAULT_ADMIN_IDS else "") for aid in ADMIN_IDS]
    bot.reply_to(msg, f"👑 <b>DANH SÁCH ADMIN ({len(ADMIN_IDS)}):</b>\n\n" + "\n".join(lines), parse_mode="HTML")


@bot.message_handler(commands=["khoa"])
def cmd_lock_bot(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    global IS_BOT_MANUALLY_LOCKED
    IS_BOT_MANUALLY_LOCKED = True
    save_lock_state()
    bot.reply_to(msg, "🔒 <b>Đã khóa Bot thành công!</b>\nChỉ Admin mới có thể tiếp tục thao tác lệnh.")

@bot.message_handler(commands=["mobot"])
def cmd_unlock_bot(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    global IS_BOT_MANUALLY_LOCKED
    IS_BOT_MANUALLY_LOCKED = False
    save_lock_state()
    bot.reply_to(msg, "🔓 <b>Đã mở khóa Bot thành công!</b>\nTất cả người dùng có thể sử dụng lại bình thường.")


@bot.message_handler(commands=["on"])
def cmd_on(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    if msg.chat.type == "private":
        bot.reply_to(msg, "❌ Lệnh này chỉ dùng trong nhóm!")
        return
    groups = _load_allowed_groups()
    groups.add(msg.chat.id)
    _save_allowed_groups(groups)
    bot.reply_to(msg, f"✅ <b>Đã cấp quyền thành công cho nhóm này!</b>\nChat ID: <code>{msg.chat.id}</code>")

@bot.message_handler(commands=["off"])
def cmd_off(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    if msg.chat.type == "private":
        bot.reply_to(msg, "❌ Lệnh này chỉ dùng trong nhóm!")
        return
    groups = _load_allowed_groups()
    if msg.chat.id in groups:
        groups.remove(msg.chat.id)
        _save_allowed_groups(groups)
        bot.reply_to(msg, f"🚫 <b>Đã tước quyền sử dụng bot của nhóm này!</b>")
    else:
        bot.reply_to(msg, "⚠️ Nhóm này chưa được cấp quyền trước đó.")

@bot.message_handler(commands=["setlimit"])
def cmd_set_limit(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        current_limit = _get_daily_limit()
        bot.reply_to(
            msg,
            f"⚠️ <b>Cú pháp không hợp lệ!</b>\n"
            f"• Cú pháp: <code>/setlimit &lt;số_lần&gt;</code>\n"
            f"• Giới hạn hiện tại: <b>{current_limit}</b> lần/ngày"
        )
        return
    new_limit = int(parts[1])
    _set_daily_limit(new_limit)
    bot.reply_to(
        msg,
        f"⚙️ <b>Cập nhật giới hạn thành công!</b>\n"
        f"Số lần user được buff tối đa mỗi ngày: <b>{new_limit} lần</b>."
    )

@bot.message_handler(commands=["tb"])
def cmd_tb(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(msg, "⚠️ Cú pháp: <code>/tb [nội dung thông báo]</code>")
        return
    notice_text = parts[1]
    groups = _load_allowed_groups()
    success = 0
    failed = 0
    for gid in groups:
        try:
            bot.send_message(gid, f"📢 <b>THÔNG BÁO TỪ ADMIN</b>\n\n{notice_text}")
            success += 1
        except:
            failed += 1
    bot.reply_to(msg, f"✅ <b>Gửi thông báo hoàn tất!</b>\n• Thành công: {success} nhóm\n• Thất bại: {failed} nhóm")


@bot.message_handler(commands=["like"])
def cmd_like(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        if not check_join(msg.from_user.id):
            first_name = msg.from_user.first_name or "bạn"
            bot.reply_to(
                msg,
                f"👋 <b>Chào {first_name}!</b>\n\n"
                f"❌ <b>Bạn phải tham gia nhóm và kênh để sử dụng bot!</b>\n\n"
                f"🔗 <b>Yêu cầu:</b>\n"
                f" • Tham gia nhóm: <a href='{GROUP_LINK}'>Bấm vào đây</a>\n"
                f" • Tham gia nhóm: <a href='{GROUPP_LINK}'>Bấm vào đây</a>\n"
                f" • Tham gia kênh: <a href='{CHANNEL_LINK}'>Bấm vào đây</a>\n"
                f"✅ Sau khi tham gia, bấm nút <b>Tôi đã tham gia</b> để xác nhận.\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📞 <b>Liên hệ admin:</b> {ADMIN_CONTACT}",
                reply_markup=build_join_markup(),
                disable_web_page_preview=True
            )
            return

    can_use, remaining = _check_like_limit(msg.from_user.id)
    if not can_use:
        bot.reply_to(msg, f"❌ Bạn đã hết lượt buff trong ngày hôm nay! Hạn mức: {_get_daily_limit()} lần/ngày.")
        return

    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(msg, "⚠️ <b>Thiếu UID!</b>\nCú pháp: <code>/like UID [Region]</code>")
        return

    uid = parts[1].strip()
    region = parts[2].strip().upper() if len(parts) > 2 else "BD"

    if not uid.isdigit() or region not in VALID_REGIONS:
        bot.reply_to(msg, "❌ UID hoặc Region không hợp lệ!")
        return

    total_accs_preview = len(load_accounts())
    wait_msg = bot.reply_to(msg, f"⏳ <i>Đang quét và tối ưu tốc độ chạy <b>{total_accs_preview:,}</b> tài khoản cho UID <code>{uid}</code>...</i>")

    def process():
        result = do_like_process(uid, region)
        try:
            bot.delete_message(msg.chat.id, wait_msg.message_id)
        except:
            pass
        if "error" in result:
            bot.reply_to(msg, f"❌ <b>Lỗi:</b> {result['error']}")
            return
        _increment_like_usage(msg.from_user.id)
        can_use2, remaining2 = _check_like_limit(msg.from_user.id)
        remain_txt = f"\n🔋 <b>Lượt còn lại hôm nay:</b> <i>{remaining2 if remaining2 >= 0 else '∞'}</i>"
        bot.reply_to(
            msg,
            f"✅ <b>Đã chạy xong tất cả tài khoản!</b>\n"
            f"👤 <b>Player:</b> {result['nickname']}\n"
            f"🆔 <b>UID:</b> <code>{result['uid']}</code>\n"
            f"📦 <b>Tổng số acc đã chạy:</b> <i>{result['total_accounts']:,} accs</i>\n"
            f"📉 <b>Before:</b> <i>{result['before']:,}</i>\n"
            f"📈 <b>After:</b> <i>{result['after']:,}</i>\n"
            f"♥️ <b>Added (Thực tế tăng):</b> <i>+{result['added']} like</i>"
            f"{remain_txt}"
        )
    threading.Thread(target=process, daemon=True).start()


@bot.message_handler(commands=["auto"])
def cmd_auto(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(
            msg,
            "⚠️ <b>Cú pháp sử dụng lệnh Auto:</b>\n"
            "• <code>/auto ID</code> (Buff vĩnh viễn)\n"
            "• <code>/auto ID số_ngày</code> (Buff theo ngày, hết ngày tự xóa)\n"
            "• <code>/auto ID số_like</code> (Buff theo mốc like, đủ like tự xóa, ví dụ 10000)"
        )
        return
    uid = parts[1].strip()
    if not uid.isdigit():
        bot.reply_to(msg, "❌ UID không hợp lệ!")
        return
    mode = "forever"
    target_value = 0
    region = "BD"
    if len(parts) >= 3:
        param = parts[2].strip()
        if param.isdigit():
            val = int(param)
            if val <= 365:
                mode = "days"
                target_value = val
            else:
                mode = "likes"
                target_value = val
    auto_add(uid, region, msg.chat.id, mode=mode, target_value=target_value)
    if mode == "forever":
        info_txt = "Vĩnh viễn"
    elif mode == "days":
        info_txt = f"{target_value} ngày"
    else:
        info_txt = f"Đạt mốc {target_value:,} likes"
    bot.reply_to(
        msg,
        f"✅ <b>Đã đăng ký Auto Buff Like thành công!</b>\n"
        f"<blockquote>"
        f"🆔 <b>UID:</b> <code>{uid}</code>\n"
        f"⏳ <b>Chế độ:</b> <i>{info_txt}</i>\n"
        f"⏰ <b>Thời gian chạy:</b> <i>5:00 AM mỗi ngày</i>\n"
        f"</blockquote>"
    )

@bot.message_handler(commands=["stopauto"])
def cmd_stop_auto(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(msg, "⚠️ Cú pháp: <code>/stopauto &lt;UID&gt;</code>")
        return
    uid = parts[1].strip()
    if auto_remove(uid):
        bot.reply_to(msg, f"🗑 Đã huỷ auto buff cho UID <code>{uid}</code>.")
    else:
        bot.reply_to(msg, f"❌ UID <code>{uid}</code> không có trong danh sách auto.")

@bot.message_handler(commands=["listauto"])
def cmd_list_auto(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    items = auto_list_for_chat(msg.chat.id)
    if not items:
        bot.reply_to(msg, "📋 Chưa có UID nào đăng ký auto.")
        return
    rows = []
    for uid, v in items:
        mode = v.get("mode", "forever")
        t_val = v.get("target_value", 0)
        if mode == "forever":
            m_str = "Vĩnh viễn"
        elif mode == "days":
            m_str = f"Còn {t_val} ngày"
        elif mode == "likes":
            m_str = f"Mục tiêu {t_val:,} like"
        else:
            m_str = "KGH"
        rows.append(f"🆔 <code>{uid}</code> | 🌍 {v.get('region', 'BD')} | 📌 {m_str}")
    bot.reply_to(msg, f"📋 <b>Danh sách Auto Buff ({len(items)} UID):</b>\n\n" + "\n".join(rows))

@bot.message_handler(commands=["myid"])
def cmd_my_id(msg: Message):
    bot.reply_to(msg, f"ℹ️ Chat ID: <code>{msg.chat.id}</code> | User ID: <code>{msg.from_user.id}</code>")


@bot.message_handler(commands=["admin", "menuadmin"])
def cmd_admin_menu(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        bot.reply_to(msg, "❌ Bạn không có quyền admin.")
        return
    text = (
        "🛠 <b>MENU ADMIN</b>\n\n"
        "📌 <b>Quản lý Admin:</b>\n"
        "• <code>/addmin &lt;User_ID&gt;</code> - Thêm Admin mới\n"
        "• <code>/deladmin &lt;User_ID&gt;</code> - Gỡ quyền Admin\n"
        "• <code>/listadmin</code> - Xem danh sách Admin\n\n"
        "📌 <b>Quản lý hệ thống:</b>\n"
        "• <code>/khoa</code> - Tạm khóa toàn bộ bot\n"
        "• <code>/mobot</code> - Mở khóa lại bot\n\n"
        "📌 <b>Quản lý nhóm:</b>\n"
        "• <code>/on</code> - Cấp quyền nhóm hiện tại\n"
        "• <code>/off</code> - Tước quyền nhóm hiện tại\n"
        "• <code>/tb [nội dung]</code> - Thông báo tới các nhóm\n\n"
        "📌 <b>Quản lý like:</b>\n"
        "• <code>/setlimit &lt;số&gt;</code> - Đặt hạn mức/ngày\n"
        "• <code>/reset &lt;user_id&gt;</code> - Reset lượt buff 1 user\n"
        "• <code>/resetall</code> - Reset lượt buff tất cả user\n"
        "• <code>/usagelist</code> - Xem lượt dùng của tất cả user\n\n"
        "📌 <b>Quản lý auto:</b>\n"
        "• <code>/auto &lt;UID&gt; [ngày|like]</code> - Thêm auto\n"
        "• <code>/stopauto &lt;UID&gt;</code> - Xoá auto\n"
        "• <code>/listauto</code> - Danh sách auto\n\n"
        "📌 <b>Khác:</b>\n"
        "• <code>/myid</code> - Xem ID chat/user"
    )
    bot.reply_to(msg, text, parse_mode="HTML")


@bot.message_handler(commands=["reset"])
def cmd_reset_user(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    parts = msg.text.strip().split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        bot.reply_to(msg, "⚠️ Cú pháp: <code>/reset &lt;user_id&gt;</code>")
        return
    target_id = parts[1].strip()
    if target_id in user_usage:
        user_usage[target_id]["count"] = 0
        save_user_usage()
        bot.reply_to(msg, f"✅ Đã reset lượt buff cho user <code>{target_id}</code>.\n"
                          f"🔋 Lượt còn lại: <b>{_get_daily_limit()}</b>")
    else:
        user_usage[target_id] = {"date": datetime.now(VN_TZ).strftime("%Y-%m-%d"), "count": 0}
        save_user_usage()
        bot.reply_to(msg, f"⚠️ User <code>{target_id}</code> chưa có dữ liệu, đã tạo mới với 0 lượt dùng.")

@bot.message_handler(commands=["resetall"])
def cmd_reset_all(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    for uid in user_usage:
        user_usage[uid] = {"date": today, "count": 0}
    save_user_usage()
    bot.reply_to(msg, f"✅ Đã reset lượt buff cho <b>tất cả {len(user_usage)} user</b>.\n"
                      f"Hạn mức mới: <b>{_get_daily_limit()}</b> lần/ngày.")

@bot.message_handler(commands=["usagelist"])
def cmd_usage_list(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    if not user_usage:
        bot.reply_to(msg, "📋 Chưa có user nào sử dụng.")
        return
    daily_limit = _get_daily_limit()
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    lines = []
    for uid, info in user_usage.items():
        used = info.get("count", 0) if info.get("date") == today else 0
        remaining = daily_limit - used
        lines.append(f"👤 <code>{uid}</code> | Đã dùng: <b>{used}</b> | Còn: <b>{remaining}</b>")
    text = f"📋 <b>DANH SÁCH LƯỢT DÙNG HÔM NAY ({today})</b>\n\n" + "\n".join(lines[:50])
    bot.reply_to(msg, text, parse_mode="HTML")


@app.route('/like', methods=['GET'])
def api_like():
    uid = request.args.get("uid")
    region = request.args.get("server_name", "BD").upper()
    key = request.args.get("key")
    if key != "SIAM":
        return jsonify({"error": "Invalid or missing API key 🔑"}), 403
    if not uid:
        return jsonify({"error": "UID is required"}), 400
    result = do_like_process(uid, region)
    if "error" in result:
        return jsonify(result), 500
    return jsonify({
        "TotalAccountsExecuted": result["total_accounts"],
        "LikesGivenByAPI": result["added"],
        "LikesafterCommand": result["after"],
        "LikesbeforeCommand": result["before"],
        "PlayerNickname": result["nickname"],
        "UID": result["uid"],
        "status": result["status"]
    })


if __name__ == "__main__":
    print("🚀 Khởi động hệ thống...")
    load_admins()
    load_user_usage()
    load_lock_state()
    load_token_cache()
    print("✅ Đã load dữ liệu Admin, lượt dùng user & trạng thái khóa bot")
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False), daemon=True).start()
    print("🌐 Flask API đã chạy trên cổng 5001")
    threading.Thread(target=auto_like_scheduler, daemon=True).start()
    threading.Thread(target=broadcast_promo_scheduler, daemon=True).start()
    print("🤖 Bot Telegram đang hoạt động...")
    bot.skip_pending = True
    bot.infinity_polling(timeout=30, long_polling_timeout=20)