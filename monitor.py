"""
Минимальный runtime-мониторинг: ожидание интервала, delta RX/TX,
чтение socket-соединений из /proc/net/* внутри контейнеров
"""

from __future__ import annotations

import ipaddress
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None

from collector import collect_traffic, get_docker_client

TCP_STATES = {
    "01": "ESTABLISHED",
    "02": "SYN_SENT",
    "03": "SYN_RECV",
    "04": "FIN_WAIT1",
    "05": "FIN_WAIT2",
    "06": "TIME_WAIT",
    "07": "CLOSE",
    "08": "CLOSE_WAIT",
    "09": "LAST_ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
}

PROC_FILES = (
    ("/proc/net/tcp", "TCP", "ipv4"),
    ("/proc/net/tcp6", "TCP", "ipv6"),
    ("/proc/net/udp", "UDP", "ipv4"),
    ("/proc/net/udp6", "UDP", "ipv6"),
)


def wait_interval(seconds: int) -> None:
    """Простое ожидание с обратным отсчётом."""
    for left in range(seconds, 0, -1):
        sys.stdout.write(f"\rОсталось: {left} сек...")
        sys.stdout.flush()
        time.sleep(1)
    if seconds > 0:
        print("\rИнтервал завершён.     ")


def calculate_traffic_delta(
    start: Dict[str, Dict[str, Any]],
    end: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Посчитать RX/TX за интервал
    Ключ результата — полный Docker ID контейнера
    """

    result: Dict[str, Dict[str, Any]] = {}

    container_ids = sorted(set(start.keys()) | set(end.keys()))

    for container_id in container_ids:
        start_item = start.get(container_id) or {}
        end_item = end.get(container_id) or {}

        start_rx = int(start_item.get("rx") or 0)
        start_tx = int(start_item.get("tx") or 0)

        end_rx = int(end_item.get("rx") or 0)
        end_tx = int(end_item.get("tx") or 0)

        if end_rx >= start_rx:
            rx = end_rx - start_rx
        else:
            # Контейнер мог быть перезапущен,
            # поэтому счётчик Docker сбросился
            rx = end_rx

        if end_tx >= start_tx:
            tx = end_tx - start_tx
        else:
            tx = end_tx

        name = (end_item.get("name") or start_item.get("name") or "unknown")

        error = (end_item.get("error") or start_item.get("error"))

        result[container_id] = {
            "name": name,
            "rx_kb": round(rx / 1024, 2),
            "tx_kb": round(tx / 1024, 2),
            "total_kb": round((rx + tx) / 1024, 2),
            "error": error,
        }

    return result


def get_host_info() -> Dict[str, float]:
    """Небольшая psutil-метрика для отчёта"""
    if psutil is None:
        return {"cpu_percent": 0.0, "ram_percent": 0.0}

    memory = psutil.virtual_memory()
    return {
        "cpu_percent": float(psutil.cpu_percent(interval=0.2)),
        "ram_percent": float(memory.percent),
    }


def _decode_ipv4(hex_ip: str) -> str:
    raw = bytes.fromhex(hex_ip)
    return str(ipaddress.IPv4Address(raw[::-1]))


def _decode_ipv6(hex_ip: str) -> str:
    raw = bytes.fromhex(hex_ip)
    reordered = b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4))
    return str(ipaddress.IPv6Address(reordered))


def _decode_ip(hex_ip: str, family: str) -> str:
    return _decode_ipv6(hex_ip) if family == "ipv6" else _decode_ipv4(hex_ip)


def _parse_endpoint(value: str, family: str) -> Tuple[str, int]:
    ip_hex, port_hex = value.split(":", 1)
    return _decode_ip(ip_hex, family), int(port_hex, 16)


def _skip_remote(ip_value: str, port: int) -> bool:
    if port == 0:
        return True
    try:
        address = ipaddress.ip_address(ip_value)
        return address.is_unspecified or address.is_loopback
    except ValueError:
        return True


def _parse_proc_net(text: str, protocol: str, family: str, container_id: str, container_name: str) -> List[Dict[str, Any]]:
    """Разобрать /proc/net/tcp или /proc/net/udp"""
    result: List[Dict[str, Any]] = []
    lines = text.splitlines()

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue

        try:
            local_ip, local_port = _parse_endpoint(parts[1], family)
            remote_ip, remote_port = _parse_endpoint(parts[2], family)
        except Exception:
            continue

        state = TCP_STATES.get(parts[3].upper(), parts[3].upper()) if protocol == "TCP" else "UDP"

        # LISTEN это просто открытый порт
        if state == "LISTEN" or _skip_remote(remote_ip, remote_port):
            continue

        # Для TCP берём только живые соединения. Так меньше шума в отчёте
        if protocol == "TCP" and state != "ESTABLISHED":
            continue

        result.append(
            {
                "container_id": container_id,
                "container": container_name,
                "protocol": protocol,
                "state": state,
                "local_ip": local_ip,
                "local_port": local_port,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
            }
        )

    return result


def collect_sockets(client: Optional[Any] = None) -> Dict[str, Any]:
    """Собрать socket-соединения из running-контейнеров"""
    client = client or get_docker_client()
    result: Dict[str, Any] = {"connections": [], "errors": []}

    for container in client.containers.list(filters={"status": "running"}):
        for file_path, protocol, family in PROC_FILES:
            try:
                exit_code, output = container.exec_run(["cat", file_path], stdout=True, stderr=True)
            except Exception as exc:
                result["errors"].append({"container": container.name, "file": file_path, "error": str(exc)})
                continue

            if exit_code != 0:
                continue

            text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
            result["connections"].extend(
                _parse_proc_net(
                    text=text,
                    protocol=protocol,
                    family=family,
                    container_id=str(container.id),
                    container_name=str(container.name),
                )
            )

    return result

def collect_interval(
    client: Any,
    seconds: int,
    sample_interval: float = 1.0,
    scan_sockets: bool = True,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Собирать трафик и сокеты в течение всего интервала"""

    if seconds < 0:
        raise ValueError("seconds не может быть меньше 0")

    if sample_interval <= 0:
        raise ValueError("sample_interval должен быть больше 0")

    # Последние доступные счётчики трафика
    # Они сохраняются даже после завершения контейнера
    last_traffic = collect_traffic(client)

    merged_scan: Dict[str, Any] = {"connections": [], "errors": []}

    seen_connections = set()
    seen_errors = set()

    deadline = time.monotonic() + seconds

    while True:
        # Обновляем только контейнеры, которые сейчас доступны
        # Данные уже завершившихся контейнеров остаются в last_traffic
        traffic_sample = collect_traffic(client)
        last_traffic.update(traffic_sample)

        if scan_sockets:
            scan = collect_sockets(client)

            for connection in scan.get("connections", []):
                key = (
                    connection.get("container_id"),
                    connection.get("container"),
                    connection.get("protocol"),
                    connection.get("state"),
                    connection.get("local_ip"),
                    connection.get("local_port"),
                    connection.get("remote_ip"),
                    connection.get("remote_port"),
                )

                if key not in seen_connections:
                    seen_connections.add(key)
                    merged_scan["connections"].append(connection)

            for error in scan.get("errors", []):
                key = (error.get("container"), error.get("file"), error.get("error"))

                if key not in seen_errors:
                    seen_errors.add(key)
                    merged_scan["errors"].append(error)

        remaining = deadline - time.monotonic()

        if remaining <= 0:
            break

        time.sleep(min(sample_interval, remaining))

    return last_traffic, merged_scan