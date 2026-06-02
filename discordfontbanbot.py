#!/usr/bin/env python3
"""
Discord.py bot for VERY LARGE servers (50k–200k+ members).
Scans all members for non-standard fonts / non-English names **and custom statuses** and bans them.

Key features for large servers:
- Respects Discord rate limits dynamically (retry_after + adaptive backoff with jitter)
- Processes bans in configurable batches (BATCH_SIZE)
- Regular progress updates so you know it's working
- Dry-run mode (strongly recommended first run on huge servers)
- Exponential backoff when rate limited
- Safety cap (MAX_BANS_PER_RUN)

SETUP:
1. Enable **both** "Server Members Intent" **and** "Presence Intent" in Discord Developer Portal.
   (Presence Intent is required to read custom statuses)
2. Invite bot with "Ban Members" permission.
3. pip install discord.py
4. Replace BOT_TOKEN and OWNER_ID below.
5. For huge servers: Set DRY_RUN = True first, run !scanfonts, review, then set to False.

The detection = characters that render cleanly in Discord's standard default font.
If ENFORCE_ENGLISH_ONLY = True (default), it also requires English/Latin characters only.
Set ENFORCE_ENGLISH_ONLY = False to allow other languages/scripts while still blocking zalgo/fancy Unicode.

Also scans **custom status** text for the same rules (name or status failing = ban).
"""

import discord
from discord.ext import commands
import re
import unicodedata
import asyncio
import logging
import random
from datetime import datetime

# ==================== CONFIGURATION - EDIT THESE ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
OWNER_ID = 123456789012345678          # Your Discord user ID
PREFIX = "!"
LOG_CHANNEL_ID = None                  # Optional: channel ID for ban logs

# === VERY LARGE SERVER SETTINGS ===
BATCH_SIZE = 15                        # Ban this many, then pause (10-25 recommended)
BASE_BATCH_SLEEP = 2.5                 # Base sleep after each batch (seconds)
MAX_BACKOFF = 60                       # Never sleep longer than this even on heavy rate limiting
DRY_RUN = False                        # True = report only, do NOT ban (use this first!)
MAX_BANS_PER_RUN = 3000                # Safety: stop after this many bans in one session
PROGRESS_EVERY = 2500                  # Send progress message every X members checked

ENFORCE_ENGLISH_ONLY = True            # Set to False to ALLOW non-English characters/scripts
                                       # (still blocks zalgo, fancy Unicode, and non-standard font rendering)

