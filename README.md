# Rugby Union Monitor

Automated Rugby Union fixture and reminder bot for the dedicated Discord **Rugby** channel.

## Current build

The repository now contains:
- Men's and women's international Rugby Union tracking.
- 15s plus HSBC SVNS event tracking.
- Brisbane/AEST fixture times.
- Stan Sport viewing information.
- Legitimate Australian free-stream information when confirmed (for example 9Now).
- A numbered weekly Discord fixture list.
- `!watch` selection commands.
- Automatic pre-match reminders.
- Scheduled GitHub Actions.

Configured Discord targets:
- Rugby channel: `1551020296700698744`
- User: `1203632253398421539`

## Discord commands

```
!fixtures
!watch 1 3 5
!watch all
!unwatch 3
!list
!help
```

The weekly list is posted Sunday morning Brisbane time. The monitor then checks hourly for your commands and for selected matches that are within 12 hours of kickoff.

## Data

The monitor combines:
- FixtureDownload international competition feeds.
- Curated current Wallabies/WXV fixtures for competitions not exposed in those feeds.
- Current HSBC SVNS event dates.

The current seeded schedule includes the September 2026 WXV round, Wallabies v South Africa on 27 September, the October Bledisloe Tests and the opening 2026/27 SVNS events.

## One remaining setup item

Create a Discord bot, add it to the server with permission to **View Channel**, **Read Message History** and **Send Messages**, then add its token in:

`GitHub repository → Settings → Secrets and variables → Actions → New repository secret`

Secret name:

`DISCORD_BOT_TOKEN`

Until that secret exists, scheduled GitHub runs safely skip the Discord posting step instead of failing.

## Manual test

In GitHub open **Actions → Rugby Monitor → Run workflow**.

Choose:
- `preview` to test the fixture build without Discord.
- `weekly` to post the numbered list after the Discord token is configured.
- `poll` to process Discord commands/reminders.
