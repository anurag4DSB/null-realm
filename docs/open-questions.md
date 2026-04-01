# Open Questions & Pending Decisions

Track items that came up during development but aren't blocking — revisit when relevant.

---

## UI / Chainlit Customization

**Config file**: `.chainlit/config.toml`

### Auto-scroll behavior (noticed Phase 03)
When a second message is sent, the viewport jumps to show the new question at the top. History is preserved (scroll up to see it), but the jump feels abrupt.

**Options**:
- `user_message_autoscroll = false` → viewport stays where you are
- `assistant_message_autoscroll = false` → doesn't jump during streaming
- Keep defaults (current) — this is how ChatGPT/Claude.ai behave

**Decision**: TBD — try toggling and see what feels better.

### Branding & theme
- `name = "Assistant"` → should change to `"Null Realm"` or project-specific name
- `default_theme = "dark"` → currently uses browser default, could force dark
- `layout = "wide"` → wider chat area, good for code/tool output
- `cot = "full"` → already shows chain-of-thought/tool steps (keep)
- `custom_css` → can point to `/public/custom.css` for deeper styling
- `logo_file_url` → add a Null Realm logo

**Decision**: Low priority. Apply branding when the core features are stable.

### Custom CSS ideas
- Style tool steps differently (highlight file_read, bash, etc.)
- Code block syntax highlighting theme
- Compact message spacing for longer conversations

---

## GKE Deployment Cadence

### When to deploy to GKE?
The plan doesn't specify when to push each phase to GKE. Current approach:
- Phase 01: deployed to GKE (observability, auth, ingress)
- Phase 02: deployed to GKE (chat UI, agent, LiteLLM)
- Phase 03: **Kind only** — not yet deployed to GKE

**Options**:
- Deploy after every phase completion
- Deploy only at milestones (e.g., after Phase 04 when multi-agent is ready)
- Deploy continuously (once Cloud Build trigger is connected)

**Decision**: Deploy after each phase for now (manual `docker buildx --platform linux/amd64 --push`). Connect Cloud Build trigger when ready for continuous deployment.

### What's needed for Phase 03 GKE deploy:
- [ ] NATS StatefulSet for GKE (`infra/k8s/gke/nats/`)
- [ ] Updated api-server with DATABASE_URL pointing to Cloud SQL
- [ ] Rebuild AMD64 images and push to Artifact Registry
- [ ] Run seed script on GKE api-server pod

---

## invoke binary missing

`uv run invoke build` stopped working — the `invoke` binary isn't found in the venv. Direct `docker build` works. Need to debug why `invoke` disappeared from the path.

**Workaround**: Use `docker build -t null-realm-api:latest -f Dockerfile.api .` directly.
**TODO**: Fix `tasks.py` / `invoke` installation.

---

> Add new items here as they come up. Move to `docs/architecture/decisions.md` once a decision is made.
