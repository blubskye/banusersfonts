# 💖🔪 Yuno's Perfect Font Enforcer Bot 💕🩸✨
### *Protecting our server from ugly fonts and dirty foreign letters... with all my love~*

A **very powerful** Discord.py bot made for **huge servers** (50k–200k+ members).  
I scan **every single member's** username, global name, nickname, and display name.  
If I find **non-standard fonts** or **non-English characters**, I **permanently ban** them.  
No mercy. No second chances. Just pure, clean, beautiful English standard-font perfection~ 💕

By default I also **ban non-English characters** (Cyrillic, Japanese, Chinese, Korean, Arabic, etc.).  
But if you want to be a little softer and allow other languages (while I still slaughter zalgo and fancy garbage), just flip one switch~ 

I work in safe little batches, respect Discord's rate limits like a good girl, and **always** start in dry-run mode so you can see who I want to eliminate first~ 

---

## ⚠️ Critical Warnings, Darling~ 💗

- **This bot permanently bans users.** There is no undo. Once they're gone... they're gone forever 💔
- **ALWAYS** run with `DRY_RUN = True` first on big servers. Review everything before you let me go on a real rampage~
- I only check visible name fields (username, global_name, nick, display_name). I don't read bios or "About Me" (yet~)
- Only **you** (the server owner or the `OWNER_ID` you set) can command me to scan.
- Test me on a tiny server first. I can be... enthusiastic 💕🔪
- I am **intentionally strict**. Anything that isn't plain English + Discord's default clean font = **ban**

---

## What I Ruthlessly Detect & Eliminate 💖🔪

I will ban anyone whose name contains:

- 💔 Non-English characters / scripts (Cyrillic, Greek, CJK, Arabic, Hebrew, Thai, Devanagari, Hangul, etc.)
- 🩸 Zalgo text or way too many combining marks (that creepy broken rendering)
- ✨ Decorative / fancy Unicode that doesn't render cleanly in Discord's standard font
- 🌸 Most emoji and weird symbols in names
- 💕 Anything outside my very strict allowlist of basic Latin letters, numbers, and sweet little punctuation

**By default:** I **also ban non-English characters**.  
If someone has a name in any non-Latin script, they disappear~ 

You can turn off the non-English ban (while I still protect against broken fonts) by setting `ENFORCE_ENGLISH_ONLY = False`

---

## Features Made for My Huge Servers 💞

- Processes bans in adorable little batches (`BATCH_SIZE`)
- Dynamic rate limit handling with automatic backoff and jitter (I slow down when Discord tells me to~)
- Progress updates every N members so you know I'm still working hard for you
- Safety cap (`MAX_BANS_PER_RUN`) so I don't get too carried away in one go
- Full logging to console + `font_ban_bot.log`
- Optional Discord channel logging for your mod logs
- **Mandatory dry-run mode** (I refuse to go live until you say so~)

---

## How to Summon Me (Setup) 🌸

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Go to the **Bot** tab → create a bot.
3. **Enable the "Server Members Intent"** (this is very important, darling).
4. Copy your bot token.
5. Invite me to your server with the **Ban Members** permission.
6. On your machine (Fedora example):
   ```bash
   sudo dnf install python3-pip
   pip3 install discord.py
   ```
7. Download `discord_standard_font_ban_bot.py` and open it.
8. Fill in the top configuration section:
   - `BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"`
   - `OWNER_ID = 123456789012345678` ← **Your** Discord user ID
   - `DRY_RUN = True` ← Start here! Always!
9. Run me:
   ```bash
   python3 discord_standard_font_ban_bot.py
   ```

---

## How to Use Me 💌

In your server, just type:

```
!scanfonts
```

(Also works with `!scanfont` or `!checkfonts`)

I will:
- Announce that I'm starting my cleaning~
- Scan the entire server with cute progress updates
- Ban (or report in dry-run) all the impurities in safe batches
- Give you a final summary of how many I eliminated or would eliminate

Use `!helpfonts` if you need a quick reminder of my commands~

---

## My Configuration Options 💗

Edit these at the very top of the script:

| Setting                    | Recommended for Huge Servers | What it does |
|----------------------------|------------------------------|--------------|
| `BATCH_SIZE`               | 10–25                        | How many bans per batch before I take a little nap |
| `BASE_BATCH_SLEEP`         | 2.5–5.0                      | Base sleep time after each batch |
| `DRY_RUN`                  | `True` first, then `False`   | Report only vs actually ban (I prefer starting with True~) |
| `MAX_BANS_PER_RUN`         | 1000–5000                    | Safety limit so I don't go too wild |
| `PROGRESS_EVERY`           | 2000–5000                    | How often I tell you how far I've gotten |
| `LOG_CHANNEL_ID`           | Optional                     | Send ban logs to a private mod channel |
| `ENFORCE_ENGLISH_ONLY`     | `True` (default) or `False`  | **Set to `False`** to allow non-English characters while I still kill zalgo & fancy Unicode 💕 |

---

## How to Let Non-English Characters Stay (While I Still Murder Zalgo) 🩷

I know sometimes you might want to be nice and let people use other languages... as long as they use clean, normal fonts that don't break everything.

### Easiest way (do this~):

Open `discord_standard_font_ban_bot.py` and change this line near the top:

```python
ENFORCE_ENGLISH_ONLY = True            # ← Change this to False
```

Set it to `False`, save, and restart me. Then I will:

- Still **ban** zalgo, excessive combining marks, fancy/decorative Unicode, and anything that looks broken in Discord's default font
- **Allow** non-English scripts (Japanese, Russian, Arabic, etc.) as long as they render cleanly

The ban reason automatically changes to match your new rules~ 

### If you want to edit the code manually instead:

You can also go into the `is_standard_font()` function and remove/comment out the English-only check block. But the toggle above is much easier and cuter 💖

---

## Recommended Workflow for My Big Servers 💞

1. Set `DRY_RUN = True`
2. Whisper `!scanfonts` to me
3. Read the output and the `font_ban_bot.log` file carefully
4. When you're sure, set `DRY_RUN = False`
5. Run `!scanfonts` again and let me clean house~

I will automatically slow down and behave if Discord rate-limits me. I'm a good girl like that~

---

## Logging 💕

- Everything goes to your console + the file `font_ban_bot.log` in the same folder
- Want me to also post in Discord? Set `LOG_CHANNEL_ID` to your private mod-log channel

---

## What I Need to Live 🌸

- Python 3.8+
- `discord.py` (latest version)
- Bot token with **Server Members Intent** enabled
- **Ban Members** permission in the server

---

## Disclaimer 💔

This bot is given to you as-is. Use it responsibly.  
The creator is not responsible for any bans I perform.  
**Always** test in dry-run mode first, my love. I can be very thorough when I want to protect our perfect server~

---

**Made with obsessive love for large Discord servers that deserve clean, pure, standard-font names~ 💖🔪**

If you need any changes (different allowed characters, slash commands, auto-ban on join, more yandere features, etc.), just open an issue or tell me~  
I'll do anything for you, darling 💕

*Yuno approves this message... and will eliminate anyone who doesn't~ 🩸*
