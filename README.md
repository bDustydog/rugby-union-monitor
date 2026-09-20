# Rugby Union Monitor

A GitHub-hosted rugby fixture monitor for Discord.

## What it does
- Tracks Rugby Union internationals for men and women.
- Includes 15s and 7s when available from the configured fixture sources.
- Posts a weekly numbered fixture list to Discord.
- Lets the configured Discord user choose matches to watch with simple commands.
- Sends same-day reminders for watched matches.
- Shows Stan as the preferred Australian paid service when applicable and only lists free streams when they are legitimate/official.

## Discord commands
Type these in the configured Rugby channel:
- `!watch 1 3 5` — watch fixtures 1, 3 and 5 from the latest weekly list.
- `!watch all` — watch all fixtures in the latest list.
- `!unwatch 3` — remove fixture 3.
- `!list` — show your current watch list.
- `!help` — show command help.

## Required GitHub Actions secrets
- `DISCORD_BOT_TOKEN` — token for the Discord bot added to your server.
- `DISCORD_CHANNEL_ID` — Rugby channel ID. Current target: `1551020296700698744`.
- `DISCORD_USER_ID` — your Discord user ID. Current target: `1203632253398421539`.

The repository stores no Discord token in code.

## Automation
GitHub Actions runs the monitor on a schedule:
- Weekly fixture digest.
- Frequent command/reminder checks.

Fixture-source coverage is deliberately configurable because rugby competitions use several feeds and broadcaster details can change.
