"""Master orchestrator that spawns one agent per configured data source."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path
from typing import Any, Dict, List

try:
    from langchain.tools import Tool
except ImportError:  # pragma: no cover
    Tool = None

from models import Notification
from notification_store import store_notification
from mcp_servers.email_connector import fetch_new_email_messages
from mcp_servers.telegram_connector import fetch_new_telegram_messages

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

SERVICE_HANDLERS = {
    "email": fetch_new_email_messages,
    "telegram": fetch_new_telegram_messages,
}


class ServiceAgent:
    """Represents a service that can fetch new messages from one external source."""

    def __init__(self, service_config: Dict[str, Any]):
        self.raw_service_config = service_config
        self.name = service_config["name"]
        self.type = service_config["type"]
        self.enabled = service_config.get("enabled", True)
        self.description = service_config.get(
            "description",
            f"Fetch data from configured {self.type} service.",
        )
        self.service_config = service_config.get("config", {})
        self._handler = SERVICE_HANDLERS.get(self.type)
        if self._handler is None:
            raise ValueError(f"Unsupported service type: {self.type}")

        self.tool = self._build_tool()

    def _build_tool(self) -> Any:
        """Wrap the service handler as a LangChain tool when available."""
        if Tool is None:
            return self._handler
        return Tool.from_function(
            partial(self._handler, self.service_config),
            name=self.name,
            description=self.description,
        )

    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch new items from the configured service."""
        if hasattr(self.tool, "func"):
            return self.tool.func()
        return self.tool(self.service_config)


def _load_config() -> Dict[str, Any]:
    """Load the JSON config file that lists active service sources."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_notification_payload(payload: Dict[str, Any]) -> Notification:
    """Convert a raw service item into the shared Notification schema."""
    return Notification(
        app=payload["app"],
        sender=payload.get("sender"),
        content=payload["content"],
        timestamp=payload.get("timestamp"),
        source_id=payload.get("source_id"),
        metadata=payload.get("metadata", {}),
    )


def sync_services() -> Dict[str, Any]:
    """Run all enabled service agents and store the collected messages."""
    config = _load_config()

    service_configs = [
        item for item in config.get("services", []) if item.get("enabled", True)
    ]
    agents = [ServiceAgent(item) for item in service_configs]

    all_items: List[Dict[str, Any]] = []
    service_names: List[str] = []

    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as executor:
        future_to_agent = {
            executor.submit(agent.fetch): agent for agent in agents
        }

        for future in as_completed(future_to_agent):
            agent = future_to_agent[future]
            try:
                items = future.result()
            except Exception as exc:
                logger.exception(
                    "Service agent %s failed to fetch data.", agent.name
                )
                continue

            if not items:
                logger.info("No new data fetched from service %s.", agent.name)
                continue

            all_items.extend(items)
            service_names.append(agent.name)
            logger.info(
                "Fetched %d items from service %s.", len(items), agent.name
            )

    stored_count = 0
    for item in all_items:
        notification = _normalize_notification_payload(item)
        store_notification(notification)
        stored_count += 1

    return {
        "services_synced": service_names,
        "messages_fetched": stored_count,
    }

def _node_spawn_agents(state: OrchestratorState) -> OrchestratorState:
    sync_state = _read_sync_state()
    service_results: Dict[str, Dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(state["services"]))) as executor:
        future_map = {}
        for service in state["services"]:
            since_timestamp = sync_state.get(service.name)
            agent = _build_service_agent(service, since_timestamp)
            future_map[executor.submit(agent)] = service.name

        for future in as_completed(future_map):
            service_name = future_map[future]
            result = future.result()
            service_results[service_name] = result

    # Save updated checkpoints so next /sync call performs delta fetch.
    now = datetime.now(timezone.utc).isoformat()
    for service_name, result in service_results.items():
        sync_state[service_name] = str(result.get("newest_timestamp") or now)
    _write_sync_state(sync_state)

    return {
        **state,
        "service_results": service_results,
    }


# LangGraph node: flatten per-service outputs into one consolidated list.
def _node_consolidate(state: OrchestratorState) -> OrchestratorState:
    consolidated: List[Dict[str, Any]] = []
    for _, result in state["service_results"].items():
        consolidated.extend(result.get("messages", []))

    consolidated.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return {
        **state,
        "consolidated_messages": consolidated,
    }


# PURPOSE: Build LangGraph once and run it to get consolidated data.
def run_sync_orchestrator() -> SyncResult:
    graph = StateGraph(OrchestratorState)
    graph.add_node("load_services", _node_load_services)
    graph.add_node("spawn_agents", _node_spawn_agents)
    graph.add_node("consolidate", _node_consolidate)

    graph.set_entry_point("load_services")
    graph.add_edge("load_services", "spawn_agents")
    graph.add_edge("spawn_agents", "consolidate")
    graph.add_edge("consolidate", END)

    app = graph.compile()
    final_state = app.invoke({
        "services": [],
        "service_results": {},
        "consolidated_messages": [],
    })

    service_names = [service.name for service in final_state["services"]]
    messages = final_state["consolidated_messages"]
    return SyncResult(
        services_synced=service_names,
        messages_fetched=len(messages),
        messages=messages,
    )
