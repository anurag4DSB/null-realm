---
phase: 03-streaming-persistence
plan: 03-01
status: complete
completed: 2026-04-01
---

# Summary: 03-01 NATS JetStream + Real-Time Streaming Pipeline

## What Was Accomplished

1. **NATS JetStream on Kind** -- NATS 2.10-alpine StatefulSet with JetStream enabled. `AGENT_EVENTS` stream configured. Service on ports 4222 (client) and 8222 (monitoring).

2. **NATSBus messaging client** -- `NATSBus` class with `connect()`, `publish()`, `subscribe()` methods. Event schemas: `TextDeltaEvent`, `ToolUseEvent`, `ToolResultEvent`, `TaskCompleteEvent`. Subjects: `agent.{session_id}.events`, `ctrl.{session_id}`, `done.{session_id}`.

3. **Direct LangGraph streaming to WebSocket** -- LangGraph `astream_events(version="v2")` iterates over LLM token chunks and sends each directly to the WebSocket. Character-by-character streaming at ~8ms per character. Graceful fallback to `run_agent()` if streaming fails.

4. **Persistent WebSocket per Chainlit session** -- WebSocket opened once in `on_chat_start`, stored in `cl.user_session`, reused for all messages. Auto-reconnect on connection drop (ADR-006).

## Files Created

```
infra/k8s/system/nats/statefulset.yaml       # NATS 2.10-alpine with JetStream
infra/k8s/system/nats/service.yaml           # ClusterIP ports 4222, 8222
nullrealm/communication/__init__.py
nullrealm/communication/events.py            # Pydantic event schemas (4 types)
nullrealm/communication/nats_bus.py          # NATSBus client (pub/sub/connect)
```

## Files Modified

```
nullrealm/api/websocket.py    # Direct astream_events streaming, persistent WS
nullrealm/main.py             # NATS connection in lifespan (opt-in via NATS_URL)
ui/app.py                     # Persistent WebSocket, stream_token display
pyproject.toml                # Added nats-py, websockets dependencies
```

## Deviations from Plan

1. **NATS NOT used for streaming** -- The plan called for agent events to flow through NATS. In practice, the agent runs in-process in the API server, so NATS added latency and complexity for zero benefit. Switched to direct `astream_events()` streaming (ADR-002).
2. **NATS JetStream replay caused message duplication** -- New subscriptions on the same subject received old messages. Fixed by adding unique `msg_id` per request, but this added complexity that motivated the switch to direct streaming.
3. **Character splitting via NATS caused truncation** -- `asyncio.sleep(0.01)` per character in the NATS callback caused timeouts and silently truncated responses. Three async layers (agent -> NATS -> WebSocket) made debugging hard.
4. **websockets v16 breaking change** -- Removed `.closed` attribute. Switched to `.protocol` check for connection state.
5. **NATS connection opt-in** -- Gated by `NATS_URL` env var. If not set, API server skips NATS entirely (no error, no warning). Keeps GKE logs clean where NATS is not deployed.
6. **Single NATS replica** -- Plan called for 3 replicas. Deployed 1 for Kind (sufficient for dev).

## Verification Results

- [x] NATS pod Running on Kind with JetStream enabled
- [x] NATSBus client connects, publishes, and subscribes
- [x] Tokens stream character-by-character in Chainlit (~8ms per char)
- [x] Persistent WebSocket survives across multiple messages
- [x] Graceful fallback to full response if streaming fails
- [x] NATS monitoring endpoint returns connection info

## Next Step

**03-02**: PostgreSQL registry tables + CRUD API + seed data.
