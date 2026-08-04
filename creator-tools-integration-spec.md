# Creator Tools — Integration Spec

Six text-in / text-out AI tools for content creators. All six deliberately avoid video processing and platform write-access, so none of them require TikTok/Instagram/YouTube API approval, OAuth, or rendering infrastructure. Each is a one-day no-code build.

**Status:** spec / pre-build
**Constraint:** no-code + AI only (Lovable/Bolt, Make.com, Airtable, Claude or OpenAI API, Gumroad/Lemon Squeezy/Whop)
**Core architectural rule:** the user pastes text in, the tool returns text out. Never connect to a creator's social account.

---

## 0. Shared Foundation (build this once, reuse for all six)

Everything below assumes a single shared shell. Build this first — roughly 2–3 hours — then each tool is a 2–4 hour add-on.

### 0.1 Common data flow

```
User pastes text
   ↓
Input validation (length cap, strip formatting)
   ↓
Tool-specific prompt template + user's saved Voice Profile
   ↓
LLM call (Claude / OpenAI)
   ↓
Structured output (JSON preferred for anything rendered as cards/lists)
   ↓
UI render + copy-to-clipboard on every block
   ↓
Deduct credit → log run to history
```

### 0.2 Shared components

| Component | Purpose | Notes |
|---|---|---|
| **Auth** | Email magic link | Whatever your no-code platform gives natively — don't build custom |
| **Voice Profile** | Per-user tone settings reused across all tools | Fields: niche, audience, tone sliders, banned words, 2–3 sample posts |
| **Credit ledger** | Meter usage without per-seat billing | Simple integer column; decrement on each run |
| **Run history** | Let users retrieve past outputs | Big retention lever — cheap to build, users expect it |
| **Copy-to-clipboard** | On every output block, individually | Non-negotiable UX. These tools exist to be copy-pasted |
| **Regenerate** | Re-run a single block, not the whole job | Costs 0 or 0.5 credits |
| **Export** | Copy-all as Markdown or plain text | Also enables the CSV path for the caption tool |

### 0.3 Voice Profile schema

```json
{
  "user_id": "string",
  "niche": "string",
  "audience": "string",
  "tone": ["conversational", "direct", "witty"],
  "banned_words": ["delve", "unlock", "game-changer", "in today's world"],
  "sample_content": ["...", "...", "..."],
  "default_platforms": ["linkedin", "x", "instagram"],
  "cta_style": "string"
}
```

Inject this into every system prompt. It's the main differentiator against people just using raw ChatGPT.

### 0.4 Recommended stack

| Layer | Pick | Fallback |
|---|---|---|
| App shell + UI | Lovable or Bolt | Softr on Airtable |
| Database | Supabase (Lovable-native) or Airtable | Google Sheets |
| LLM | Claude API | OpenAI |
| Orchestration | Direct API call from app | Make.com scenario if you need multi-step |
| Payments | Lemon Squeezy or Gumroad | Whop for community bundling |
| Landing page | Framer or Carrd | The app's own home route |

### 0.5 Cost model

Text-only calls are cheap. Assume roughly 2k–8k tokens in, 1k–3k out per run. Price so that a $12/mo plan with ~100 runs still clears a healthy margin — verify against current API pricing before you publish a plan, since rates change.

**Guardrails:** hard input cap (~15k words), rate limit per user per hour, and a monthly spend alert on the API key.

---

## 1. Newsletter/Blog → Social Repurposer

**Priority: 1 (build first)**

### Pain point
Writers finish a newsletter and then face hours of manual repurposing, or skip it entirely and let the work die in the inbox. The generic-AI version loses the frameworks and specificity that made the original good — that's the actual complaint, not "I can't write posts."

### Target user
Newsletter writers (Substack, beehiiv, Kit), bloggers, ghostwriters, solo consultants who publish long-form.

### v1 scope
Paste a newsletter or blog post → get back:
- 1 LinkedIn post (hook + body + CTA)
- 1 X/Twitter thread (5–9 posts, numbered)
- 3 short-form notes (Substack Notes / X standalone)
- 1 Instagram carousel outline (slide-by-slide copy)

Each block independently copyable and independently regenerable.

### Explicitly out of scope for v1
Scheduling, posting, image generation, analytics, multi-user workspaces.

### Input / output contract

**Input:** raw text (500–15,000 words), optional target platforms, optional "emphasize this angle" field.

