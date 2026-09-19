# Producer chat: see, reply, flag, block

Date: 2026-09-18. Research pass: 4 lenses (YouTube API, Twitch, detection methods, moderation practice), a design step against the code, a skeptic that overturned 10 claims. YouTube in v1; Twitch noted where it changes the shape.

**Bottom line**
- Everything needed on YouTube works with the OAuth grant the Broadcast page already holds. No re-link.
- Local owns the token, the reader, the verdicts and every platform call. Remote displays and stages commands.
- Software flags. People decide. Nothing is ever auto-deleted or auto-banned.
- Storage fits in settings keys until the cut-over; a real table can replace them later behind the same API.

---

## 1. What YouTube allows (verified)

- **Scope:** every live-chat method (list, insert, delete, bans, moderators) accepts the `youtube` scope already in `SCOPES` (`integrations/youtube_live.py:40`).
- **Chat id:** `go_live()` already asks `part=snippet` on `liveBroadcasts.insert`, which returns `snippet.liveChatId`. Per broadcast, so re-read each show. After a restart: `liveBroadcasts.list?mine=true` (1 unit), include `upcoming` because chat opens before OBS streams.
- **Reading works with a bare API key** for public chats. The reader must not die when the OAuth token fails.
- **No threaded reply.** `liveChatMessages.insert` has no parent id. A "reply" is a new message from the channel, `@Name` by convention. No pin or highlight API either, so "feature this comment" is local.
- **Quota:** 10,000 units/day. `list` is documented at 1 unit; insert, delete, ban, unban are 50 each; go-live spends ~250. Reports of 5 per `list` are unverified: label 5 as an *assumed* planning number until the Cloud project's Quotas page is read after show one.
- **`streamList`** exists as a chunked REST stream (`requests` with `stream=True`, no new dependency), but its cost is unpublished. Phase 3, behind a flag.
- **No moderation signals from the API.** Held-for-review, blocked words, slow mode, hidden users are Studio-only. The API gives only `isChatOwner / isChatModerator / isChatSponsor / isVerified` and `channelId`. Flagging and standing are ours.
- **Bans:** `temporary | permanent`. Always send `banDurationSeconds` (no documented default). Owners and moderators cannot be banned. No `liveChatBans.list`, so store the `ban_id`. Whether `permanent` equals Studio's "Hide user" is undocumented: test on show one.
- **Housekeeping:** `youtube.upload` is not on the device-flow allow-list yet links fine, and is redundant (`thumbnails.set` accepts `youtube`). Resolve before relying on that list.

**Twitch (later):** EventSub push instead of polling, a real `reply_parent_message_id`, delete within 6 h, timeouts 1 s to 14 d, AutoMod holds, blocked terms, Shield Mode, device grant. `websocket-client` is already a dependency; the record and command shapes below are platform-neutral.

---

## 2. Recommended design

**Reader (local)**
- `integrations/youtube_chat.py`, daemon thread from `boot.start_integrations`, skipped under `SP_INTEGRATIONS=0`.
- Poll `list` at `max(pollingIntervalMillis, poll_s)`: 8 s with a console open, 20 s idle, back off on empty pages.
- Record shape: `{seq, id, at, author{id, name, owner, mod, member}, type, text, flag, standing}`.
- Rules run synchronously per record; rows land in an in-memory deque (1,000).
- One `events.emit('chat', {kind, seq_from, seq_to})` per non-empty page. New topic in `events.TOPICS` and `topics.js`. Hints only, never bodies.
- Error branches: `quotaExceeded` → pause to Pacific midnight (`zoneinfo`; add `tzdata` to `requirements.win`); `rateLimitExceeded` → seconds back-off; `liveChatEnded` → clear id; rejected page token → refetch first page tagged `history`.
- **Hard reserve ~1,000 units:** reads stop there so go-live and actions keep working.
- Studio actions (`userBannedEvent`, `messageDeletedEvent`) mirrored into the audit as `actor=youtube:studio`.

**Endpoints (local, `require_dm`)**
- `routers/producer_chat.py` at `/ttrpg/producer/api/chat`: `GET ?since&lane`, `reply`, `delete`, `timeout`, `ban`, `unban`, `flag`, `flag/clear`, `feature`, `note`, `standing`, `forget`, `log`, `settings`, `export` (signed URL, local only), `connect`.
- YouTube calls use an 8 s timeout so a hung call never pins a threadpool token.
- `state_doc()` gains a small `chat` block: health, quota meter, counts, featured ids, permissions. Bodies stay out of the 5 s push.

