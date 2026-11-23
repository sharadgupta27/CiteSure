# Chapter 17: A free public demo, links that expire, and a test that needs no internet

*The last mile: put the app where anyone can click it, close the security gap you wrote down long ago, and test the one feature that needs the internet without the internet.*

**You will learn:** how to fit a whole app (database included) into one free container, why "it starts" and "it starts fast enough" are different problems, what a signed link is and why it beats putting a login token in a URL, how to test an internet feature offline, and one expensive mistake to avoid.
**You will build:** a single-container demo on a free host, short-lived download links, an offline "sample" research source, and three new browser tests.
**Time:** about 4 hours. **Code and files:** `deploy/demo/`, `render.yaml`, `backend/app/security.py`, `backend/app/api/routes_documents.py`, `backend/app/research/sample_papers.py`, `e2e/tests/public-lane.spec.ts`, `e2e/tests/download.spec.ts`, `docs/public-demo.md`.

---

## The problem

Three things were still open at the end of chapter 16:

1. **Nobody could try it.** "Clone the repository and run Docker" is a big ask for a recruiter with two minutes.
2. **A security item was marked "partly done".** Downloads needed a login, but the plan asked for *short-lived signed links*, and they did not exist.
3. **The public research lane had no browser test.** It talks to arXiv and friends, and CI has no business depending on someone else's server.

## Step 1: the whole app in one free container

Free hosting tiers give you **one container, 512 MB of memory and a tenth of a CPU**. CiteSure normally runs as five containers (database, migrations, API, worker, web server). So the demo puts all of them in one:

```text
one container
  Postgres 16 + pgvector   (listens on localhost only)
  API (uvicorn)            (localhost only)
  worker                   (background jobs)
  nginx on port 7860       (the only thing the internet sees)
```

A small shell script, `start.sh`, starts them in order and stops the container if any of them dies, so the host restarts it cleanly.

**Make it safe to be public.** The demo uses the fake models (no API key, so nobody can spend your money), the invented handbook, uploads switched off, public research switched off, and a fresh random login secret on every start. The demo passwords are public on purpose: they only open invented data, and every restart resets it.

> **Where should it run?** My first choice, Hugging Face Spaces, turned out to charge for Docker on my account. Because everything was one ordinary container, moving to Render took one small file, `render.yaml`. Keep your deploy target boring and portable.

## Step 2: "it starts" is not "it starts fast enough"

I tested the container with the free tier's exact limits:

```bash
docker run --rm -p 7860:7860 --memory 512m --cpus 0.1 citesure-demo
```

Memory was fine (about 300 MB). Start-up was not: **322 seconds**. The free tier sleeps after 15 quiet minutes, so the next visitor would stare at a blank page for five minutes.

Where did the time go? Every start created the database, ran the migrations and loaded 20 documents. That work gives the same result every time, so I moved it **into the image build**: the database is created and seeded once, when the image is made, and each start only launches the processes. Two smaller changes helped too:

- **Answer at once.** nginx starts first and serves a small "CiteSure is waking up" page that reloads itself. When the API answers its health check, the script switches nginx to the real app.
- **Do not compete for the CPU.** The worker starts *after* the API is ready, and the script no longer starts extra Python processes just to make a random string.

Result: the waking page in **4 seconds**, the app in **61 seconds**, using **190 MB**.

| Change | Start-up on 0.1 CPU |
|---|---|
| Seed at start-up | 322 s |
| Seed at build time, waking page, worker last | 61 s (page visible after 4 s) |

**The lesson:** measure with the real limits. On a normal laptop the first version started in under 20 seconds and looked fine.

## Step 3: download links that expire

Clicking **Download original** used to work like this: JavaScript fetched the file with your login token in a header, held the whole file in memory, then handed it to the browser. That works, but a large file sits in memory, and the browser cannot show its usual download progress.

The tempting shortcut is `<a href="/api/v1/documents/42/file?token=YOUR_LOGIN_TOKEN">`. **Never do this.** URLs end up in browser history, server logs and chat messages, and that token opens *everything* you can see for eight hours.

A **signed link** is the safe version. It is a small token that says "user U may download document D until 12:00:59", signed so nobody can change it:

