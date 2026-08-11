# Phase 0 posting plan

Where to post, in what order, and the exact text to use. Covers `STRATEGY.md` §5 items 1 and 2.

**This file lives in the product repo on purpose.** The site folder is deployed to Netlify by
dragging the whole directory, so anything in it is publicly readable. `README.md` was live at
`cbrin.holycrius.app/README.md` until 2026-08-10 and exposed the kill criterion and the failing
seek-error number to anyone who guessed the path. Do not move this file there.

---

## Before you post anything

1. **Redeploy the site.** The live version predates the checkout URL, the explainer video and
   the self-hosted fonts. Right now the page cannot take money.
2. **Enable Netlify form detection, then redeploy again.** Forms are registered at deploy time.
3. **Buy your own product at full price and refund yourself.** A discount code skips the card
   charge, the receipt and the redirect, which are the three things that have to work.
4. **Write down the date 14 days out.** That is your kill-criterion deadline.

## Facts you have to make true before you paste anything

The copy below contains claims about **you**, which I wrote as plausible filler. Every one of
them has to be true or replaced. A product positioned on being honest by design cannot open
its first conversation with an invented anecdote, and somebody will ask a follow-up question
you can't answer.

| Claim in the copy | Make it true or change it |
|---|---|
| "[YOUR NUMBER] hours of old episodes" | Use your real number. If you don't have an archive, drop the sentence and write from the position you actually have. |
| "every few months I try one of the auto-clip tools" | Only if you have. Name the one you used if you're asked. |
| "I got annoyed enough that I started building" | True as far as I know, but say it in your own words. |
| "I saw you have a few years of VODs still up" (DM) | Check each recipient before sending. |

If you have not personally hit this problem, the honest version is different and still works:
say you built it after watching the failure happen to someone else, or say you built it
because the engineering problem interested you. Both are fine. An invented war story is not.

## What counts

Ten **pre-orders** in 14 days, counted from the Gumroad dashboard. Waitlist signups are your
interview pool, not your signal. Do not add them together. If you find yourself wanting to,
that is the moment the gate is being moved.

## Rules that apply everywhere

- No performance numbers. Recall, accuracy, speed, none of it. Appendix A binds you until the
  15-video library is measured, and seek error currently misses its bar.
- No claim that a named competitor produces worse clips. You have not measured that. Their
  public pricing is a fact and is fair to cite.
- Lead with the problem. Mention the product when someone asks, not in the opening line.
- One community at a time. If the first post lands badly, fix the message before spending the
  second one.

---

## 1. Direct messages (start here)

The highest signal per unit of effort, and no ban risk. §5 item 2 needs ten interviews, and
buyers who came from a conversation are worth more than buyers who came from a link.

Find streamers and podcasters with large public back catalogues. Two hundred episodes, or a
Twitch channel with years of VODs still up.

Send around ten a day. Expect two or three replies.

### Who to contact

Not the big names. Anyone famous enough to recognise has a producer and an editor, will not
read a cold DM, and has already bought a solution. Targeting them wastes the two weeks.

The target is someone with a large archive **who still edits it themselves**. Filter on all
of these at once:

- 100+ episodes, or years of Twitch VODs still public. The pain has to exist.
- Still publishing. A dead show does not care.
- Under roughly 50K followers, so they read their own messages. This is the one that gets
  ignored, and it is the one that decides whether you get a reply.
- Solo or a two-person operation. If they pay an editor, the problem is already solved.
- Either already posts clips, which proves they want them, or conspicuously does not despite
  a big back catalogue, which proves the cost is too high.

### Where to find them

| Source | What it gives you |
|---|---|
| listennotes.com | 3.7M podcasts, 190M episodes, searchable, has an API |
| podchaser.com | 5.5M shows, filters, and credits so you can find who actually makes it |
| Twitch directory | Open channels in a category you know and check the VODs and Highlights tabs |
| **Your own Reddit thread** | The best source, and free. See below. |

Anyone who comments "yes, this happens to me every time" on your Reddit post has just
identified themselves as the exact target and started the conversation for you. Reply to
every one of them individually. That is a warmer lead than any list you could build, and it
is the cheapest path to the ten interviews §5 asks for.

### Which Discords

| Server | Size | Notes |
|---|---|---|
| The Podcasters Community | ~1K | Podcasters and audio engineers. Start here. |
| Podcasters for Podcasters | small | Networking, independent shows. |
| StreamScheme | 69K | Largest streamer server. Low signal, see below. |
| Nerd or Die | 14K | Live streaming tools and overlays. |
| Streamer Hub | 11K | Streaming and content creation. |

**Use the small servers first.** In a 69K-member server the self-promo channel scrolls past
in under a minute and nobody replies. In a 1K server people read the post. The two servers
§5 asks for should be the two small ones.

