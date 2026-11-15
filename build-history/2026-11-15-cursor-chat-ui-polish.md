I’m tracking this in the Project tracker as it unfolds — see Project Notes; shared files live in Context.

Web UI polish is on branch ui-polish for the /web styling pass (dark default, spacing, fonts, rounded controls). I’ll send the PR link and file list when it’s ready.



Correction: the worker is 
Web UI polish (ignore the earlier bad link).



UI polish is ready for review: 
#1

Dark is the first-open default (toggle still remembers your choice). Plus Jakarta Sans, 16px body, rounded surfaces, brighter dark theme, and tighter mobile spacing. Build passed.

Files: web/index.html, web/package.json, web/package-lock.json, web/src/main.tsx, web/src/index.css, web/src/App.tsx, and web/src/components/{Books,Briefing,BusinessNote,Cards,Glance,Ledger,Menu,Research,Sheets,Snapshot}.tsx




On the branch ui-polish (pull request #1), fix the Cash Quality card. Presentation only; do not change any calculations or data.
1. The sentence "Profit for this half-year is positive and operating cash flow is negative" is shown twice (main paragraph and red flag line). Show it once: keep the red flag line and remove it from the paragraph.
2. The period is shown twice ("Half-year 1 Apr 2026 to 30 Sep 2026" and "Half-year to 2026-09-30"). Show it once.
3. Free cash flow is shown in the paragraph and again as its own line. Show it once, as its own line, with the same rounded value everywhere.
4. Keep only one half-year caveat note.
5. The XBRL tag names under each line overflow the card and cause a horizontal scroll. Make them wrap (break-all or break-words), or hide them behind a small "details" toggle. No horizontal scrolling anywhere in the card.
6. Check the other cards (Balance sheet, Business, At a glance) for the same kind of repeated sentences and fix them the same way.
7. Run npm run build, then commit to the same branch so the pull request updates. Do not push to main.
Got it — presentation-only cleanup on the Cash Quality card (and the same pattern on the other cards) on ui-polish.



Cash Quality presentation cleanup is on 
#1 (commit bf46689). Duplicates removed, XBRL tags behind a Tag toggle, same treatment on Business and At a glance. Build passed.