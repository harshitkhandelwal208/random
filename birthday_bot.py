import discord
from discord.ext import commands, tasks
import os
import asyncio
import datetime
import random
from aiohttp import web
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────
BOT_TOKEN        = os.getenv("BOT_TOKEN")
BIRTHDAY_USER_ID = int(os.getenv("BIRTHDAY_USER_ID", "0"))
CHANNEL_ID       = int(os.getenv("CHANNEL_ID", "0"))
PING_INTERVAL    = int(os.getenv("PING_INTERVAL", "15"))
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")

missing = [k for k, v in {
    "BOT_TOKEN": BOT_TOKEN,
    "BIRTHDAY_USER_ID": os.getenv("BIRTHDAY_USER_ID"),
    "CHANNEL_ID": os.getenv("CHANNEL_ID"),
}.items() if not v]

if missing:
    raise EnvironmentError(f"❌ Missing required .env variables: {', '.join(missing)}")

# ─────────────────────────────────────────────
#  GEMINI SETUP
# ─────────────────────────────────────────────
gemini_model = None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-2.0-flash")
        print("🤖 Gemini API ready.")
    except Exception as e:
        print(f"⚠️  Gemini setup failed: {e} — using fallback messages.")
else:
    print("⚠️  GEMINI_API_KEY not set — using fallback messages.")

# ─────────────────────────────────────────────
#  FALLBACK MESSAGES
# ─────────────────────────────────────────────
FALLBACK_MESSAGES = [
    "🎂 HAPPY BIRTHDAY <@{uid}>! Hope your day is absolutely amazing! 🎉",
    "🎁 Hey <@{uid}>, HAPPY BIRTHDAY!! Wishing you all the best today! 🥳",
    "🎊 <@{uid}> IT'S YOUR BIRTHDAY!! Have an incredible day! 🍰",
    "🎈 Happy Birthday <@{uid}>!! You deserve all the cake in the world! 🎂",
    "🥂 Cheers to you, <@{uid}>! HAPPY BIRTHDAY!! 🎉🎊🎈",
]

STYLES = [
    "overly dramatic and theatrical",
    "like a pirate",
    "like an excited golden retriever",
    "formal and regal, like a medieval herald",
    "like a sports commentator mid-game",
    "in the style of a nature documentary narrator",
    "like a villain who secretly loves birthdays",
    "extremely wholesome and sincere",
    "like a hype man at a rap concert",
    "like a disappointed parent who is also very proud",
]

ping_count = 0


async def fetch_gemini_message() -> str | None:
    """
    Calls Gemini synchronously inside a thread so it doesn't block the
    event loop. Returns the message string, or None on any failure.
    """
    style = random.choice(STYLES)
    prompt = (
        f"Write one short, fun birthday message in this style: {style}. "
        "Include 1-2 relevant emojis. "
        "Do NOT include a name or username — the Discord mention is added automatically. "
        "Reply with only the message text and nothing else."
    )
    try:
        # Run the blocking SDK call in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(gemini_model.generate_content, prompt)
        text = response.text.strip()
        if not text:
            print("⚠️  Gemini returned empty response — using fallback.")
            return None
        print(f"✅ Gemini message: {text[:60]}...")
        return text
    except Exception as e:
        print(f"⚠️  Gemini API error ({type(e).__name__}): {e} — using fallback.")
        return None


# ─────────────────────────────────────────────
#  BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    # Guard against on_ready firing multiple times on reconnects
    if not birthday_ping.is_running():
        birthday_ping.start()
        print(f"🎂 Birthday ping loop started — every {PING_INTERVAL}s")
    else:
        print("🔁 Reconnected — ping loop already running, skipping restart.")


@tasks.loop(seconds=PING_INTERVAL)
async def birthday_ping():
    global ping_count

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"❌ Channel {CHANNEL_ID} not found.")
        return

    # Try Gemini; fall back to cycling through the hardcoded list
    if gemini_model:
        body = await fetch_gemini_message()
    else:
        body = None

    if body:
        msg = f"<@{BIRTHDAY_USER_ID}> {body}"
    else:
        msg = FALLBACK_MESSAGES[ping_count % len(FALLBACK_MESSAGES)].format(uid=BIRTHDAY_USER_ID)

    await channel.send(msg)
    ping_count += 1
    print(f"🎉 Ping #{ping_count} sent.")


