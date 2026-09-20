# Rugby Union Monitor

Automated Rugby Union fixture and reminder bot for the dedicated Discord **Rugby** server.

## What it does

- Tracks men's and women's international Rugby Union.
- Includes 15s and HSBC SVNS 7s events.
- Shows fixture times in Queensland/AEST.
- Shows where to watch in Australia, separating paid, confirmed-free, and official free fallback checks.
- Posts a numbered weekly fixture list to Discord.
- Lets you select matches with `!watch`.
- Sends reminders for selected matches before kick-off.
- Checks Discord commands and reminders every 5 minutes using GitHub Actions.

## Discord

- Server: **Rugby**
- Text channel: **#general**
- Channel ID: `1551020299665940482`
- User ID: `1203632253398421539`

## Commands

```
!fixtures
!watch 1 3 5
!watch all
!unwatch 3
!list
!help
```

The weekly list is scheduled for Sunday morning Queensland time. Command and reminder checks run every 5 minutes.

## GitHub secret

The Discord bot token is stored as a repository Actions secret named:

`Rugby_DISCORD_BOT_TOKEN`

Do not commit the token to the repository.

## Data

## Viewing-source logic

The bot is Australia-first and uses official sources only.

- **Stan Sport** — primary paid Australian rugby service.
- **9Now / Nine Network** — confirmed free for Wallabies home Tests and matches against New Zealand when supported by Rugby Australia's current rights information.
- **RugbyPass TV** — official free World Rugby service. It is marked **confirmed free** only when a tournament-specific official page confirms it; otherwise it is an **official free check** because geographic rights can vary.
- **World Rugby YouTube** — checked as an official free fallback where event rights allow.
- **WXV** — the current World Rugby Australia-specific page names Stan Sport for all matches, so the bot does not incorrectly advertise RugbyPass TV as free in Australia.
- **HSBC SVNS** — Rugby Australia currently lists Australian coverage as exclusive to Stan Sport, so the bot does not label RugbyPass TV as confirmed free in Australia.

The Discord weekly list, `!list`, and match reminders all use the same broadcaster logic and include direct links.

## Data

The monitor combines:
- FixtureDownload international competition feeds.
- Curated current Wallabies and women's international fixtures where a suitable feed is not available.
- HSBC SVNS event dates.

The current seeded schedule includes September 2026 women's internationals, Wallabies v South Africa on 27 September, the October Bledisloe Tests, and the opening 2026/27 SVNS events.

## Manual run

In GitHub open **Actions → Rugby Monitor → Run workflow** and choose:
- `preview` — build the fixture list without posting.
- `weekly` — post the numbered weekly list.
- `poll` — process Discord commands and due reminders.