**Remote**
- `relay_producer.py` sends a fire-and-forget `producer_chat` frame, coalesced to 1/s; a reset frame of the last 100 on `link_up` and when consoles go 0 → n.
- `chat_*` commands run on a **second executor queue**, so a slow YouTube call can never delay a Take. Docstring contract change in both repos.
- TTLs: delete / ban / unban 60 s; replies and short timeouts 15–20 s.
- Idempotency by `(action, channel_id, message_id)` within 60 s on top of command-id dedup: local and remote clicking the same user never double-charge quota.
- Remote side: `COMMANDS` gains the chat kinds; `producer_hub` keeps 300 records, dropped on `link_down`, session end, restart; `GET /producer/chat?since`; SSE `producer_chat` (already producer-only by prefix); a `pc-chat` card in `portal/producer.js`.
- **Chat push to remote is opt-in** (default off, or names and counts only). Reason: "DM" is any `role='dm'` account and every DM hash is pushed to the portal.

**Storage without tables**
- `tblAppSettings` JSON keys under one lock: `chat_settings`, `chat_standing:yt:<channel>`, `chat_audit:yt:<channel>` (append-only, capped 2,000), `chat_featured:s<sid>`.
- `tblEvents` carries hints only.
- `tblAppSettings` is merge-excluded in backup restore, so only replace-mode restore carries the ledger. Every backup zip now holds viewer ids: say so in the privacy note.
- After the cut-over: revision 0018 moves the blobs into real tables behind the same `moderation/ledger.py` API.

**Settings** (Broadcast page, under the YouTube card, dropdowns only)
- Chat on/off; poll intervals (estimate labelled "assumed"); quota-per-list assumption; AI triage opt-in and model; cast aliases and cast accounts (picked from recent chatters); lexicon extras; thresholds and decay; remote permissions; default timeout tier; retention (max 30 d).

**Surfaces**
- Collapsible Chat card in the console's reserved row 5.
- Chromeless `/ttrpg/chat` popout that does **not** count as a console: opening `/ttrpg/producer` flips OBS into Studio Mode, and a solo DM only wants chat.
- Throttled DM-facing chime for severity ≥ 2 cast attacks.

---

## 3. Flagging: layered, cheapest first, humans last

**0. Allow-list** — never flagged, never sent to Gemini
- `isChatOwner`, `isChatModerator`, `chat_settings.cast_channels`, standing `trusted`.
- Strongest guard is platform-side: make the cast channel moderators in Studio. YouTube itself refuses to ban them.

**1. Rules** (`moderation/normalize.py`, `rules.py`, stdlib, < 1 ms)
- Normalise: NFKC, vendored confusables map (~600 entries, NFKC-filtered), leetspeak, repeat collapse, casefold.
- Cast list rebuilt every 30 s from `_ordered_party()`, `player_name_for()`, `dm_name()` plus aliases, inside `session_scope()` (the thread has no request).
- Default aliases `DM`, `GM`, `the DM`. Common-word names (Hope, Rose) get a capitalised or `@`-only mode.
- Detectors: cast mention · insult / threat / identity lexicon · accusation patterns (`<name> is a cheater`, `should be fired`) · link and duplicate spam · brigade (first-seen accounts per minute, identical text from ≥ 2 accounts).

**2. Gemini** (`moderation/triage.py`, default **off**, copy: "viewer messages are sent to Google")
- Batches up to 20 `ambiguous` / `mention` rows every 5 s (~12 RPM → needs a paid Tier 1 key).
- Prompt carries three name lists and the rule: statements about the *character* are in-fiction unless they reach the real person's body, identity or conduct.
- `responseSchema` output `{id, target, kind, severity, quote}`. `generate_json` gains a `schema` argument; a `GeminiBlocked` error marks the batch "model refused, review" instead of failing.
- Models: `gemini-3.5-flash-lite` / `3.1-flash-lite` are stable ids at 2.5–3× less than `3.7-flash`, whose price doubles 2027-01-01. Never hard-code $/show.

**3. Human**
- Lanes: All | Cast | Flagged | Mod log.
- Badges read `attacks Carl (player)`, `accusation about the DM`, `threat`, `model refused`. Never "defamatory" or "toxic".
- **Defamation is a legal conclusion.** The operational proxy: *a factual-sounding accusation about the real person behind a cast name*, distinct from insults, threats and in-fiction talk.

**Why nothing is automatic**
- Banter ("I hope Thorin dies") hits threat lexicons. Twitch's own ML refuses to auto-ban for the same false-positive reason.
- YouTube developer policy caps stored API data at 30 days.
- Automation sets lane, badge and sort order only.

---

## 4. Blocking and community standing

