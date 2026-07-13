from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

RUNNING_STATUS = "running"
DEAD_STATUSES = {"exited", "dead"}


def _status(container: Optional[Dict[str, Any]]) -> str:
    if not container:
        return "removed"
    return str(container.get("status") or "unknown").lower()


def _is_running(container: Optional[Dict[str, Any]]) -> bool:
    if not container:
        return False
    return container.get("running") is True or _status(container) == RUNNING_STATUS


def _is_dead_or_stopped(container: Optional[Dict[str, Any]]) -> bool:
    if not container:
        return True
    return not _is_running(container) and _status(container) in DEAD_STATUSES


def _traffic(container: Dict[str, Any]) -> Dict[str, float]:
    return container.get("traffic") or {"rx_kb": 0.0, "tx_kb": 0.0, "total_kb": 0.0}


def _has_traffic(container: Dict[str, Any], noise_kb: float) -> bool:
    return float(_traffic(container).get("total_kb") or 0.0) > noise_kb


def _build_ip_index(containers: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Создать индекс: какому IP какой контейнер принадлежит"""

    index: Dict[str, Dict[str, str]] = {}

    for container in containers:
        container_id = str(container.get("id") or "")
        container_name = str(container.get("name") or "unknown")

        network_details = (container.get("network_details") or {})

        for network_name, details in network_details.items():
            for field in ("ip", "ipv4", "ipv6"):
                ip_value = details.get(field)

                if not ip_value:
                    continue

                index[str(ip_value)] = {
                    "container_id": container_id,
                    "container": container_name,
                    "network": str(network_name),
                }

    return index


def _attach_traffic(
    container: Dict[str, Any],
    traffic_delta: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Добавить контейнеру трафик по его Docker ID"""

    item = dict(container)

    container_id = str(item.get("id") or "")

    item["traffic"] = traffic_delta.get(
        container_id,
        {
            "name": item.get("name"),
            "rx_kb": 0.0,
            "tx_kb": 0.0,
            "total_kb": 0.0,
            "error": None,
        },
    )

    return item


def _dead_during_interval(
    start_by_id: Dict[str, Dict[str, Any]],
    end_by_id: Dict[str, Dict[str, Any]],
) -> Set[str]:
    """Вернуть ID контейнеров, умерших за интервал"""

    result: Set[str] = set()

    for container_id, start_container in start_by_id.items():
        end_container = end_by_id.get(container_id)

        if (_is_running(start_container) and not _is_running(end_container)):
            result.add(container_id)

    return result


def _make_actual_links(
    sockets: List[Dict[str, Any]],
    ip_index: Dict[str, Dict[str, str]],
    visible_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Построить реальные связи между контейнерами
    ID используются для внутренней логики
    Имена сохраняются для отчётов
    """

    links: Dict[Tuple[str, str, str, int], Dict[str, Any]] = {}

    for socket in sockets:
        scanned_id = str(socket.get("container_id") or "")

        scanned_name = str(socket.get("container") or "unknown")

        if not scanned_id:
            continue

        if scanned_id not in visible_ids:
            continue

        remote_ip = str(socket.get("remote_ip") or "")
        local_ip = str(socket.get("local_ip") or "")

        remote_info = ip_index.get(remote_ip)
        local_info = ip_index.get(local_ip)

        if not remote_info:
            continue

        remote_id = str(remote_info.get("container_id") or "")
        remote_name = str(remote_info.get("container") or "unknown")

        if not remote_id:
            continue

        if remote_id == scanned_id:
            continue

        if remote_id not in visible_ids:
            continue

        local_port = int(socket.get("local_port") or 0)
        remote_port = int(socket.get("remote_port") or 0)
        protocol = str(socket.get("protocol") or "TCP")

        source_id = scanned_id
        source_name = scanned_name

        target_id = remote_id
        target_name = remote_name

        target_port = remote_port

        if local_port < remote_port:
            source_id = remote_id
            source_name = remote_name

            target_id = scanned_id
            target_name = scanned_name

            target_port = local_port

        network_info = local_info or remote_info

        network = str(network_info.get("network", "unknown"))

        key = (source_id, target_id, protocol, target_port)

        if key not in links:
            links[key] = {
                "source_id": source_id,
                "target_id": target_id,
                "source": source_name,
                "target": target_name,
                "network": network,
                "protocol": protocol,
                "target_port": target_port,
                "type": "socket",
                "count": 0,
            }

        links[key]["count"] += 1

    return sorted(
        links.values(),
        key=lambda item: (
            item["source"],
            item["target"],
            item["target_port"],
        ),
    )


def _make_network_hints(containers: List[Dict[str, Any]], actual_links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Пунктирные линии: контейнеры в одной Docker-сети, но socket-связь не найдена"""
    actual_pairs = {frozenset((link["source_id"], link["target_id"])) for link in actual_links}
    hints: List[Dict[str, Any]] = []

    # Чтобы HTML не превращался в паутину, подсказки рисуем только на небольших стендах
    if len(containers) > 12:
        return hints

    for i in range(len(containers)):
        for j in range(i + 1, len(containers)):
            first = containers[i]
            second = containers[j]
            if not _is_running(first) or not _is_running(second):
                continue
            pair = frozenset((first["id"], second["id"]))
            if pair in actual_pairs:
                continue
            common = sorted(set(first.get("networks") or []) & set(second.get("networks") or []))
            if common:
                hints.append(
                    {
                        "source_id": first["id"],
                        "target_id": second["id"],
                        "source": first["name"],
                        "target": second["name"],
                        "network": common[0],
                        "protocol": "-",
                        "target_port": "-",
                        "type": "no_socket",
                        "count": 0,
                    }
                )

    return hints


def analyze_data(
    start_containers: List[Dict[str, Any]],
    end_containers: List[Dict[str, Any]],
    traffic_delta: Dict[str, Dict[str, Any]],
    socket_scan: Dict[str, Any],
    interval_seconds: int,
    stand_name: str,
    host_info: Optional[Dict[str, Any]] = None,
    noise_kb: float = 1.0,
) -> Dict[str, Any]:
    start_by_id = {str(item["id"]): item for item in start_containers}

    end_by_id = {str(item["id"]): item for item in end_containers}

    died_interval = _dead_during_interval(start_by_id, end_by_id)

    visible: List[Dict[str, Any]] = [_attach_traffic(container, traffic_delta) for container in end_containers]

    # Если контейнер был running в начале, а потом был удалён, его нет в end_containers,
    # но на графе его всё равно нужно показать красным
    for container_id in sorted(died_interval):
        if container_id not in end_by_id:
            removed_item = dict(start_by_id[container_id])

            removed_item["status"] = "removed"
            removed_item["running"] = False

            visible.append(_attach_traffic(removed_item, traffic_delta))

    visible_ids = {str(item["id"]) for item in visible}
    ip_index = _build_ip_index(list(start_containers) + list(end_containers))
    actual_links = _make_actual_links(
        sockets=socket_scan.get("connections", []),
        ip_index=ip_index,
        visible_ids=visible_ids,
    )
    linked_ids = {
                     link["source_id"]
                     for link in actual_links
                 } | {
                     link["target_id"]
                     for link in actual_links
                 }

    for container in visible:
        container_id = str(container["id"])

        if container_id in died_interval:
            container["life"] = "dead"
            container["dead_reason"] = "died_during_interval"

        elif _is_dead_or_stopped(container):
            container["life"] = "dead"
            container["dead_reason"] = "already_stopped_or_exited"


        elif _is_running(container) and (_has_traffic(container, noise_kb) or container_id in linked_ids):
            container["life"] = "alive"

        elif _is_running(container):
            container["life"] = "inactive"

        else:
            container["life"] = "stopped"

    # Пунктирные подсказки строим только между running-контейнерами
    # С exited/dead контейнерами связь не рисуем
    network_hints = _make_network_hints(visible, actual_links)
    links = actual_links + network_hints

    running_count = sum(1 for item in visible if _is_running(item))
    active_count = sum(1 for item in visible if item["life"] == "alive")
    inactive_count = sum(1 for item in visible if item["life"] == "inactive")
    dead_count = sum(1 for item in visible if item["life"] == "dead")

    return {
        "stand": stand_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "interval_seconds": interval_seconds,
        "host": host_info or {},
        "summary": {
            "running": running_count,
            "alive": active_count,
            "inactive": inactive_count,
            "dead": dead_count,
            "dead_during_interval": len(died_interval),
            "actual_links": len(actual_links),
            "network_hints": len(network_hints),
        },
        "containers": visible,
        "links": links,
        "socket_errors": socket_scan.get("errors", []),
        "note": "socket = реальная текущая связь; no_socket = общая Docker-сеть, но socket-связь не найдена.",
    }
