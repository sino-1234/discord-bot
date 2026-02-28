import discord
from discord.ext import commands

import os
import json
import re
from datetime import datetime, timedelta

from PIL import Image
import pytesseract

# ===== 設定 =====
DATA_FILE = "data.json"
STATE_FILE = "state.json"
IMAGE_DIR = "images"

ADMIN_PASSWORD = "senpansine"

IMAGE_CHANNEL_ID = 1441414653648568472
RESULT_CHANNEL_ID = 1453386509620346922
FAILED_CHANNEL_ID = 1453386433913032754
REPORT_CHANNEL_ID = 1441414653648568472

HISTORY_LIMIT = 1000

os.makedirs(IMAGE_DIR, exist_ok=True)


# ===== Discord =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ===== state =====
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_message_id": None}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ===== data =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== OCR =====
def extract_id_from_image(img: Image.Image):
    w, h = img.size
    crops = [
        (0.42, 0.05, 1.00, 0.25),
        (0.42, 0.10, 1.00, 0.30),
        (0.42, 0.15, 1.00, 0.35),
    ]

    last_crop = None

    for l, t, r, b in crops:
        crop = img.crop((int(w*l), int(h*t), int(w*r), int(h*b)))
        last_crop = crop

        text = pytesseract.image_to_string(
            crop,
            lang="jpn+eng",
            config="--psm 6"
        )

        m = re.search(r"\b\d{6,10}\b", text)
        if m:
            return m.group(), None

    return None, last_crop


async def get_log_channel():
    return await bot.fetch_channel(RESULT_CHANNEL_ID)


async def get_failed_channel():
    return await bot.fetch_channel(FAILED_CHANNEL_ID)


# ===== 長文送信用 =====
async def send_long_message(ctx, text, limit=1900):
    for i in range(0, len(text), limit):
        await ctx.send(text[i:i+limit])


# ===== 画像処理 =====
async def process_image_message(message, from_history=False):
    data = load_data()

    # 投稿された実際の日付を取得（日本時間）
    today = (message.created_at + timedelta(hours=9)).strftime("%Y-%m-%d")
    log_ch = await get_log_channel()
    failed_ch = await get_failed_channel()

    for att in message.attachments:
        if not att.content_type:
            if not att.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
        else:
            if not att.content_type.startswith("image/"):
                continue

        path = os.path.join(IMAGE_DIR, f"{message.id}_{att.filename}")
        await att.save(path)

        try:
            with Image.open(path) as img:
                game_id, failed_crop = extract_id_from_image(img)
        except Exception:
            os.remove(path)
            continue

        if game_id:
            if game_id not in data:
                data[game_id] = {
                    "count": 1,
                    "twitter": None,
                    "sex": None,
                    "position": None,
                    "logs": [today]
                }
            else:
                data[game_id]["count"] += 1
                data[game_id].setdefault("logs", []).append(today)

            save_data(data)

            await log_ch.send(
                f"{'⏮ 履歴登録' if from_history else '📸 写真登録'}\n"
                f"ID：{game_id}\n"
                f"登録回数：{data[game_id]['count']}"
            )
        else:
            if failed_crop:
                p = os.path.join(IMAGE_DIR, f"failed_{message.id}_{att.filename}.png")
                failed_crop.save(p)
                await failed_ch.send(
                    f"⚠ OCR失敗\n投稿者：{message.author}",
                    file=discord.File(p)
                )
                os.remove(p)

        os.remove(path)