**Output JSON:**
```json
{
  "linkedin": { "hook": "", "body": "", "cta": "" },
  "thread": [{ "n": 1, "text": "" }],
  "notes": ["", "", ""],
  "carousel": {
    "title": "",
    "slides": [{ "n": 1, "headline": "", "body": "" }],
    "caption": ""
  }
}
```

### Prompt design (the actual product)
The differentiator is instruction, not model choice. Bake in:
1. **Extract before you write.** First identify the piece's core argument, any named frameworks/models, the strongest concrete example, and the most contrarian line. Only then generate.
2. **Preserve named frameworks verbatim.** If the writer coined a term, it survives into every output.
3. **Don't summarize — re-angle.** Each output should stand alone and give value, not tease a click.
4. **Platform-native form.** LinkedIn: short paragraphs, line breaks, no hashtag spam. X: one idea per post, no "🧵" if the writer's samples don't use it. Notes: conversational, opinionated.
5. **Apply Voice Profile + banned words list.**
6. **No invented facts, stats, or quotes.** Only use what's in the source.

### Competitors & wedge
Repurpose.io, Taplio, Castmagic, plus raw ChatGPT. Wedge: framework preservation + voice matching + a flat cheap price against subscription-heavy suites. Niche hard on one persona (e.g. "for B2B newsletter writers") rather than serving everyone.

### Pricing
$12–19/mo, or a $29 one-time lifetime deal for the first 100 users to buy early traction and testimonials.

### Distribution
r/Substack, r/Newsletters, r/Blogging, Substack Notes, Indie Hackers, X writing community. Lead with the personal story ("I was losing 6 hours a week to this"), not the feature list.

### Feasibility & risk
**Build: ~3 hours on top of the shared shell.** Main risk is low differentiation — the moat is prompt quality and niche focus, so treat the prompt as the product and iterate it against real user content weekly.

---

## 2. Podcast/Video Transcript → Show Notes, Timestamps & Titles

**Priority: 2**

### Pain point
Show notes, chapters, and titles are post-production chores that get rushed or skipped. Existing tools want you to upload and host the audio; creators already have the transcript sitting right there.

### Target user
Podcasters, video podcasters, YouTubers who publish long-form.

### v1 scope
Paste a transcript (plain text, VTT, or SRT) → get:
- Episode summary (2–3 sentences)
- Show notes (bulleted key takeaways)
- Chaptered timestamps
- 8 title options
- 1 promo thread / social blurb

### Timestamp handling — the one real technical detail
- **SRT/VTT input:** parse timestamps directly. Chapters are accurate. This is the good path.
- **Plain text input:** you cannot invent timestamps. Either return chapter titles with no times and tell the user to fill them, or ask for an episode duration and mark estimates clearly as estimates. **Never fabricate precise timestamps** — this is the fastest way to lose trust.
- Format chapters as `00:00 Chapter title`, YouTube-compatible, first chapter always starting at `00:00`.

### Input / output contract

**Input:** transcript text or SRT/VTT paste, optional episode title, optional guest name.

**Output JSON:**
```json
{
  "summary": "",
  "show_notes": [""],
  "chapters": [{ "time": "00:00", "title": "", "estimated": false }],
  "titles": [""],
  "promo": ""
}
```

### Prompt design
- Chapter on topic shifts, not fixed intervals.
- Chapter titles are descriptive, 3–7 words, no clickbait.
- Show notes capture claims and takeaways, not a play-by-play.
- Titles: mix formats — question, number, contrarian claim, guest-name-forward.
- Attribute guest statements to the guest.
- Flag any moment that's obviously clip-worthy (bridges to Tool 6).

### Competitors & wedge
Descript, Castmagic, Swell AI. Wedge: no upload, no hosting, no waiting on processing — paste and go, at a fraction of the price. Positioning: *"You already have the transcript. Stop re-uploading your episode."*

### Pricing
$12–25/mo, or credit packs (e.g. 10 episodes for $19) since podcast cadence is weekly, not daily.

### Distribution
r/podcasting, r/podcasts, podcaster Facebook groups, Indie Hackers. Podcasters are unusually reachable — many list contact emails publicly.

### Feasibility & risk
**Build: ~3–4 hours.** Long transcripts may exceed comfortable context; chunk by section and merge. Risk: SRT parsing edge cases, and users expecting audio upload — set expectations on the landing page.

---

## 3. YouTube Title & Hook Idea Generator (pre-publish, niche-tuned)

**Priority: 3**

### Pain point
Packaging is the growth obsession for small and mid-size YouTubers. The incumbent extensions are heavy, browser-based, and priced for people further along; new creators want title ideas *before* they film, not SEO dashboards after.

