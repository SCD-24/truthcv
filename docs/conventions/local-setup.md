# Local setup — 652384b2-fef2-4000-aaa2-95577cbd4cae

How this repo is set up and started on a developer machine.
Forestree runs the setup commands automatically when it creates a forest (an isolated worktree), and the run commands when someone asks to start the app.

## Setup

Run these once in a fresh checkout, in order.

### Pull images

```bash
docker compose pull
```

## Run

Start the app with any of these. They are long-lived: they keep running until stopped.

### Start the stack

```bash
docker compose up
```

---

Generated from `.forestree/runbook.json`, which is the source of truth. Edit it there (or in the Commands tab) rather than here — this file is overwritten on every save.