Invite links expire constantly. Search the server name rather than trusting a saved URL.

### DM text

```
Hi [name], I saw you have a few years of VODs still up.

I'm building a tool that goes through an old archive and pulls out the
clippable bits, and I'm trying to work out whether the problem I think
exists actually does.

Could I ask you two questions? What have you tried for clipping the back
catalogue, and what made you stop using it?

Not selling anything here. If you'd rather just reply in one line, that
helps too.
```

If they reply and the conversation goes well, then send the link. Not before.

### The follow-up, once they've answered

```
That's useful, thank you. The mid-sentence thing is the part I've been
working on: it cuts on sentence boundaries instead of a fixed window, so a
clip can't end before the payoff lands.

It runs on your own machine, so nothing gets uploaded and there's no credit
meter. It isn't finished. There's a pre-order at $49 with a full refund if
it slips, and honestly the refund promise is doing a lot of work there.

cbrin.holycrius.app if you want to look. No pressure either way, the
conversation was the useful part.
```

---

## 2. Creator Discords

Read the rules and post in the right channel. Most servers have a self-promo channel and will
remove product talk from the general ones. Spend a few days being present before you post.

Two servers, per §5. Podcasting and streaming communities are the fit.

### Discord text

```
Question for anyone sitting on a big archive.

When you run old episodes through an auto-clipper, how often do the clips
stop halfway through the sentence that made the moment worth clipping?

I have about [YOUR NUMBER] hours of old recordings and every tool I tried gave me
back a pile of clips where the joke has the setup and no punchline. I got
annoyed enough to start building something that cuts on sentence boundaries
instead.

Before I put more months into it: is this a real problem for other people
or have I just been unlucky?
```

Replace [YOUR NUMBER] with the real figure. See the table at the top.

---

## 3. Reddit

Stagger these. One subreddit, wait, read the response, then the next.

**r/podcasting**, **r/NewTubers**, **r/Twitch**. Also worth trying: **r/VideoEditing**,
**r/streaming**, **r/SmallYTChannels**.

Every one of these removes posts that read as product launches. The framing below is a
question, which is what §5 asked for and also what keeps the post up.

**Do not put the link in the post.** If people ask, reply with it in a comment. If nobody
asks, the message was wrong and that is worth knowing.

### Title

```
Does anyone else re-trim every clip the auto-clippers give you?
```

### Body

```
I have around [YOUR NUMBER] hours of old episodes sitting on a drive. Every few
months I try one of the auto-clip tools on them, and every time I get back
thirty vertical videos where half of them stop in the middle of the
sentence that made the moment worth clipping.

The joke has the setup and then it just ends. The story builds and gets cut
before it lands.

So I open the editor and re-trim by hand, which is the exact job I was
trying to skip. Meanwhile the rest of it stays untouched because going
through them costs either my evenings or a per-minute processing bill.

I got annoyed enough that I started building something for myself that cuts
on sentence boundaries instead of a fixed time window, and runs locally so
there's no upload queue.

Two questions for people with big archives:

Is the mid-sentence thing a common annoyance, or have I been unlucky with
the tools I picked?

And if you have a back catalogue you've never mined, what actually stopped
you? Time, cost, or something else?
```

### Comment to use if someone asks for the link

```
It's at cbrin.holycrius.app. Fair warning: it isn't finished. There's a
pre-order but there's no download yet, so if that reads as a red flag to
you, that's a reasonable read. Refund is full and no-questions if the date
slips or if I never ship it at all.
```

---

## 4. X and Bluesky

Low effort and low signal, but the video does the work. Post the 46 second explainer.

### Post text

```
Auto-clippers cut to a time window, so they'll happily end a clip halfway
through the sentence that made the moment worth clipping.

I've been building one that cuts on sentence boundaries instead. Runs on
your own machine, so the footage never gets uploaded.

cbrin.holycrius.app
```

Attach `assets/explainer.mp4`. On X, native video gets more reach than a link with a preview.

---

## Skip for now

**Hacker News and Product Hunt.** Both go badly for an unreleased paid product, and a Show HN
with no download is a bad first impression on an audience you might want later. If Phase 0
clears and there is a real build, they become worth doing.

---

## If the numbers come back

**Ten or more pre-orders.** Phase 0 clears. Move to Phase 1: build the rights-clear 15-video
library and hit the measurement bars, which is what earns the right to make the boundary claim
in public with numbers attached.

**Fewer than ten.** Stop, per §5. Refund everyone who bought. That is not a failure, it is the
answer you paid two weeks to get, and the codebase stays a strong portfolio piece either way.

**Nobody replies at all.** Different problem. That is a distribution failure rather than a
demand failure, and the fix is more conversations, not a better landing page.
