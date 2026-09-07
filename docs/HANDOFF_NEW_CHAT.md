# Flight Bot handoff

Current implementation uses Naver Flights SSE as the sole price source.

Latest product scope:
- 20 persistent watch slots
- Telegram button-first UI
- ad-hoc one-time search without slot creation
- per-slot immediate search
- `/help` and `/?` help aliases
- direct round-trip TOP 5 with airline/flight/time details
- Docker-first deployment with `bash install.sh`
- FastAPI health/admin endpoints including `/admin/search`

Before merging changes, require CI success for Linux full suite, Windows harness, Docker build, and live container health check.
