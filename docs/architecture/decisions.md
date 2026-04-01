# Architecture Decision Records

Decisions made during development, what worked, what didn't, and why.

---

## ADR-001: Subdomain routing over path-based routing

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Multiple services (Langfuse, Grafana, Jaeger, Chainlit) behind one Traefik ingress on GKE.

### What we tried first: path-based routing

```
34.53.165.155.nip.io/grafana/  → Grafana
34.53.165.155.nip.io/jaeger/   → Jaeger
34.53.165.155.nip.io/chat/     → Chainlit
34.53.165.155.nip.io/           → Langfuse
```

**Why it failed**:
- Grafana needed `serve_from_sub_path: true` + `root_url` config — worked but added complexity
- Jaeger v2 doesn't support `QUERY_BASE_PATH` the same way v1 did — UI loaded blank
- Chainlit has no sub-path support (Next.js/React SPA with root-relative asset paths)
- `stripPrefix` middleware stripped the path but static assets (CSS/JS) still requested from root `/`, which routed to the wrong service
- OAuth2 Proxy's multi-upstream path routing didn't work through Traefik (all requests matched `/` instead of `/grafana/`)

### What works: subdomain routing

```
34.53.165.155.nip.io            → Langfuse (via OAuth2 Proxy)
chat.34.53.165.155.nip.io       → Chainlit
grafana.34.53.165.155.nip.io    → Grafana
jaeger.34.53.165.155.nip.io     → Jaeger
api.34.53.165.155.nip.io        → FastAPI
```

**Why it works**:
- Each app thinks it's at root `/` — no sub-path configuration needed
- Static assets load correctly (relative to root)
- nip.io supports subdomains natively (`chat.34.53.165.155.nip.io` resolves to `34.53.165.155`)
- OAuth cookie set on `.34.53.165.155.nip.io` is shared across all subdomains
- Traefik uses `Host()` matching which is clean and unambiguous

**Trade-off**: Requires wildcard cookie domain (leading dot). Google OAuth redirect URI only needs the root domain.

---

## ADR-002: Direct LangGraph streaming over NATS streaming

**Date**: 2026-04-01
**Status**: Accepted (NATS ready for Phase 04)
**Context**: Stream LLM tokens from agent to Chainlit UI in real-time.

### What we tried first: NATS JetStream as message bus

```
Agent → NATS publish(text_delta) → API server subscribes → WebSocket → Chainlit
```

**Why it was problematic**:
- JetStream replays old messages on new subscriptions (same subject per session). Fixed by adding unique `msg_id` per request, but added complexity.
- Character-by-character splitting in the NATS callback (`asyncio.sleep(0.01)` per char) caused timeouts and truncated responses.
- Three layers of async (agent → NATS → WebSocket) made debugging hard — no errors logged, responses just silently truncated.
- The agent runs in-process in the API server anyway — NATS adds overhead for zero benefit at this stage.

### What works: direct streaming

```
Agent.astream_events() → WebSocket.send_text() → Chainlit.stream_token()
```

**Why it works**:
- One async loop: iterate over `astream_events(version="v2")`, send each chunk directly to WebSocket
- No middleman, no message replay issues, no character splitting needed
- LLM tokens arrive in natural chunks (words/phrases) which look smooth in the UI
- Graceful fallback: if streaming fails, returns full response via `run_agent()`

### NATS is still deployed and ready

NATS JetStream is running on Kind with the `AGENT_EVENTS` stream. The `NATSBus` client and event schemas (`TextDeltaEvent`, `ToolUseEvent`, `ToolResultEvent`, `TaskCompleteEvent`) are implemented. When Phase 04 moves agents to separate Argo pods, NATS becomes the bridge:

```
Argo pod (agent) → NATS → API server → WebSocket → Chainlit
```

The event schemas are the contract. Only the transport changes.

---

## ADR-003: OAuth2 Proxy as reverse proxy + ForwardAuth hybrid

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Protect all GKE services with Google OAuth login.

### Architecture

```
Browser → Traefik → Service
                 ↕
          ForwardAuth checks cookie via auth-redirect nginx
                 ↕
          OAuth2 Proxy (sets/validates cookie)
```

**Two modes**:
1. **Langfuse** (root domain): OAuth2 Proxy acts as reverse proxy (`--upstream=http://langfuse:3000/`). Handles the full login flow — unauthenticated users see Google sign-in.
2. **Other services** (subdomains): Traefik ForwardAuth middleware checks the OAuth cookie. If missing, `auth-redirect` nginx converts the 401 → 302 redirect to Google login.

### Why the auth-redirect nginx wrapper

Traefik's ForwardAuth returns the upstream's response as-is. When OAuth2 Proxy's `/oauth2/auth` returns 401 (not logged in), Traefik shows "Unauthorized" text instead of redirecting to login.