### Target user
New and intermediate YouTubers, Shorts creators, faceless-channel operators.

### v1 scope
Enter topic + niche + optional target audience → get:
- 15 title options, each tagged with the formula used
- 5 hook scripts (first 10 seconds of the video)
- 3 thumbnail *text* suggestions (3–4 words max — text only, no image generation)

### Critical scope warning
Do **not** promise thumbnail A/B testing. YouTube ships native thumbnail testing in Studio; competing there is a dead end. Stay on the pre-publish ideation side, which YouTube does not serve.

### Formula library
Hardcode a labeled library and have the model generate against it, so output is varied rather than 15 versions of the same title:
`curiosity gap` · `number/list` · `contrarian` · `transformation` · `mistake/warning` · `comparison` · `time-bound challenge` · `question` · `authority/credential` · `beginner-framing`

Tag each generated title with its formula so users learn the patterns — this is a retention hook, not just decoration.

### Input / output contract

**Input:** topic, niche, audience level, optional past-video titles that performed well.

**Output JSON:**
```json
{
  "titles": [{ "text": "", "formula": "", "why": "" }],
  "hooks": [{ "text": "", "style": "" }],
  "thumbnail_text": [""]
}
```

### Prompt design
- Titles under 60 characters where possible (mobile truncation).
- No clickbait the video can't deliver on — one line per title on what the video must contain to honor the promise.
- If the user supplied past winners, mirror their structure.
- Hooks: state the payoff or the stakes in the first sentence. No "hey guys, welcome back."

### Competitors & wedge
vidIQ, TubeBuddy, Spotter Studio. Wedge: no browser extension, no channel connection, pre-production focused, niche-specific formula libraries, priced for creators who can't justify $30–99/mo.

### Pricing
$9/mo or credit packs. This audience is the most price-sensitive of the six — keep the entry price low and consider a free tier of 3 runs/month for word-of-mouth.

### Distribution
r/NewTubers, r/youtubers, r/SmallYoutubers, r/PartneredYoutube, YouTube creator Discords. Give value in the thread itself — post free title ideas for people's actual videos, link in profile.

### Feasibility & risk
**Build: ~2 hours.** Crowded space; low switching cost both directions. Requires no YouTube API at all, which is the entire point — sidesteps the 10,000 units/day quota wall and the compliance audit that kills most YouTube tool ideas.

---

## 4. AI Comment/DM Reply Assistant (paste-in, human-in-the-loop)

**Priority: 4**

### Pain point
Reply volume becomes a second job, and the emotional labor of staying "on" in the comments is a real and frequently voiced burnout driver. Creators want to stay responsive without it eating their evening.

### Target user
Growing creators on any platform, community managers, small brand accounts.

### v1 scope
Paste a batch of comments (one per line, up to ~50) → get a suggested on-brand reply for each, tone-matched to the Voice Profile, in a two-column review UI. User copies each reply back manually.

### Architectural rule — do not violate
**No auto-posting. No account connection. No DM automation.** The moment you connect to Instagram or TikTok you inherit App Review, advanced permissions, the customer-initiated messaging window, and posting caps — and you become a ToS liability. Copy-paste is not a limitation here; it's the product's legal and operational moat. It also keeps the tool platform-agnostic, which is a selling point.

### v1 feature set
- Batch paste → per-comment suggested reply
- Tone control per batch: warm / short / witty / professional
- **Auto-flag** comments that shouldn't get an AI reply: hostile, trolling, crisis/mental-health content, legal or medical questions, business inquiries. Surface these separately with "handle personally."
- Length control (one-liner vs. considered reply)
- Regenerate individual replies

The flagging feature matters more than the generation. It's the differentiator, and it's the ethically correct design — some comments genuinely need a human, and the tool should say so.

### Input / output contract

```json
{
  "replies": [
    {
      "comment": "",
      "suggested_reply": "",
      "flag": null,
      "flag_reason": ""
    }
  ]
}
```
`flag` ∈ `null | "hostile" | "sensitive" | "business" | "spam"`

### Prompt design
- Match the creator's voice; never sound like a support bot.
- Never invent facts about the creator's life, products, or opinions.
- Vary the replies — 30 comments should not get 30 near-identical responses.
- Never argue with hostile comments; flag instead.
- Where a comment shares something personal or painful, flag as sensitive rather than generating a reply.

### Competitors & wedge
Mostly agency/SMM tools that bundle this. Wedge: creator-first, voice-matched, zero account connection, works on every platform including ones with no API at all.

### Pricing
$9–15/mo.