@bot.event
async def on_ready():
    print("Bot ready")

    log_ch = await get_log_channel()
    await log_ch.send("⏮ 履歴処理開始")

    state = load_state()
    last_id = state.get("last_message_id")

    channel = await bot.fetch_channel(IMAGE_CHANNEL_ID)

    processed_last_id = last_id

    try:
        async for msg in channel.history(
            limit=None,
            oldest_first=True,
            after=discord.Object(id=last_id) if last_id else None
        ):
            if msg.attachments:
                await process_image_message(msg, from_history=True)

            processed_last_id = msg.id

        # ループ終了後に保存
        if processed_last_id:
            state["last_message_id"] = processed_last_id
            save_state(state)

        await log_ch.send("✅ 履歴処理完了")

    except Exception as e:
        await log_ch.send(f"⚠ 履歴処理中エラー: {e}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.channel.id == IMAGE_CHANNEL_ID and message.attachments:
        await process_image_message(message)
        state = load_state()
        state["last_message_id"] = message.id
        save_state(state)

    await bot.process_commands(message)


# ===== 🏓 ping =====
@bot.command()
async def ping(ctx):
    await ctx.send("pong")
# ===== 📝 register =====
@bot.command()
async def register(ctx, game_id=None):
    if not game_id:
        await ctx.send("⚠ 使い方：!register <ID>")
        return

    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")

    if game_id not in data:
        data[game_id] = {
            "count": 1,
            "twitter": None,
            "sex": None,
            "position": None,
            "logs": [today]
        }
    else:
        data[game_id]["count"] += 1
        data[game_id].setdefault("logs", []).append(today)

    save_data(data)

    await (await get_log_channel()).send(
        f"📝 手動登録\n"
        f"ID：{game_id}\n"
        f"登録回数：{data[game_id]['count']}"
    )

    await ctx.send(f"✅ 登録しました\nID：{game_id}")

# ===== 🐦 write =====
@bot.command()
async def write(ctx, game_id=None, twitter_id=None):
    if not game_id or not twitter_id:
        await ctx.send("⚠ 使い方：!write <ID> <TwitterID>")
        return

    data = load_data()
    if game_id not in data:
        await ctx.send("❌ 未登録IDです")
        return

    data[game_id]["twitter"] = twitter_id.lstrip("@")
    save_data(data)

    await (await get_log_channel()).send(
        f"🐦 Twitter登録\n"
        f"ID：{game_id}\n"
        f"https://x.com/{data[game_id]['twitter']}?s=20"
    )

    await ctx.send("✅ Twitterを登録しました")


# ===== 📊 count =====
@bot.command()
async def count(ctx, *, query=None):
    data = load_data()

    if not query:
        await ctx.send("⚠ 使い方：!count <ID または 名前>")
        return

    # =============================
    # 🔢 IDが完全一致した場合
    # =============================
    if query in data:
        info = data[query]

        msg = f"📊 ID：{query}\n"

        if info.get("name"):
            msg += f"📛 現在の名前：{info['name']}\n"

        name_logs = info.get("name_logs", [])
        if name_logs:
            names = [n["name"] for n in name_logs]
            msg += "📝 名前履歴：" + " / ".join(names) + "\n"

        twitter = info.get("twitter")
        msg += (
            f"登録回数：{info['count']}\n"
            f"🐦 Twitter："
            f"{f'https://x.com/{twitter}?s=20' if twitter else '未登録'}\n"
        )

        if info.get("sex"):
            msg += f"🔞 性癖：{info['sex']}\n"

        if info.get("position"):
            msg += f"🔁 体位：{info['position']}\n"

        await ctx.send(msg)
        return

    # =============================
    # 🔎 名前検索（部分一致）
    # =============================
    results = []

    for gid, info in data.items():
        # 現在名チェック
        if info.get("name") and query in info["name"]:
            results.append(gid)
            continue

        # 履歴チェック
        for n in info.get("name_logs", []):
            if query in n.get("name", ""):
                results.append(gid)
                break

    if not results:
        await ctx.send("❌ 該当するID・名前が見つかりません")
        return

    msg = f"🔎 名前検索結果（{query}）\n"
    for gid in results:
        msg += f"ID：{gid}\n"

    await send_long_message(ctx, msg)
# ===== 🔞 sex =====
@bot.command()
async def sex(ctx, arg1=None, *, arg2=None):
    if not arg1:
        await ctx.send("⚠ 使い方：!sex <ID> <性癖> / !sex clear <ID>")
        return

    data = load_data()

    # ===== 削除 =====
    if arg1 == "clear":
        if not arg2 or arg2 not in data:
            await ctx.send("❌ 未登録IDです")
            return

        data[arg2]["sex"] = None
        save_data(data)

        await ctx.send(f"♻ 性癖を削除しました\nID：{arg2}")
        return

    # ===== 登録 =====
    if arg1 not in data or not arg2:
        await ctx.send("❌ 未登録ID または 性癖未指定")
        return

    data[arg1]["sex"] = arg2
    save_data(data)

    await (await get_log_channel()).send(
        "🔞 性癖登録\n"
        f"ID：{arg1}\n"
        f"内容：{arg2}"
    )

    await ctx.send("✅ 性癖を登録しました")


# ===== 🔁 position =====
@bot.command()
async def position(ctx, arg1=None, *, arg2=None):
    if not arg1:
        await ctx.send("⚠ 使い方：!position <ID> <体位> / !position clear <ID>")
        return

    data = load_data()

    # ===== 削除 =====
    if arg1 == "clear":
        if not arg2 or arg2 not in data:
            await ctx.send("❌ 未登録IDです")
            return

        data[arg2]["position"] = None
        save_data(data)

        await ctx.send(f"♻ 体位を削除しました\nID：{arg2}")
        return

    # ===== 登録 =====
    if arg1 not in data or not arg2:
        await ctx.send("❌ 未登録ID または 体位未指定")
        return

    data[arg1].setdefault("position", None)
    data[arg1]["position"] = arg2
    save_data(data)

    await (await get_log_channel()).send(
        "🔁 体位登録\n"
        f"ID：{arg1}\n"
        f"内容：{arg2}"
    )

    await ctx.send("✅ 体位を登録しました")


# ===== 🏆 ranking =====
@bot.command()
async def ranking(ctx, arg1=None, arg2=None):
    data = load_data()
    if not data:
        await ctx.send("❌ データなし")
        return

    limit = 5
    mode = "all"
    days = None

    if arg1:
        if arg1.upper() == "ALL":
            limit = None
        elif arg1.lower() in ("day", "month"):
            mode = arg1.lower()
            if arg2 and arg2.isdigit():
                n = int(arg2)
                days = n if mode == "day" else n * 30
        elif arg1.isdigit():
            limit = int(arg1)

    today = datetime.now()
    results = []

    for gid, info in data.items():
        logs = info.get("logs", [])
        cnt = 0

        if days:
            border = today - timedelta(days=days)
            for d in logs:
                try:
                    if datetime.strptime(d, "%Y-%m-%d") >= border:
                        cnt += 1
                except Exception:
                    pass
        else:
            cnt = info.get("count", 0)

        if cnt > 0:
            results.append((gid, cnt))

    results.sort(key=lambda x: x[1], reverse=True)

    if limit:
        results = results[:limit]

    title = "📊 ランキング"
    if mode == "day" and days:
        title += f"（直近{days}日）"
    elif mode == "month" and days:
        title += f"（直近{days // 30}か月）"

    msg = title + "\n"
    for i, (gid, cnt) in enumerate(results, 1):
        msg += f"{i}位：{gid}（{cnt}回）\n"

    await send_long_message(ctx, msg)


# ===== 📛 writename =====
@bot.command()
async def writename(ctx, arg1=None, arg2=None, arg3=None, *, arg4=None):
    data = load_data()

    # ===== 削除系（DM限定＋パスワード必須）=====
    if arg1 in ("clear", "del"):
        # DM以外は無反応
        if ctx.guild is not None:
            return

        # clear: arg1=clear, arg2=ID, arg3=password
        # del  : arg1=del,   arg2=ID, arg3=番号, arg4=password
        if arg1 == "clear":
            if not arg2 or arg3 != ADMIN_PASSWORD:
                return
            if arg2 not in data:
                return

            data[arg2]["name_logs"] = []
            data[arg2]["name"] = None
            save_data(data)

            await ctx.send(f"♻ 名前履歴を全削除しました\nID：{arg2}")
            return

        if arg1 == "del":
            if not arg2 or not arg3 or arg4 != ADMIN_PASSWORD:
                return
            if arg2 not in data:
                return

            try:
                idx = int(arg3) - 1
            except ValueError:
                return

            logs = data[arg2].get("name_logs", [])
            if idx < 0 or idx >= len(logs):
                return

            removed = logs.pop(idx)

            # 現在名を更新
            if logs:
                data[arg2]["name"] = logs[-1]["name"]
            else:
                data[arg2]["name"] = None

            save_data(data)

            await ctx.send(
                f"🗑 名前履歴を削除しました\n"
                f"ID：{arg2}\n"
                f"削除名：{removed['name']}"
            )
            return

    # ===== 通常登録 =====
    game_id = arg1
    name = arg2 if arg4 is None else f"{arg2} {arg3} {arg4}".strip()

    if not game_id or not name:
        return

    if game_id not in data:
        await ctx.send("❌ 未登録IDです")
        return

    data[game_id].setdefault("name_logs", [])
    data[game_id]["name_logs"].append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name
    })

    data[game_id]["name"] = name
    save_data(data)

    await (await get_log_channel()).send(
        f"📛 名前登録\nID：{game_id}\n名前：{name}"
    )
    await ctx.send("✅ 名前を登録しました")