The `auth-redirect` nginx sits between Traefik and OAuth2 Proxy:
- Forwards to `/oauth2/auth` (proxy_pass)
- `proxy_intercept_errors on` catches the 401
- `error_page 401 = @login_redirect` returns 302 to `/oauth2/start?rd=<original_url>`
- User gets redirected to Google login, then back to their original page

### Cookie sharing

- Cookie domain: `.34.53.165.155.nip.io` (with leading dot for subdomain sharing)
- `--prompt=select_account` forces Google to show the account picker
- Login once at root domain → cookie valid for all subdomains

---

## ADR-004: GKE Autopilot constraints

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Running on GKE Autopilot (managed node pools).

### Constraints encountered

| Constraint | Impact | Fix |
|-----------|--------|-----|
| No `hostPID`, `hostNetwork`, privileged DaemonSets | `node-exporter` can't run | Disabled in Helm values |
| All containers must have resource requests | Pods rejected without them | Set requests on everything |
| Private nodes (no public IP) | Can't pull from external registries | Added Cloud NAT to VPC |
| ARM vs AMD64 images | Mac builds ARM, GKE runs AMD64 | `docker buildx --platform linux/amd64` |
| ReadWriteOnce PVC on rolling updates | Grafana Multi-Attach errors | Changed to `Recreate` deployment strategy |

### Cloud NAT

Private GKE nodes need Cloud NAT for outbound internet access (pulling images from `registry.k8s.io`, `docker.io`, `ghcr.io`). Added via Pulumi:
```python
gcp.compute.Router("null-realm-router", ...)
gcp.compute.RouterNat("null-realm-nat", nat_ip_allocate_option="AUTO_ONLY", ...)
```

---

## ADR-005: LiteLLM probe configuration

**Date**: 2026-04-01
**Status**: Accepted
**Context**: LiteLLM pod kept crashing on Kind and GKE.

### Problem

LiteLLM's `/health` endpoint runs a full model health check (calls the LLM API). With a 1-second timeout on the liveness probe, the check consistently timed out, causing K8s to kill the pod → CrashLoopBackOff.

### Fix

- Switched to `/health/readiness` (lighter check)
- `timeoutSeconds: 10` (up from 1)
- `initialDelaySeconds: 60` for liveness (LiteLLM startup is slow)
- `failureThreshold: 5` (give it more chances)
- Memory limit: 2Gi (LiteLLM `main-latest` image is heavy, OOMKills at 512Mi/1Gi)

---

## ADR-006: Persistent WebSocket per Chainlit session

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Chat messages were replacing each other in the UI.

### Problem

The original Chainlit app opened a new WebSocket connection per message:
```python
async with websockets.connect(f"{API_URL}/{session_id}") as ws:
    # send message, receive response
```

Each new connection reset the server-side context. Previous messages disappeared from the UI.

### Fix

Open WebSocket once in `on_chat_start`, store in session, reuse for all messages:
```python
@cl.on_chat_start
async def on_chat_start():
    ws = await websockets.connect(f"{API_URL}/{session_id}")
    cl.user_session.set("ws", ws)

@cl.on_message
async def on_message(message):
    ws = cl.user_session.get("ws")
    # reuse connection
```

Auto-reconnect if the WebSocket drops between messages.

---

## ADR-007: No silent failures — structured logging at every boundary

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Chat on GKE stopped responding with no errors in logs. Agent worked when tested directly inside the pod, but the Chainlit→API→LangGraph pipeline silently failed.

### Problem

The WebSocket handler caught exceptions with bare `except Exception: pass` or `except WebSocketDisconnect: pass`. When something went wrong (connection drop, streaming error, timeout), there was no log entry — just "connection open" then "connection closed".

Debugging required manual `kubectl exec` to test each component individually. With 4 services in the chain (Chainlit → API → LiteLLM → Claude), finding the broken link took too long.

### Rule

Every boundary in the pipeline must log:
1. **Entry**: what was received (message content, session ID)
2. **Exit**: what was sent (chunk count, completion status)
3. **Failure**: full exception with context (session ID, what was being attempted)

```python
# BAD — silent failure
except Exception:
    pass

# GOOD — observable failure
except Exception:
    logger.exception("Streaming failed for session %s", session_id)
```

### Applied to

- `nullrealm/api/websocket.py`: logs message received, streaming start/complete, chunk count, disconnect, every exception
- `nullrealm/communication/nats_bus.py`: logs connect/disconnect/publish failures
- `nullrealm/main.py`: logs NATS/DB init success or failure

### Future

Phase 04+ should add structured JSON logging with correlation IDs (session_id propagated through NATS → Jaeger → Langfuse) so traces can be followed across services.