### Distribution
r/socialmedia, r/SocialMediaMarketing, r/InstagramMarketing, r/NewTubers. Frame it around the burnout angle, which is what people actually post about.

### Feasibility & risk
**Build: ~3 hours.** Risk: users will ask for auto-posting — decline, and explain why in the FAQ. Second risk: AI replies that sound canned damage the creator's relationship with their audience, so the review step must be mandatory and the UI must never let someone bulk-accept without reading.

---

## 5. Multi-Platform Description/Caption + Hashtag Reformatter

**Priority: 5**

### Pain point
Same content, five platforms, five sets of conventions on length, tone, hashtags, and links. Creators either post one caption everywhere (underperforms) or manually rewrite five times.

### Target user
Short-form creators posting the same asset to TikTok, Reels, Shorts, plus X and LinkedIn.

### v1 scope
Paste one caption or video description → get platform-optimized versions for TikTok, Instagram, YouTube (Shorts + long-form description), X, and LinkedIn, each with platform-appropriate hashtag handling.

### Platform rules to hardcode
Character limits and hashtag conventions shift; store them in an editable config table rather than in the prompt so you can update them without touching the build.

| Platform | Style | Hashtags | Links |
|---|---|---|---|
| TikTok | Short, hook-first, casual | 3–5, in-caption | Not clickable in caption |
| Instagram | Hook line + break + body | 3–8, avoid spam blocks | Not clickable in caption |
| YouTube Shorts | Very short, keyword-aware | 2–3 | Clickable |
| YouTube long-form | Full description + timestamps + links | 2–3 | Clickable |
| X | One idea, punchy | 0–2 | Clickable |
| LinkedIn | Hook + line breaks + takeaway | 0–3 | Clickable, but deprioritized in-post |

### Input / output contract

```json
{
  "tiktok": { "caption": "", "hashtags": [""] },
  "instagram": { "caption": "", "hashtags": [""] },
  "youtube_short": { "title": "", "description": "", "hashtags": [""] },
  "youtube_long": { "description": "", "hashtags": [""] },
  "x": { "text": "" },
  "linkedin": { "text": "" }
}
```

### Prompt design
- Rewrite, don't truncate — a shortened caption should still be a complete thought.
- Hashtags should be relevant, not maximal. Explicitly instruct against hashtag walls.
- Preserve any CTA the user included; adapt its phrasing per platform.
- Respect Voice Profile and banned words.

### Competitors & wedge
Buffer, Later, Hootsuite — all bloated schedulers requiring account connections. Wedge: single-purpose, instant, no login to any platform, no scheduling. Sell it as the thing you use *before* you open the app.

### Pricing
$7–12/mo. Lowest-priced of the six; strongest candidate for a generous free tier that funnels into the others.

### Distribution
r/TikTokhelp, r/InstagramMarketing, r/socialmedia, r/SocialMediaMarketing.

### Feasibility & risk
**Build: ~2 hours** — the simplest of the six. Risk: highly commoditized. Best used as a free acquisition wedge into the paid tools rather than as a standalone business.

---

## 6. Stream/VOD → Clip-Moment Finder (text-based, no video processing)

**Priority: 6 (build last)**

### Pain point
Streamers sit on hours of VOD they'll never mine. Auto-clip tools do exist, but they miss context and jokes, produce irrelevant cuts, and the processing itself fails often enough that people give up on it.

### Target user
Twitch and YouTube live streamers, long-form video podcasters.

### v1 scope
Paste a transcript or captions file from a stream → get a ranked "moment map": timestamped candidates with a one-line reason and a suggested clip title. The creator jumps straight to those timestamps in their own editor.

### Critical positioning
**You do not produce video.** Say so on the landing page, above the fold. This is the single biggest expectation-management risk of the six. The pitch is: *"We find the moments. You cut them in 5 minutes instead of scrubbing for 3 hours."* Framed correctly, no-rendering is a feature — no processing queue, no failed exports, no credits burned on a bad render.

### Timestamp dependency
This tool is only useful with timestamped input (SRT/VTT, or Twitch/YouTube caption exports). Plain text without timestamps can't produce a usable moment map. Make timestamped input a hard requirement in the UI, with a short guide on exporting captions from Twitch VODs and YouTube.

### Input / output contract

**Input:** SRT/VTT or timestamped transcript. Optional: stream topic, clip length target (15s / 30s / 60s).