```text
1. Browser:  POST /documents/42/download-link       (with the normal login)
   Server:   may this user read document 42?  yes → sign {user, doc 42, expires in 60 s}
             → { "url": "/api/v1/files/eyJ...", "expires_at": "..." }
2. Browser:  opens /api/v1/files/eyJ...             (no login header needed)
   Server:   valid signature? not expired? may this user STILL read document 42? → the file
```

Four details make it safe:

- **One purpose only.** The link is signed with a key derived just for links, so a link can never be used as a login token, and a login token can never be used as a link. There is a test for each direction.
- **Short.** 60 seconds by default (`FILE_LINK_TTL_SECONDS`, at most 15 minutes).
- **Checked twice.** Access is checked when the link is made *and* when it is used. If an admin removes you from the HR group, a link you made a second earlier stops working. A test proves exactly that.
- **No onward leaks.** The file is sent with `Referrer-Policy: no-referrer` and `Cache-Control: no-store`, on top of the earlier `attachment`, `nosniff` and `sandbox`.

What it does *not* do, said plainly: within its 60 seconds, a link works for whoever holds it, and it is not single-use (that would need a table of used links). Both are written in the threat model.

## Step 4: test an internet feature without the internet

The public lane sends keywords to arXiv, Crossref and others. A browser test that calls them would fail whenever one of them is slow, and it would hammer free services from every CI run.

The project already solved this once: **fake models** stand in for real ones in tests. So I added a **fake source**. `PUBLIC_SOURCES=sample` serves three invented papers from a file and never opens a network connection. Everything around it is real: the keyword preview, the egress guard, the answer, the citation checks, and the "what was sent" note.

Two guard rails stop the invented papers from being mistaken for real ones:

- every title starts with **[Sample]** and every link is on `example.org`, and
- the server **refuses to start** in production with `PUBLIC_SOURCES=sample`.

The browser tests then check, through the real UI:

1. **Published research:** the preview says the keywords are allowed, the answer cites `[Sample] Sparse attention for long sequences`, carries a **Public** badge, and says "keywords sent to sample".
2. **Personal data:** a question with an email address in it is **blocked** in the preview, and asking anyway sends **nothing**.

My first idea for test 2 was a sentence copied word for word from a company document. It was *not* blocked, and that was correct. Only keywords leave, and turning the sentence into keywords dropped "16" and "of", so no run of six words from the document survived. A failing test is sometimes the test being wrong. Read why before you "fix" the code.

## What went wrong (and what it taught me)

- **I spent real money by accident.** The development stack reads `.env` automatically, and mine pointed at OpenAI with a real key. My test run started a 40-question evaluation on the real model (96 calls) before I noticed in the worker log. Fix: run tests with an **empty env file** (`docker compose --env-file empty.env ...`) so only the fake models can load. The project notes already said this; I did not follow them. Make the safe way the default, for example with a script that always passes the empty env file.
- **Windows line endings broke a shell script.** A script saved with `\r\n` fails inside Linux with `bash\r: No such file or directory`. `.gitattributes` fixes it for anything checked out from git; files written locally still need care.
- **A security header disappeared.** In nginx, adding *any* `add_header` inside a `location` block silently drops *all* headers set for the whole server, including your Content-Security-Policy. Check headers with `curl -I` on every route, not only `/`.

## Recap

- One container, honest limits, measured with the host's real CPU and memory.
- Move repeatable work into the build so starts are fast.
- Never put a login token in a URL. Use a short, single-purpose, signed link, and check access again when it is used.
- Fake the outside world at the edge (a fake source, like a fake model), keep everything else real, and make the fake impossible to use in production.

## Try it yourself

1. Open the live demo, sign in as `employee@acme.example`, open a citation and click **Download original**. Copy the link from your browser's download list and open it two minutes later. What happens?
2. Run `docker run --cpus 0.1 --memory 512m` on any app you have built. How long does it take to answer its first request?
3. Start the development stack with `PUBLIC_RESEARCH_ENABLED=true PUBLIC_SOURCES=sample PUBLIC_LLM_PROVIDER=fake` and ask a question about hybrid search with the scope set to **Published research**.

**Next:** the series ends here. **Back to the index:** [The CiteSure series](00-series-index.md) · [Glossary](glossary.md)
