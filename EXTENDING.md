# Extending PALM Messenger RAG with New Services

This project is designed so you can add new services without changing the core backend logic.

## How the system works

1. The backend reads `backend/config.json`.
2. Each enabled service is represented as one agent.
3. The orchestrator spawns those agents and asks them to fetch new data.
4. All fetched items are normalized and stored in ChromaDB.
5. The digest pipeline can then run over the combined data.

## Adding a new service

1. Add a new entry to `backend/config.json`.
2. Create a new connector in `backend/mcp_servers/` and expose a function named `fetch_new_<service>_messages`.
3. Register the new service type in `backend/agents/orchestrator.py` under `SERVICE_HANDLERS`.
4. If needed, add a short `description` to the service config.
5. Run `POST /sync` to verify the new service data is fetched and stored.

## Example service types

- `email` — personal inbox using IMAP
- `telegram` — personal Telegram using pyrogram

## Important behavior

- Only enabled services are run.
- Each agent fetches new items independently.
- If one service fails, the others still continue.
- New service data is stored in the same shared notification collection.