# ===== 🧱 black（黒歴史）=====
@bot.command()
async def black(ctx, game_id=None, *, text=None):
    if not game_id or not text:
        return

    data = load_data()
    if game_id not in data:
        await ctx.send("❌ 未登録IDです")
        return

    data[game_id].setdefault("black", [])
    data[game_id]["black"].append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text": text
    })

    save_data(data)
    await (await get_log_channel()).send(
        f"🧱 黒歴史追加\nID：{game_id}\n内容：{text}"
    )
    await ctx.send("✅ 記録しました")
@bot.command()
async def report(ctx, password=None, *, message=None):
    if ctx.guild is not None:
        await ctx.send("❌ DM限定")
        return
    if not password or password != ADMIN_PASSWORD or not message:
        await ctx.send("❌ 認証失敗")
        return
    channel = bot.get_channel(REPORT_CHANNEL_ID)
    if channel:
        await channel.send("📢 **運営からの連絡**\n" + message)
    await ctx.send("✅ 送信完了")

# ===== 🗑 del_（DM専用・完全版）=====
@bot.command(name="del_")
async def del_(ctx, game_id=None, password=None):
    # DM以外では拒否
    if ctx.guild is not None:
        await ctx.send("❌ このコマンドはDM専用です")
        return

    # 引数チェック
    if not game_id or not password:
        await ctx.send("⚠ 使い方：!del_ <ID> <password>")
        return

    # パスワード確認
    if password != ADMIN_PASSWORD:
        await ctx.send("❌ パスワードが違います")
        return

    data = load_data()

    # ID存在チェック
    if game_id not in data:
        await ctx.send("❌ 未登録IDです")
        return

    # 削除
    del data[game_id]
    save_data(data)

    await ctx.send(f"🗑 削除完了\nID：{game_id}")


# ===== 起動 =====
bot.run(os.getenv("TOKEN"))
