# What to do right now

You're stuck in a hotel with time to kill. Here's the order of things you can actually make progress on from a hotel room, vs the things that need the Mac Mini.

## Can do from the hotel (right now)

1. **Sign up for Enable Banking** (Phase 1 of SETUP.md). Only needs a browser and your phone. Takes ~30 min once you're past the ID checks.
2. **Read through ARCHITECTURE.md and SETUP.md** — poke holes in anything that doesn't match how you actually work. Any change of mind is cheaper now than after I've written code.
3. **Open the pensions tracker** (`Pensions Dashboard/pensions_tracker.html`) and fill in the starting values for Scottish Widows and Mercer. Two minutes.
4. **Dig out the consent expiry date** from whatever Halifax/Lloyds relationship you already have set up (if any) so we don't accidentally overlap consents.

## Needs the Mac Mini (save for when you're home)

- Phase 2 onwards of SETUP.md — Python env, launchd, Claude Code scheduled tasks.
- Writing `fetch_halifax.py` — I'll do that once you've finished the Enable Banking signup and we know the exact auth shape.

## Things I'm blocked on until you've done Phase 1

- I can't write `fetch_halifax.py` yet because Enable Banking's exact auth flow (JWS headers, key format) varies slightly between app types, and I don't want to write 200 lines of Python guessing.
- Once you've signed up and have a sandbox working, paste me one successful sandbox response and I'll have the real poller written within a single session.
