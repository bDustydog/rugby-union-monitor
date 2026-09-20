# Rugby Union Monitor

Automated Rugby Union fixture and reminder bot for the dedicated Discord **Rugby** server.

## What it does

- Tracks men's and women's international Rugby Union.
- Includes 15s and HSBC SVNS 7s events.
- Shows fixture times in Queensland/AEST.
- Shows where to watch in Australia, including Stan Sport and confirmed free options such as 9Now.
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