# Standard English / Discord default font characters only
ALLOWED_PATTERN = re.compile(
    r'^[A-Za-z0-9\s\.\_\-@#&\'"!?()\[\]{}:;,\\/+=*^%$~`|]+$'
)
MAX_COMBINING_MARKS = 1                # Max zalgo/combining marks allowed
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("font_ban_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
intents.presences = True          # REQUIRED to read custom statuses / activities

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def is_standard_font(text: str) -> bool:
    """True only if text uses characters that render cleanly in Discord's standard font.
    
    If ENFORCE_ENGLISH_ONLY is True, also requires basic Latin/English characters only.
    """
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if not text:
        return True
    if not ALLOWED_PATTERN.match(text):
        return False
    combining = sum(1 for c in text if unicodedata.category(c) == 'Mn')
    if combining > MAX_COMBINING_MARKS:
        return False

    if ENFORCE_ENGLISH_ONLY:
        for char in text:
            try:
                name = unicodedata.name(char)
                if any(s in name for s in ['CYRILLIC', 'GREEK', 'CJK', 'ARABIC', 'HEBREW', 'HIRAGANA', 'KATAKANA', 'HANGUL', 'THAI', 'DEVANAGARI']):
                    return False
            except ValueError:
                continue
    return True


def get_custom_status(member: discord.Member) -> str | None:
    """Extract the text of a member's custom status if they have one set.
    Returns None if no custom status or no text.
    """
    # Primary activity first (most common for custom status)
    if isinstance(getattr(member, "activity", None), discord.CustomActivity):
        name = member.activity.name
        if name and isinstance(name, str) and name.strip():
            return name.strip()

    # Check the full activities list
    for act in getattr(member, "activities", []):
        if isinstance(act, discord.CustomActivity):
            name = act.name
            if name and isinstance(name, str) and name.strip():
                return name.strip()

    return None


async def log_action(guild: discord.Guild, message: str):
    logger.info(message)
    if LOG_CHANNEL_ID:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch:
            try:
                await ch.send(f"🔨 {message}")
            except Exception:
                pass


async def ban_member_safely(member: discord.Member, reason: str, current_sleep: float):
    """
    Attempts to ban one member.
    Handles rate limits dynamically and returns updated sleep time.
    """
    try:
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would ban {member} — {reason}")
            return True, current_sleep

        await member.ban(reason=reason, delete_message_days=0)
        return True, current_sleep

    except discord.RateLimited as e:
        sleep_time = min(e.retry_after + random.uniform(1.0, 3.0), MAX_BACKOFF)
        logger.warning(f"RateLimited on {member}. Sleeping {sleep_time:.1f}s (dynamic backoff)")
        await asyncio.sleep(sleep_time)
        return False, sleep_time

    except discord.HTTPException as e:
        if e.status == 429:
            retry = getattr(e, 'retry_after', current_sleep * 1.7)
            sleep_time = min(retry + random.uniform(1.0, 4.0), MAX_BACKOFF)
            logger.warning(f"HTTP 429 on {member}. Backing off {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
            return False, sleep_time
        logger.error(f"HTTP error banning {member}: {e}")
        return False, min(current_sleep * 1.3, MAX_BACKOFF)

    except discord.Forbidden:
        logger.error(f"Missing permissions to ban {member}")
        return False, current_sleep

    except Exception as e:
        logger.error(f"Unexpected error on {member}: {e}")
        return False, current_sleep


async def process_ban_batch(batch: list[discord.Member], guild: discord.Guild, current_sleep: float):
    """Process a batch of users with rate limit awareness."""
    banned_this_batch = 0
    new_sleep = current_sleep

    for member in batch:
        if ENFORCE_ENGLISH_ONLY:
            reason = "Non-standard font / non-English in name or custom status. Server policy: standard Discord font + English only."
        else:
            reason = "Non-standard font / fancy Unicode in name or custom status. Server policy: clean standard Discord font only."
        success, new_sleep = await ban_member_safely(member, reason, new_sleep)
        if success:
            banned_this_batch += 1
            await log_action(guild, f"Banned {member} (ID {member.id})")
        # Small random delay between individual bans inside the batch
        await asyncio.sleep(random.uniform(0.25, 0.65))

    # After batch, apply the (possibly increased) sleep
    if not DRY_RUN and banned_this_batch > 0:
        sleep_time = max(new_sleep, BASE_BATCH_SLEEP)
        logger.info(f"Batch of {len(batch)} done ({banned_this_batch} banned). Sleeping {sleep_time:.1f}s...")
        await asyncio.sleep(sleep_time)

    return banned_this_batch, new_sleep


@bot.event
async def on_ready():
    mode = "DRY RUN (reporting only)" if DRY_RUN else "LIVE BANNING"
    policy = "English-only + standard font" if ENFORCE_ENGLISH_ONLY else "Standard font only (non-English allowed)"
    logger.info(f"Large Server Font Ban Bot ready as {bot.user} | Mode: {mode} | Policy: {policy}")
    logger.info(f"Batch size: {BATCH_SIZE} | Progress every {PROGRESS_EVERY} members | Also scanning custom statuses")
    logger.info("Run !scanfonts in your server to begin the full scan.")


def is_authorized(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    return ctx.author.id in (ctx.guild.owner_id, OWNER_ID)


@bot.command(name="scanfonts", aliases=["scanfont", "checkfonts"])
@commands.check(is_authorized)
async def scanfonts(ctx: commands.Context):
    guild = ctx.guild
    mode = "DRY RUN — no bans will occur" if DRY_RUN else "LIVE — users will be banned"
    
    policy = "English-only + standard font" if ENFORCE_ENGLISH_ONLY else "Standard font only (non-English allowed)"
    await ctx.send(
        f"🔍 **Starting full server scan** for non-standard fonts **and custom statuses**.\n"
        f"**Policy:** {policy}\n"
        f"**Mode:** {mode}\n"
        f"Batch size: **{BATCH_SIZE}** | Progress updates every **{PROGRESS_EVERY}** members.\n"
        f"Rate limit handling: **dynamic backoff enabled**.\n"
        f"Starting scan now on **{guild.name}**..."
    )

    checked = 0
    banned_total = 0
    batch: list[discord.Member] = []
    current_sleep = BASE_BATCH_SLEEP
    last_progress = 0
    start_time = datetime.now()

    try:
        async for member in guild.fetch_members(limit=None):
            checked += 1

            if member.bot or member.id in (guild.owner_id, bot.user.id):
                continue

            fields_to_check = [
                member.name,
                getattr(member, "global_name", None),
                member.nick,
                member.display_name,
            ]

            # Also check custom status text (requires Presence Intent)
            custom_status = get_custom_status(member)
            if custom_status:
                fields_to_check.append(custom_status)

            needs_ban = any(field and not is_standard_font(str(field)) for field in fields_to_check)

            if needs_ban:
                batch.append(member)

            if len(batch) >= BATCH_SIZE:
                banned_in_batch, current_sleep = await process_ban_batch(batch, guild, current_sleep)
                banned_total += banned_in_batch
                batch = []

                if banned_total >= MAX_BANS_PER_RUN:
                    await ctx.send(f"🛑 Reached MAX_BANS_PER_RUN limit ({MAX_BANS_PER_RUN}). Stopping for safety.")
                    break

            if checked - last_progress >= PROGRESS_EVERY:
                elapsed_min = (datetime.now() - start_time).total_seconds() / 60
                await ctx.send(
                    f"📊 **Progress Update**\n"
                    f"Checked: **{checked:,}** members\n"
                    f"Banned so far: **{banned_total}** {'(dry run)' if DRY_RUN else ''}\n"
                    f"Time elapsed: **{elapsed_min:.1f} min**\n"
                    f"Current backoff: **{current_sleep:.1f}s**"
                )
                last_progress = checked

        # Process any remaining users in the last batch
        if batch:
            banned_in_batch, _ = await process_ban_batch(batch, guild, current_sleep)
            banned_total += banned_in_batch

    except Exception as e:
        await ctx.send(f"❌ Scan aborted due to error: {e}")
        logger.exception("Full scan failed")
        return

    elapsed_min = (datetime.now() - start_time).total_seconds() / 60
    final_msg = (
        f"✅ **Scan finished** on **{guild.name}**\n"
        f"Total members checked: **{checked:,}**\n"
        f"Users banned: **{banned_total}** {'(dry-run mode — no one was actually banned)' if DRY_RUN else ''}\n"
        f"Total time: **{elapsed_min:.1f} minutes**\n"
        f"Final backoff value used: {current_sleep:.1f}s"
    )
    await ctx.send(final_msg)
    logger.info(final_msg.replace("\n", " | "))


@bot.command(name="helpfonts")
async def helpfonts(ctx):
    policy = "English-only + standard font" if ENFORCE_ENGLISH_ONLY else "Standard font only (non-English scripts allowed)"
    await ctx.send(
        "**Large Server Standard Font Ban Bot Help**\n\n"
        f"`{PREFIX}scanfonts` — Owner-only command. Scans the entire server (names + custom statuses) in safe batches.\n"
        f"**Current policy:** {policy}\n\n"
        "**Recommended workflow for huge servers:**\n"
        "1. Edit the script and set `DRY_RUN = True`\n"
        "2. Run `!scanfonts` and review the report\n"
        "3. Set `DRY_RUN = False` and run again when ready\n\n"
        f"Current settings: Batch size = {BATCH_SIZE}, Progress every {PROGRESS_EVERY} members.\n"
        "Toggle `ENFORCE_ENGLISH_ONLY` at the top of the script to allow or block non-English names/statuses.\n"
        "The bot automatically backs off when Discord rate-limits it.\n"
        "**Note:** Custom status scanning requires the Presence Intent to be enabled in the Developer Portal."
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ This command is restricted to the server owner and the configured OWNER_ID.")
    else:
        logger.error(f"Command error: {error}")


if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord bot token.")
    else:
        mode = "DRY RUN" if DRY_RUN else "LIVE BANNING"
        print(f"Starting Large Server Font Ban Bot ({mode} mode)...")
        bot.run(BOT_TOKEN)#!/usr/bin/env python3
"""
Discord.py bot for VERY LARGE servers (50k–200k+ members).
Scans all members for non-standard fonts / non-English names and bans them.

Key features for large servers:
- Respects Discord rate limits dynamically (retry_after + adaptive backoff with jitter)
- Processes bans in configurable batches (BATCH_SIZE)
- Regular progress updates so you know it's working
- Dry-run mode (strongly recommended first run on huge servers)
- Exponential backoff when rate limited
- Safety cap (MAX_BANS_PER_RUN)

SETUP:
1. Enable "Server Members Intent" in Discord Developer Portal.
2. Invite bot with "Ban Members" permission.
3. pip install discord.py
4. Replace BOT_TOKEN and OWNER_ID below.
5. For huge servers: Set DRY_RUN = True first, run !scanfonts, review, then set to False.

The detection = characters that render cleanly in Discord's standard default font.
If ENFORCE_ENGLISH_ONLY = True (default), it also requires English/Latin characters only.
Set ENFORCE_ENGLISH_ONLY = False to allow other languages/scripts while still blocking zalgo/fancy Unicode.
"""

import discord
from discord.ext import commands
import re
import unicodedata
import asyncio
import logging
import random
from datetime import datetime

# ==================== CONFIGURATION - EDIT THESE ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
OWNER_ID = 123456789012345678          # Your Discord user ID
PREFIX = "!"
LOG_CHANNEL_ID = None                  # Optional: channel ID for ban logs

# === VERY LARGE SERVER SETTINGS ===
BATCH_SIZE = 15                        # Ban this many, then pause (10-25 recommended)
BASE_BATCH_SLEEP = 2.5                 # Base sleep after each batch (seconds)
MAX_BACKOFF = 60                       # Never sleep longer than this even on heavy rate limiting
DRY_RUN = False                        # True = report only, do NOT ban (use this first!)
MAX_BANS_PER_RUN = 3000                # Safety: stop after this many bans in one session
PROGRESS_EVERY = 2500                  # Send progress message every X members checked

ENFORCE_ENGLISH_ONLY = True            # Set to False to ALLOW non-English characters/scripts
                                       # (still blocks zalgo, fancy Unicode, and non-standard font rendering)

# Standard English / Discord default font characters only
ALLOWED_PATTERN = re.compile(
    r'^[A-Za-z0-9\s\.\_\-@#&\'"!?()\[\]{}:;,\\/+=*^%$~`|]+$'
)
MAX_COMBINING_MARKS = 1                # Max zalgo/combining marks allowed
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("font_ban_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def is_standard_font(text: str) -> bool:
    """True only if text uses characters that render cleanly in Discord's standard font.
    
    If ENFORCE_ENGLISH_ONLY is True, also requires basic Latin/English characters only.
    """
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if not text:
        return True
    if not ALLOWED_PATTERN.match(text):
        return False
    combining = sum(1 for c in text if unicodedata.category(c) == 'Mn')
    if combining > MAX_COMBINING_MARKS:
        return False

    if ENFORCE_ENGLISH_ONLY:
        for char in text:
            try:
                name = unicodedata.name(char)
                if any(s in name for s in ['CYRILLIC', 'GREEK', 'CJK', 'ARABIC', 'HEBREW', 'HIRAGANA', 'KATAKANA', 'HANGUL', 'THAI', 'DEVANAGARI']):
                    return False
            except ValueError:
                continue
    return True


async def log_action(guild: discord.Guild, message: str):
    logger.info(message)
    if LOG_CHANNEL_ID:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch:
            try:
                await ch.send(f"🔨 {message}")
            except Exception:
                pass


async def ban_member_safely(member: discord.Member, reason: str, current_sleep: float):
    """
    Attempts to ban one member.
    Handles rate limits dynamically and returns updated sleep time.
    """
    try:
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would ban {member} — {reason}")
            return True, current_sleep

        await member.ban(reason=reason, delete_message_days=0)
        return True, current_sleep

    except discord.RateLimited as e:
        sleep_time = min(e.retry_after + random.uniform(1.0, 3.0), MAX_BACKOFF)
        logger.warning(f"RateLimited on {member}. Sleeping {sleep_time:.1f}s (dynamic backoff)")
        await asyncio.sleep(sleep_time)
        return False, sleep_time

    except discord.HTTPException as e:
        if e.status == 429:
            retry = getattr(e, 'retry_after', current_sleep * 1.7)
            sleep_time = min(retry + random.uniform(1.0, 4.0), MAX_BACKOFF)
            logger.warning(f"HTTP 429 on {member}. Backing off {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
            return False, sleep_time
        logger.error(f"HTTP error banning {member}: {e}")
        return False, min(current_sleep * 1.3, MAX_BACKOFF)

    except discord.Forbidden:
        logger.error(f"Missing permissions to ban {member}")
        return False, current_sleep

    except Exception as e:
        logger.error(f"Unexpected error on {member}: {e}")
        return False, current_sleep


async def process_ban_batch(batch: list[discord.Member], guild: discord.Guild, current_sleep: float):
    """Process a batch of users with rate limit awareness."""
    banned_this_batch = 0
    new_sleep = current_sleep

    for member in batch:
        if ENFORCE_ENGLISH_ONLY:
            reason = "Non-standard font / non-English name. Server policy: standard Discord font + English only."
        else:
            reason = "Non-standard font / fancy Unicode name. Server policy: clean standard Discord font only."
        success, new_sleep = await ban_member_safely(member, reason, new_sleep)
        if success:
            banned_this_batch += 1
            await log_action(guild, f"Banned {member} (ID {member.id})")
        # Small random delay between individual bans inside the batch
        await asyncio.sleep(random.uniform(0.25, 0.65))

    # After batch, apply the (possibly increased) sleep
    if not DRY_RUN and banned_this_batch > 0:
        sleep_time = max(new_sleep, BASE_BATCH_SLEEP)
        logger.info(f"Batch of {len(batch)} done ({banned_this_batch} banned). Sleeping {sleep_time:.1f}s...")
        await asyncio.sleep(sleep_time)

    return banned_this_batch, new_sleep


@bot.event
async def on_ready():
    mode = "DRY RUN (reporting only)" if DRY_RUN else "LIVE BANNING"
    policy = "English-only + standard font" if ENFORCE_ENGLISH_ONLY else "Standard font only (non-English allowed)"
    logger.info(f"Large Server Font Ban Bot ready as {bot.user} | Mode: {mode} | Policy: {policy}")
    logger.info(f"Batch size: {BATCH_SIZE} | Progress every {PROGRESS_EVERY} members")
    logger.info("Run !scanfonts in your server to begin the full scan.")


def is_authorized(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    return ctx.author.id in (ctx.guild.owner_id, OWNER_ID)


@bot.command(name="scanfonts", aliases=["scanfont", "checkfonts"])
@commands.check(is_authorized)
async def scanfonts(ctx: commands.Context):
    guild = ctx.guild
    mode = "DRY RUN — no bans will occur" if DRY_RUN else "LIVE — users will be banned"
    
    policy = "English-only + standard font" if ENFORCE_ENGLISH_ONLY else "Standard font only (non-English allowed)"
    await ctx.send(
        f"🔍 **Starting full server scan** for non-standard fonts.\n"
        f"**Policy:** {policy}\n"
        f"**Mode:** {mode}\n"
        f"Batch size: **{BATCH_SIZE}** | Progress updates every **{PROGRESS_EVERY}** members.\n"
        f"Rate limit handling: **dynamic backoff enabled**.\n"
        f"Starting scan now on **{guild.name}**..."
    )

    checked = 0
    banned_total = 0
    batch: list[discord.Member] = []
    current_sleep = BASE_BATCH_SLEEP
    last_progress = 0
    start_time = datetime.now()

    try:
        async for member in guild.fetch_members(limit=None):
            checked += 1

            if member.bot or member.id in (guild.owner_id, bot.user.id):
                continue

            names_to_check = [
                member.name,
                getattr(member, "global_name", None),
                member.nick,
                member.display_name,
            ]

            needs_ban = any(name and not is_standard_font(str(name)) for name in names_to_check)

            if needs_ban:
                batch.append(member)

            if len(batch) >= BATCH_SIZE:
                banned_in_batch, current_sleep = await process_ban_batch(batch, guild, current_sleep)
                banned_total += banned_in_batch
                batch = []

                if banned_total >= MAX_BANS_PER_RUN:
                    await ctx.send(f"🛑 Reached MAX_BANS_PER_RUN limit ({MAX_BANS_PER_RUN}). Stopping for safety.")
                    break

            if checked - last_progress >= PROGRESS_EVERY:
                elapsed_min = (datetime.now() - start_time).total_seconds() / 60
                await ctx.send(
                    f"📊 **Progress Update**\n"
                    f"Checked: **{checked:,}** members\n"
                    f"Banned so far: **{banned_total}** {'(dry run)' if DRY_RUN else ''}\n"
                    f"Time elapsed: **{elapsed_min:.1f} min**\n"
                    f"Current backoff: **{current_sleep:.1f}s**"
                )
                last_progress = checked

        # Process any remaining users in the last batch
        if batch:
            banned_in_batch, _ = await process_ban_batch(batch, guild, current_sleep)
            banned_total += banned_in_batch

    except Exception as e:
        await ctx.send(f"❌ Scan aborted due to error: {e}")
        logger.exception("Full scan failed")
        return

    elapsed_min = (datetime.now() - start_time).total_seconds() / 60
    final_msg = (
        f"✅ **Scan finished** on **{guild.name}**\n"
        f"Total members checked: **{checked:,}**\n"
        f"Users banned: **{banned_total}** {'(dry-run mode — no one was actually banned)' if DRY_RUN else ''}\n"
        f"Total time: **{elapsed_min:.1f} minutes**\n"
        f"Final backoff value used: {current_sleep:.1f}s"
    )
    await ctx.send(final_msg)
    logger.info(final_msg.replace("\n", " | "))


@bot.command(name="helpfonts")
async def helpfonts(ctx):
    policy = "English-only + standard font" if ENFORCE_ENGLISH_ONLY else "Standard font only (non-English scripts allowed)"
    await ctx.send(
        "**Large Server Standard Font Ban Bot Help**\n\n"
        f"`{PREFIX}scanfonts` — Owner-only command. Scans the entire server in safe batches.\n"
        f"**Current policy:** {policy}\n\n"
        "**Recommended workflow for huge servers:**\n"
        "1. Edit the script and set `DRY_RUN = True`\n"
        "2. Run `!scanfonts` and review the report\n"
        "3. Set `DRY_RUN = False` and run again when ready\n\n"
        f"Current settings: Batch size = {BATCH_SIZE}, Progress every {PROGRESS_EVERY} members.\n"
        "Toggle `ENFORCE_ENGLISH_ONLY` at the top of the script to allow or block non-English names.\n"
        "The bot automatically backs off when Discord rate-limits it."
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ This command is restricted to the server owner and the configured OWNER_ID.")
    else:
        logger.error(f"Command error: {error}")


if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord bot token.")
    else:
        mode = "DRY RUN" if DRY_RUN else "LIVE BANNING"
        print(f"Starting Large Server Font Ban Bot ({mode} mode)...")
        bot.run(BOT_TOKEN)#!/usr/bin/env python3
"""
Discord.py bot for VERY LARGE servers (50k–200k+ members).
Scans all members for non-standard fonts / non-English names and bans them.

Key features for large servers:
- Respects Discord rate limits dynamically (retry_after + adaptive backoff with jitter)
- Processes bans in configurable batches (BATCH_SIZE)
- Regular progress updates so you know it's working
- Dry-run mode (strongly recommended first run on huge servers)
- Exponential backoff when rate limited
- Safety cap (MAX_BANS_PER_RUN)

SETUP:
1. Enable "Server Members Intent" in Discord Developer Portal.
2. Invite bot with "Ban Members" permission.
3. pip install discord.py
4. Replace BOT_TOKEN and OWNER_ID below.
5. For huge servers: Set DRY_RUN = True first, run !scanfonts, review, then set to False.

The detection = English only + characters that render in Discord's standard default font.
"""

import discord
from discord.ext import commands
import re
import unicodedata
import asyncio
import logging
import random
from datetime import datetime

# ==================== CONFIGURATION - EDIT THESE ====================
BOT_TOKEN = "TOKEN"
OWNER_ID = 239882051166142465          # Your Discord user ID
PREFIX = "!"
LOG_CHANNEL_ID = None                  # Optional: channel ID for ban logs

# === VERY LARGE SERVER SETTINGS ===
BATCH_SIZE = 15                        # Ban this many, then pause (10-25 recommended)
BASE_BATCH_SLEEP = 2.5                 # Base sleep after each batch (seconds)
MAX_BACKOFF = 60                       # Never sleep longer than this even on heavy rate limiting
DRY_RUN = False                        # True = report only, do NOT ban (use this first!)
MAX_BANS_PER_RUN = 3000                # Safety: stop after this many bans in one session
PROGRESS_EVERY = 2500                  # Send progress message every X members checked

# Standard English / Discord default font characters only
ALLOWED_PATTERN = re.compile(
    r'^[A-Za-z0-9\s\.\_\-@#&\'"!?()\[\]{}:;,\\/+=*^%$~`|]+$'
)
MAX_COMBINING_MARKS = 1                # Max zalgo/combining marks allowed
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("font_ban_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def is_standard_font(text: str) -> bool:
    """True only if text uses characters that render cleanly in Discord's standard font + English only."""
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if not text:
        return True
    if not ALLOWED_PATTERN.match(text):
        return False
    combining = sum(1 for c in text if unicodedata.category(c) == 'Mn')
    if combining > MAX_COMBINING_MARKS:
        return False
    for char in text:
        try:
            name = unicodedata.name(char)
            if any(s in name for s in ['CYRILLIC', 'GREEK', 'CJK', 'ARABIC', 'HEBREW', 'HIRAGANA', 'KATAKANA', 'HANGUL', 'THAI', 'DEVANAGARI']):
                return False
        except ValueError:
            continue
    return True


async def log_action(guild: discord.Guild, message: str):
    logger.info(message)
    if LOG_CHANNEL_ID:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch:
            try:
                await ch.send(f"🔨 {message}")
            except Exception:
                pass


async def ban_member_safely(member: discord.Member, reason: str, current_sleep: float):
    """
    Attempts to ban one member.
    Handles rate limits dynamically and returns updated sleep time.
    """
    try:
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would ban {member} — {reason}")
            return True, current_sleep

        await member.ban(reason=reason, delete_message_days=0)
        return True, current_sleep

    except discord.RateLimited as e:
        sleep_time = min(e.retry_after + random.uniform(1.0, 3.0), MAX_BACKOFF)
        logger.warning(f"RateLimited on {member}. Sleeping {sleep_time:.1f}s (dynamic backoff)")
        await asyncio.sleep(sleep_time)
        return False, sleep_time

    except discord.HTTPException as e:
        if e.status == 429:
            retry = getattr(e, 'retry_after', current_sleep * 1.7)
            sleep_time = min(retry + random.uniform(1.0, 4.0), MAX_BACKOFF)
            logger.warning(f"HTTP 429 on {member}. Backing off {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
            return False, sleep_time
        logger.error(f"HTTP error banning {member}: {e}")
        return False, min(current_sleep * 1.3, MAX_BACKOFF)

    except discord.Forbidden:
        logger.error(f"Missing permissions to ban {member}")
        return False, current_sleep

    except Exception as e:
        logger.error(f"Unexpected error on {member}: {e}")
        return False, current_sleep


async def process_ban_batch(batch: list[discord.Member], guild: discord.Guild, current_sleep: float):
    """Process a batch of users with rate limit awareness."""
    banned_this_batch = 0
    new_sleep = current_sleep

    for member in batch:
        reason = "Non-standard font / non-English name. Server policy: standard Discord font + English only only."
        success, new_sleep = await ban_member_safely(member, reason, new_sleep)
        if success:
            banned_this_batch += 1
            await log_action(guild, f"Banned {member} (ID {member.id})")
        # Small random delay between individual bans inside the batch
        await asyncio.sleep(random.uniform(0.25, 0.65))

    # After batch, apply the (possibly increased) sleep
    if not DRY_RUN and banned_this_batch > 0:
        sleep_time = max(new_sleep, BASE_BATCH_SLEEP)
        logger.info(f"Batch of {len(batch)} done ({banned_this_batch} banned). Sleeping {sleep_time:.1f}s...")
        await asyncio.sleep(sleep_time)

    return banned_this_batch, new_sleep


@bot.event
async def on_ready():
    mode = "DRY RUN (reporting only)" if DRY_RUN else "LIVE BANNING"
    logger.info(f"Large Server Font Ban Bot ready as {bot.user} | Mode: {mode}")
    logger.info(f"Batch size: {BATCH_SIZE} | Progress every {PROGRESS_EVERY} members")
    logger.info("Run !scanfonts in your server to begin the full scan.")


def is_authorized(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    return ctx.author.id in (ctx.guild.owner_id, OWNER_ID)


@bot.command(name="scanfonts", aliases=["scanfont", "checkfonts"])
@commands.check(is_authorized)
async def scanfonts(ctx: commands.Context):
    guild = ctx.guild
    mode = "DRY RUN — no bans will occur" if DRY_RUN else "LIVE — users will be banned"
    
    await ctx.send(
        f"🔍 **Starting full server scan** for non-standard fonts / non-English names.\n"
        f"**Mode:** {mode}\n"
        f"Batch size: **{BATCH_SIZE}** | Progress updates every **{PROGRESS_EVERY}** members.\n"
        f"Rate limit handling: **dynamic backoff enabled**.\n"
        f"Starting scan now on **{guild.name}**..."
    )

    checked = 0
    banned_total = 0
    batch: list[discord.Member] = []
    current_sleep = BASE_BATCH_SLEEP
    last_progress = 0
    start_time = datetime.now()

    try:
        async for member in guild.fetch_members(limit=None):
            checked += 1

            if member.bot or member.id in (guild.owner_id, bot.user.id):
                continue

            names_to_check = [
                member.name,
                getattr(member, "global_name", None),
                member.nick,
                member.display_name,
            ]

            needs_ban = any(name and not is_standard_font(str(name)) for name in names_to_check)

            if needs_ban:
                batch.append(member)

            if len(batch) >= BATCH_SIZE:
                banned_in_batch, current_sleep = await process_ban_batch(batch, guild, current_sleep)
                banned_total += banned_in_batch
                batch = []

                if banned_total >= MAX_BANS_PER_RUN:
                    await ctx.send(f"🛑 Reached MAX_BANS_PER_RUN limit ({MAX_BANS_PER_RUN}). Stopping for safety.")
                    break

            if checked - last_progress >= PROGRESS_EVERY:
                elapsed_min = (datetime.now() - start_time).total_seconds() / 60
                await ctx.send(
                    f"📊 **Progress Update**\n"
                    f"Checked: **{checked:,}** members\n"
                    f"Banned so far: **{banned_total}** {'(dry run)' if DRY_RUN else ''}\n"
                    f"Time elapsed: **{elapsed_min:.1f} min**\n"
                    f"Current backoff: **{current_sleep:.1f}s**"
                )
                last_progress = checked

        # Process any remaining users in the last batch
        if batch:
            banned_in_batch, _ = await process_ban_batch(batch, guild, current_sleep)
            banned_total += banned_in_batch

    except Exception as e:
        await ctx.send(f"❌ Scan aborted due to error: {e}")
        logger.exception("Full scan failed")
        return

    elapsed_min = (datetime.now() - start_time).total_seconds() / 60
    final_msg = (
        f"✅ **Scan finished** on **{guild.name}**\n"
        f"Total members checked: **{checked:,}**\n"
        f"Users banned: **{banned_total}** {'(dry-run mode — no one was actually banned)' if DRY_RUN else ''}\n"
        f"Total time: **{elapsed_min:.1f} minutes**\n"
        f"Final backoff value used: {current_sleep:.1f}s"
    )
    await ctx.send(final_msg)
    logger.info(final_msg.replace("\n", " | "))


@bot.command(name="helpfonts")
async def helpfonts(ctx):
    await ctx.send(
        "**Large Server Standard Font Ban Bot Help**\n\n"
        f"`{PREFIX}scanfonts` — Owner-only command. Scans the entire server in safe batches and enforces English-only + standard Discord font names.\n\n"
        "**Recommended workflow for huge servers:**\n"
        "1. Edit the script and set `DRY_RUN = True`\n"
        "2. Run `!scanfonts` and review the report\n"
        "3. Set `DRY_RUN = False` and run again when ready\n\n"
        f"Current settings: Batch size = {BATCH_SIZE}, Progress every {PROGRESS_EVERY} members.\n"
        "The bot automatically backs off when Discord rate-limits it."
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ This command is restricted to the server owner and the configured OWNER_ID.")
    else:
        logger.error(f"Command error: {error}")


if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord bot token.")
    else:
        mode = "DRY RUN" if DRY_RUN else "LIVE BANNING"
        print(f"Starting Large Server Font Ban Bot ({mode} mode)...")
        bot.run(BOT_TOKEN)