**Output JSON:**
```json
{
  "moments": [
    {
      "start": "01:12:40",
      "end": "01:13:15",
      "score": 8,
      "reason": "",
      "suggested_title": "",
      "type": "funny"
    }
  ]
}
```
`type` ∈ `funny | insight | reaction | story | hot_take | tutorial`

### Prompt design
- Rank by clip potential, return the top 10–15 for a multi-hour stream.
- Include ~10–20 seconds of lead-in so the clip has setup, not just punchline.
- Give a real reason per moment, not "this was interesting."
- Diversify types — don't return 15 funny moments.
- Note when a moment depends on visual context the transcript can't confirm, and mark it lower-confidence.

### Competitors & wedge
Opus Clip and similar auto-clippers, which handle rendering but are expensive, credit-metered, and prone to processing failures and context misses. Wedge: instant, cheap, never fails, human keeps editorial control.

### Pricing
$9–15/mo or credit packs by stream hour.

### Distribution
r/Twitch, r/streaming, streamer Discords, r/podcasting for the long-form video crowd.

### Feasibility & risk
**Build: ~4 hours** — the most involved, mainly because of caption parsing and chunking long transcripts. Risk: expectation mismatch (people expect clips), and transcript-only analysis genuinely misses visual gags. Be honest about the second one in the copy; it builds more trust than overclaiming.

---

## Build Order & Rollout

### Recommended sequence

| Order | Tool | Build time | Why here |
|---|---|---|---|
| 0 | Shared shell | 2–3 h | Everything depends on it |
| 1 | Newsletter → Social Repurposer | 3 h | Clearest paid demand, cleanest build |
| 2 | Transcript → Show Notes | 3–4 h | Reuses the transcript parser used later by #6 |
| 3 | Title & Hook Generator | 2 h | Fastest build, largest audience |
| 4 | Comment Reply Assistant | 3 h | Different audience, different acquisition channel |
| 5 | Caption Reformatter | 2 h | Free-tier acquisition wedge |
| 6 | Clip-Moment Finder | 4 h | Hardest; reuses #2's parser |

Tools 2 and 6 share transcript parsing. Tools 1, 3, and 5 share the generation-and-copy UI. Building in this order means each tool reuses something from the last.

### Validation gates
- **Gate 1:** Ship tool #1 alone. Do not build #2 until #1 has 10 paying users or ~$100 MRR within two weeks. If it can't clear that at a low price, the niche is too soft — change audience before adding features.
- **Gate 2:** If #1 clears, build #2 and #3 for the *same or adjacent* audience and bundle. Owning one audience beats collecting tools.
- **Gate 3:** Only build #4–#6 once you know which audience is actually paying, and pick the tools that serve them.

### Bundling
Once three or more ship, offer a single "Creator Toolkit" subscription rather than per-tool pricing. Shared credits across all tools. Bundle price around $19–29/mo. This raises LTV and makes the shared credit ledger pay for itself.

---

## Platform Constraints — Read Before Adding Any Feature

These are the rules that killed most of the ideas that didn't make this list. Any future feature request should be checked against them first.

- **TikTok Content Posting API:** unaudited clients are limited to a handful of users per 24h, posts restricted to private/self-only visibility, and an audit is required to lift it. TikTok's content-sharing guidelines explicitly disallow simple utility tools that just upload to accounts you manage. **Do not build TikTok posting.**
- **Instagram Graph API:** requires professional (Business/Creator) accounts, has per-24h publishing caps, and comment/DM management requires advanced permissions that must pass Meta App Review. Messaging is customer-initiated with a limited response window. **Do not build IG engagement automation.**
- **YouTube Data API v3:** default 10,000 units/day; a single search call costs 100 units, so ~100 searches exhausts the day. Quota increases require a compliance audit, and there's no paid quota tier. Spinning up multiple projects to multiply quota violates the ToS. **Avoid quota-heavy discovery/analytics features.**
- **Scraping:** don't scrape brand contact info, follower data, or competitor content. Legal and ToS exposure with no upside. Users supply their own inputs.
- **Native feature risk:** YouTube ships thumbnail A/B testing natively. Before building any feature, check whether the platform already gives it away free.

None of the six tools above touch any of these. That's by design — keep it that way.

---

## Open Decisions

- [ ] One combined app or six separate landing pages? (Recommend: one app, six routes, separate landing pages for SEO/positioning)
- [ ] Free tier vs. free trial — free tier likely better for #3 and #5, trial for the rest
- [ ] Claude vs. OpenAI — test both on the same 10 real inputs before committing
- [ ] Whether run history is free or paid-tier only
- [ ] Which single niche to anchor tool #1 on (the more specific, the better it converts)