**Ladder**
- delete → 5-min timeout (one click) → Studio tiers 10 s / 1 m / 5 m / 10 m / 30 m / 24 h → permanent.
- ≥ 30 min needs a typed reason. Permanent needs a modal with the quota cost line and a "never decays" checkbox.

**Strikes and standing** (`chat_standing`)
- Strikes carry weight and timestamp. Standing computed on read: weighted strikes within `decay_days` (60) ≥ 2 → `watch`; ≥ 4 or a ban row → `denied`; `trusted` set by hand.
- Derived only from logged producer actions. Never from message counts or model scores.
- Standing feeds severity: +1 on `watch`, 3 on `denied` ("banned account is back"). A returning account gets a one-click re-ban prompt, never an automatic 50 units: nothing can reconcile against Studio unhides.

**Audit** (append-only)
- `{at, actor 'local:<user>' | 'remote:<user>' | 'youtube:studio', executed_as, action, channel_id, message_id, duration, reason, result, units}` for every action, including feature, trust, forget, export and settings changes.
- Excerpts only on timeout / ban rows. Names and excerpts purged at 30 days. Ban rows keep ids and reason.
- Live feed via the `chat` topic. Export is an in-memory bundle behind `require_dm`, logged.

**Safeguards**
- Server-side refusal of timeout / ban on allow-listed ids (local-only override, logged "cast override").
- Replies to flagged rows refused.
- Featuring needs a cleared flag and a human click; auto-unfeatures on delete, reader pause or time limit; shows display name only.
- Permanent ban, unban, export and forget bound to `yt_linked_by` (stored at link time). Never from remote.
- Per-minute reply cap and per-show reply counter (replies publish as the DM's channel).
- Brigade "hide N accounts" lists the names and N × 50 units before acting.
- `forget(channel_id)` erases the entry.

**Policy rules to encode** (from the critic)
- Never automatic.
- Timeout before ban; 5-min is the one-click default.
- The cast is untouchable by default.
- Words, not verdicts, in every badge.
- Log every action, minimally.
- Nothing unreviewed reaches the stream.
- Viewer text leaves the box only by opt-in, in plain words.
- Quota is show-critical: keep the reserve, polling stops first, actions continue.

---

## 5. Effort and phasing

| Component | Side | Effort |
|---|---|---|
| `youtube_live.py`: liveChatId capture, channel-id backfill, typed errors, chat primitives | local | S |
| `integrations/youtube_chat.py` reader thread, quota reserve | local | M |
| `moderation/store.py`, `normalize.py`, `rules.py`, vendored JSON | local | M |
| `moderation/ledger.py`: standing, audit, purge, forget, export | local | M |
| `routers/producer_chat.py`, `state_doc.chat`, `chat` topic | local | M |
| Console card, `/ttrpg/chat` popout, Broadcast settings | local | L |
| `moderation/triage.py`, `gemini.py` schema + blocked handling | local | M |
| `relay_producer.py` frames, second executor, idempotency | local | M |
| Remote: commands, hub window, `/producer/chat`, portal card | remote | L |
| Feature hook (state, optional panel-note bridge) | local | S |
| Tests both suites, spec, PORT_CONTRACTS | both | M |

**Phases, each shippable**
1. **See and act, local only** (~3–4 days): primitives, reader, store, rules, ledger, endpoints, console card, settings. Read, reply, delete, timeout, ban, mod log, quota meter.
2. **Remote console and triage** (~2–3 days): `producer_chat` frames, chat commands, portal card, opt-in push, Gemini triage, popout.
3. **Overlay and streamList** (~1–2 days): featured-comment overlay in the live-content phase; `streamList` behind a flag once show-one quota is known; brigade panel.

---

## 6. Open questions for Eric

1. 8 s polling with a console open: acceptable? Will you read the Cloud quota page after show one and file for an increase?
2. Gemini triage default off; is a paid key available, and which model?
3. Bind permanent ban / unban / export / forget to `yt_linked_by` rather than local-vs-remote?
4. Chat push to remote: off, names and counts only, or full?
5. Row-5 card or right column? Is the `/ttrpg/chat` popout worth it for solo DMs?
6. Keep idle polling (~3 calls/min) with no console open, or stop?
7. Do the players and DM chat from their own accounts? If so, make them Studio moderators and pick their channels after show one.
8. Retention: 30 d for non-actioned data, 60 d decay, ban rows ids-only?
9. Panel-note bridge for "feature" before the overlay ships, only if the panel is not pushed to players: half a day?
10. Timeout ladder as Studio's six tiers, 5 min default?
11. Drop `youtube.upload` from `SCOPES` now that `youtube` covers `thumbnails.set`?
