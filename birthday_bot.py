import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env into os.environ

# ─────────────────────────────────────────────
#  CONFIGURATION — loaded from .env file
# ─────────────────────────────────────────────
BOT_TOKEN        = os.getenv("BOT_TOKEN")
BIRTHDAY_USER_ID = int(os.getenv("BIRTHDAY_USER_ID"))
CHANNEL_ID       = int(os.getenv("CHANNEL_ID"))
PING_INTERVAL    = int(os.getenv("PING_INTERVAL", 15))  # defaults to 15 if not set

# Validate that required vars are present
missing = [k for k, v in {
    "BOT_TOKEN": BOT_TOKEN,
    "BIRTHDAY_USER_ID": BIRTHDAY_USER_ID,
    "CHANNEL_ID": CHANNEL_ID,
}.items() if not v]

if missing:
    raise EnvironmentError(f"❌ Missing required .env variables: {', '.join(missing)}")

# ─────────────────────────────────────────────
#  Birthday messages (cycles through these)
# ─────────────────────────────────────────────
BIRTHDAY_MESSAGES = [
    "🎂 HAPPY BIRTHDAY <@{uid}>! Hope your day is absolutely amazing! 🎉",
    "🎁 Hey <@{uid}>, HAPPY BIRTHDAY!! Wishing you all the best today! 🥳",
    "🎊 <@{uid}> IT'S YOUR BIRTHDAY!! Have an incredible day! 🍰",
    "🎈 Happy Birthday <@{uid}>!! You deserve all the cake in the world! 🎂",
    "🥂 Cheers to you, <@{uid}>! HAPPY BIRTHDAY!! 🎉🎊🎈",
]

# ─────────────────────────────────────────────
#  Bot setup
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

message_index = 0  # tracks which message to send next


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"🎂 Birthday pings will be sent every {PING_INTERVAL} seconds")
    birthday_ping.start()   # start the looping task


@tasks.loop(seconds=PING_INTERVAL)
async def birthday_ping():
    global message_index

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"❌ Could not find channel {CHANNEL_ID}. Check the ID.")
        return

    msg = BIRTHDAY_MESSAGES[message_index % len(BIRTHDAY_MESSAGES)]
    message_index += 1

    await channel.send(msg.format(uid=BIRTHDAY_USER_ID))
    print(f"🎉 Sent birthday ping #{message_index}")


@birthday_ping.before_loop
async def before_birthday_ping():
    await bot.wait_until_ready()    # don't start until the bot is connected


# ─────────────────────────────────────────────
#  Optional commands
# ─────────────────────────────────────────────

@bot.command(name="stopbirthday")
@commands.has_permissions(administrator=True)
async def stop_birthday(ctx):
    """Admin command: !stopbirthday — stops the birthday pings."""
    if birthday_ping.is_running():
        birthday_ping.stop()
        await ctx.send("🛑 Birthday pings stopped.")
    else:
        await ctx.send("ℹ️ Birthday pings are not running.")


@bot.command(name="startbirthday")
@commands.has_permissions(administrator=True)
async def start_birthday(ctx):
    """Admin command: !startbirthday — resumes the birthday pings."""
    if not birthday_ping.is_running():
        birthday_ping.start()
        await ctx.send("🎉 Birthday pings started!")
    else:
        await ctx.send("ℹ️ Birthday pings are already running.")


@bot.command(name="birthdaystatus")
async def birthday_status(ctx):
    """Check whether the birthday ping loop is active."""
    status = "✅ Running" if birthday_ping.is_running() else "🛑 Stopped"
    await ctx.send(f"Birthday ping loop: {status}")


# ─────────────────────────────────────────────
#  Run the bot
# ─────────────────────────────────────────────
bot.run(BOT_TOKEN)
