import asyncio
import datetime as dt
import logging
import os
import random
from typing import Optional

import discord
from aiohttp import web
from discord.ext import commands, tasks
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

BIRTHDAY_USER_ID = int(os.getenv("BIRTHDAY_USER_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

PING_INTERVAL = max(1, int(os.getenv("PING_INTERVAL", "15")))
PORT = int(os.getenv("PORT", "8080"))

# Let env override the model, but keep a safe fallback list.
RAW_MODEL = os.getenv("GEMINI_MODEL", "").strip()
GEMINI_MODELS = [m for m in [RAW_MODEL, "gemini-3.5-flash", "gemini-2.0-flash"] if m]

REQUIRED_ENV = {
    "BOT_TOKEN": BOT_TOKEN,
    "BIRTHDAY_USER_ID": str(BIRTHDAY_USER_ID) if BIRTHDAY_USER_ID else "",
    "CHANNEL_ID": str(CHANNEL_ID) if CHANNEL_ID else "",
}

missing = [name for name, value in REQUIRED_ENV.items() if not value]
if missing:
    raise EnvironmentError(
        f"Missing required .env variables: {', '.join(missing)}"
    )

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("birthday-bot")

# ============================================================
# GEMINI SETUP
# ============================================================
gemini_client: Optional[genai.Client] = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        log.info("Gemini client initialized.")
    except Exception as exc:
        log.warning("Gemini init failed: %s", exc)
        gemini_client = None
else:
    log.info("No GEMINI_API_KEY found; bot will use fallback messages.")

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
START_TIME = dt.datetime.now(dt.timezone.utc)

# ============================================================
# DISCORD BOT
# ============================================================
intents = discord.Intents.default()
intents.message_content = True  # also enable in Discord Developer Portal

bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents)


def clean_gemini_text(text: str) -> str:
    """
    Make Gemini output safe and compact for a Discord message.
    """
    text = text.strip()
    text = text.replace("\n", " ").replace("\r", " ")

    # Remove common markdown wrappers if the model adds them.
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()

    # Keep it short and to the point.
    if len(text) > 300:
        text = text[:300].rstrip() + "…"

    return text


async def fetch_gemini_message() -> Optional[str]:
    """
    Generate one short birthday message using Gemini.
    Returns None if anything goes wrong.
    """
    if gemini_client is None:
        return None

    style = random.choice(STYLES)
    prompt = (
        f"Write one short, fun birthday message in this style: {style}. "
        "Use 1-2 relevant emojis. "
        "Do NOT include a name or username. "
        "Do NOT wrap the response in quotes or markdown. "
        "Reply with only the final message text."
    )

    last_error: Optional[Exception] = None

    for model_name in GEMINI_MODELS:
        try:
            response = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
            )

            text = getattr(response, "text", None)
            if not text:
                log.warning("Gemini returned empty text for model %s", model_name)
                continue

            cleaned = clean_gemini_text(text)
            if cleaned:
                log.info("Gemini message generated with %s", model_name)
                return cleaned

        except Exception as exc:
            last_error = exc
            log.warning("Gemini error with %s: %s", model_name, exc)

    if last_error:
        log.warning("All Gemini attempts failed; using fallback.")
    return None


async def get_channel(channel_id: int) -> Optional[discord.abc.Messageable]:
    """
    Fetch the channel safely, even if it isn't cached.
    """
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        fetched = await bot.fetch_channel(channel_id)
        return fetched
    except Exception as exc:
        log.error("Could not fetch channel %s: %s", channel_id, exc)
        return None


@tasks.loop(seconds=PING_INTERVAL)
async def birthday_ping():
    global ping_count

    try:
        channel = await get_channel(CHANNEL_ID)
        if channel is None:
            log.error("Channel %s not found.", CHANNEL_ID)
            return

        body = await fetch_gemini_message()
        if body:
            msg = f"<@{BIRTHDAY_USER_ID}> {body}"
        else:
            msg = random.choice(FALLBACK_MESSAGES).format(uid=BIRTHDAY_USER_ID)

        await channel.send(msg)
        ping_count += 1
        log.info("Birthday ping #%d sent.", ping_count)

    except discord.Forbidden:
        log.error("Missing permission to send messages in channel %s.", CHANNEL_ID)
    except discord.HTTPException as exc:
        log.error("Discord HTTP error while sending message: %s", exc)
    except Exception as exc:
        log.exception("Unexpected error in birthday_ping: %s", exc)


@birthday_ping.before_loop
async def before_birthday_ping():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id if bot.user else "unknown")

    if not birthday_ping.is_running():
        birthday_ping.start()
        log.info("Birthday ping loop started; interval=%ss", PING_INTERVAL)
    else:
        log.info("Birthday ping loop already running.")


# ============================================================
# COMMANDS
# ============================================================
@bot.command(name="stopbirthday")
@commands.has_permissions(administrator=True)
async def stop_birthday(ctx: commands.Context):
    if birthday_ping.is_running():
        birthday_ping.stop()
        await ctx.send("🛑 Birthday pings stopped.")
    else:
        await ctx.send("ℹ️ Birthday pings are not running.")


@bot.command(name="startbirthday")
@commands.has_permissions(administrator=True)
async def start_birthday(ctx: commands.Context):
    if not birthday_ping.is_running():
        birthday_ping.start()
        await ctx.send("🎉 Birthday pings started!")
    else:
        await ctx.send("ℹ️ Birthday pings are already running.")


@bot.command(name="birthdaystatus")
async def birthday_status(ctx: commands.Context):
    mode = "Gemini AI 🤖" if gemini_client else "fallback messages 📋"
    status = "✅ Running" if birthday_ping.is_running() else "🛑 Stopped"
    await ctx.send(
        f"Loop: {status} | Messages: {mode} | Pings sent: {ping_count}"
    )


@stop_birthday.error
@start_birthday.error
async def admin_only_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ You need administrator permissions for that.")
    else:
        raise error


# ============================================================
# KEEPALIVE WEB SERVER
# ============================================================
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


async def handle_root(request: web.Request) -> web.Response:
    now = dt.datetime.now(dt.timezone.utc)
    delta = now - START_TIME
    total_seconds = int(delta.total_seconds())

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{hours}h {minutes}m {seconds}s"
    mode = "🤖 Gemini AI" if gemini_client else "📋 Fallback messages"

    html = KEEPALIVE_HTML.format(
        interval=PING_INTERVAL,
        uptime=uptime,
        start=START_TIME.strftime("%Y-%m-%d %H:%M UTC"),
        mode=mode,
    )
    return web.Response(text=html, content_type="text/html")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "uptime_seconds": int(
                (dt.datetime.now(dt.timezone.utc) - START_TIME).total_seconds()
            ),
            "pings_sent": ping_count,
            "message_mode": "gemini" if gemini_client else "fallback",
        }
    )


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    log.info("Keepalive server running on port %s", PORT)
    return runner


# ============================================================
# MAIN
# ============================================================
async def main():
    runner = None
    try:
        runner = await start_web_server()
        await bot.start(BOT_TOKEN)
    finally:
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
