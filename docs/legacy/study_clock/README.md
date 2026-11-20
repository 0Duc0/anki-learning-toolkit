# Study Session Clock

Adds a clickable status-bar display and a native study-time dashboard.

Version 2.3 makes every status element independently configurable. Version
2.3.1 also keeps timer callbacks safe while a profile is closing. The
adaptive, polished dashboard follows Anki's light or dark palette.

- **Elapsed** is the configurable session stopwatch.
- **Focused** is review-screen time with an automatic inactivity pause.
- **Logged today** is Anki's capped per-answer time from the review log.
- **Last** and **Avg** show the latest capped answer time and the current
  session average. Each can be hidden independently and only appears while
  reviewing.
- **Current Session** splits focused live time by source deck.
- **Deck History** shows logged time and answer counts by current deck for today,
  7, 30, or 90 Anki days.

Open the dashboard from the status bar or from `Tools` → `Learning Toolkit` →
`Study Clock`. The add-on is informational only and never changes cards,
scheduling, or review history.

Version 2.4 normalizes malformed settings, avoids database polling during other
collection operations, and stops statistics polling after the first database
error until the profile is reopened. A failed timer callback stops its timer
instead of repeatedly raising dialogs. Sleep/full-sync gaps contribute to elapsed
time but not focused time. Queued callbacks tolerate destroyed Qt widgets.
