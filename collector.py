"""
Минимальный сбор данных через Docker API
Файл отвечает только за список контейнеров и счётчики RX/TX
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import docker
except ImportError:  # demo-режим может работать без docker SDK
    docker = None


def get_docker_client() -> Any:
    """Создать Docker-клиент с понятной ошибкой для пользователя."""
    if docker is None:
        raise RuntimeError("Не установлен пакет docker. Выполните: pip install -r requirements.txt")
    try:
        return docker.from_env()
    except Exception as exc:
        raise RuntimeError("Docker не запущен или Python не может подключиться к Docker Desktop.") from exc


def _image_name(container: Any) -> str:
    tags = getattr(getattr(container, "image", None), "tags", None) or []
    return tags[0] if tags else "unknown"


def _network_details(attrs: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    raw = (attrs.get("NetworkSettings", {}) or {}).get("Networks", {}) or {}
    result: Dict[str, Dict[str, str]] = {}

    for network_name, network_info in raw.items():
        ipv4 = network_info.get("IPAddress") or ""
        ipv6 = network_info.get("GlobalIPv6Address") or ""
        result[network_name] = {
            "ip": ipv4 or ipv6,
            "ipv4": ipv4,
            "ipv6": ipv6,
        }

    return result


def _first_ip(networks: Dict[str, Dict[str, str]]) -> str:
    for item in networks.values():
        if item.get("ip"):
            return item["ip"]
    return "N/A"


def collect_containers(client: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Вернуть все контейнеры: running и stopped.
    Нам нужны stopped-контейнеры, чтобы понять, кто умер за интервал.
    """
    client = client or get_docker_client()
    containers = client.containers.list(all=True)
    result: List[Dict[str, Any]] = []

    for container in containers:
        try:
            container.reload()
        except Exception:
            pass

        attrs = getattr(container, "attrs", {}) or {}
        state = attrs.get("State", {}) or {}
        status = (state.get("Status") or getattr(container, "status", "unknown") or "unknown").lower()
        networks = _network_details(attrs)

        result.append(
            {
                "id": str(getattr(container, "id", "")),
                "short_id": str(getattr(container, "short_id", "")),
                "name": getattr(container, "name", "unknown"),
                "image": _image_name(container),
                "status": status,
                "running": bool(state.get("Running", status == "running")),
                "started_at": state.get("StartedAt"),
                "finished_at": state.get("FinishedAt"),
                "exit_code": state.get("ExitCode"),
                "ip": _first_ip(networks),
                "networks": sorted(networks.keys()),
                "network_details": networks,
            }
        )

    return sorted(result, key=lambda item: item["name"])


def collect_traffic(client: Optional[Any] = None) -> Dict[str, Dict[str, Any]]:
    """Снять Docker-счётчики трафика для running-контейнеров"""

    client = client or get_docker_client()
    result: Dict[str, Dict[str, Any]] = {}

    for container in client.containers.list(filters={"status": "running"}):
        container_id = str(getattr(container, "id", ""))
        container_name = str(getattr(container, "name", "unknown"))

        rx = 0
        tx = 0
        error = None

        try:
            stats = container.stats(stream=False) or {}

            for net_stats in (stats.get("networks") or {}).values():
                rx += int(net_stats.get("rx_bytes") or 0)
                tx += int(net_stats.get("tx_bytes") or 0)

        except Exception as exc:
            error = str(exc)

        result[container_id] = {
            "name": container_name,
            "rx": rx,
            "tx": tx,
            "error": error,
        }

    return result