@birthday_ping.before_loop
async def before_birthday_ping():
    await bot.wait_until_ready()


@birthday_ping.error
async def birthday_ping_error(error):
    # Catch any unhandled exception in the loop so it doesn't silently die
    print(f"❌ birthday_ping task error: {error}")
    birthday_ping.restart()


# ─────────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────────

@bot.command(name="stopbirthday")
@commands.has_permissions(administrator=True)
async def stop_birthday(ctx):
    if birthday_ping.is_running():
        birthday_ping.stop()
        await ctx.send("🛑 Birthday pings stopped.")
    else:
        await ctx.send("ℹ️ Birthday pings are not running.")


@bot.command(name="startbirthday")
@commands.has_permissions(administrator=True)
async def start_birthday(ctx):
    if not birthday_ping.is_running():
        birthday_ping.start()
        await ctx.send("🎉 Birthday pings started!")
    else:
        await ctx.send("ℹ️ Birthday pings are already running.")


@bot.command(name="birthdaystatus")
async def birthday_status(ctx):
    mode = "Gemini AI 🤖" if gemini_model else "hardcoded fallback 📋"
    status = "✅ Running" if birthday_ping.is_running() else "🛑 Stopped"
    await ctx.send(
        f"Loop: {status} | Messages: {mode} | Pings sent: {ping_count}"
    )


# ─────────────────────────────────────────────
#  KEEPALIVE WEB SERVER
#  CSS braces doubled ({{ }}) to escape str.format()
# ─────────────────────────────────────────────
START_TIME = datetime.datetime.now(datetime.UTC)

KEEPALIVE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Birthday Bot — Online</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0f0f0f;
      font-family: 'Segoe UI', sans-serif;
      color: #fff;
    }}
    .card {{
      text-align: center;
      padding: 3rem 4rem;
      background: #1a1a1a;
      border-radius: 1.5rem;
      border: 1px solid #2a2a2a;
      box-shadow: 0 0 60px rgba(255, 200, 0, 0.08);
    }}
    .emoji {{ font-size: 4rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.8rem; font-weight: 700; margin-bottom: 0.5rem; color: #ffe066; }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      margin: 1.2rem 0;
      padding: 0.4rem 1rem;
      background: #111;
      border-radius: 999px;
      font-size: 0.9rem;
      border: 1px solid #2a2a2a;
    }}
    .dot {{
      width: 8px; height: 8px;
      border-radius: 50%;
      background: #4ade80;
      animation: pulse 1.8s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.3; }}
    }}
    .badge {{
      display: inline-block;
      margin-top: 0.8rem;
      padding: 0.25rem 0.75rem;
      background: #1e1e2e;
      border: 1px solid #333;
      border-radius: 999px;
      font-size: 0.75rem;
      color: #60a5fa;
    }}
    .meta {{ font-size: 0.8rem; color: #555; margin-top: 1.5rem; }}
    .meta span {{ color: #888; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="emoji">🎂</div>
    <h1>Birthday Bot</h1>
    <div class="status">
      <div class="dot"></div>
      Online &amp; running
    </div>
    <p style="color:#666; font-size:0.9rem;">Pinging every {interval}s &nbsp;&middot;&nbsp; Uptime: {uptime}</p>
    <div class="badge">{mode}</div>
    <p class="meta">Deployed on Render &nbsp;&middot;&nbsp; Started <span>{start}</span></p>
  </div>
</body>
</html>"""


async def handle_root(request):
    now = datetime.datetime.now(datetime.UTC)
    delta = now - START_TIME
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{hours}h {minutes}m {seconds}s"
    mode = "🤖 Gemini AI" if gemini_model else "📋 Fallback messages"
    html = KEEPALIVE_HTML.format(
        interval=PING_INTERVAL,
        uptime=uptime,
        start=START_TIME.strftime("%Y-%m-%d %H:%M UTC"),
        mode=mode,
    )
    return web.Response(text=html, content_type="text/html")


async def handle_health(request):
    return web.json_response({
        "status": "ok",
        "uptime_seconds": int((datetime.datetime.now(datetime.UTC) - START_TIME).total_seconds()),
        "pings_sent": ping_count,
        "message_mode": "gemini" if gemini_model else "fallback",
    })


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Keepalive server running on port {port}")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
async def main():
    await start_web_server()
    await bot.start(BOT_TOKEN)


asyncio.run(main())
