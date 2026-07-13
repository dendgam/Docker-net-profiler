"""
Три отчёта: JSON, Markdown и HTML-граф
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

NODE_W = 280
NODE_H = 92
CANVAS_W = 1050
CANVAS_H = 650


def _ensure_parent(filename: str) -> None:
    parent = Path(filename).parent
    if str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _traffic_text(container: Dict[str, Any]) -> str:
    traffic = container.get("traffic") or {}
    rx = traffic.get("rx_kb", 0.0)
    tx = traffic.get("tx_kb", 0.0)
    return f"▼ {rx} KB | ▲ {tx} KB"


def _ip_text(container: Dict[str, Any]) -> str:
    return str(container.get("ip") or "N/A")


def _node_class(life: str) -> str:
    return {
        "alive": "alive",
        "inactive": "inactive",
        "dead": "dead",
        "stopped": "dead",
    }.get(life, "inactive")


def _node_label(life: str) -> str:
    return {
        "alive": "активен",
        "inactive": "живой, нет трафика",
        "dead": "мёртвый / остановлен",
        "stopped": "остановлен",
    }.get(life, life)


def _layout(containers: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    """Простая круговая раскладка"""
    n = max(len(containers), 1)
    cx = CANVAS_W / 2
    cy = CANVAS_H / 2 + 10
    radius = 210 if n <= 4 else 250
    result: Dict[str, Tuple[float, float]] = {}

    for idx, container in enumerate(containers):
        angle = -math.pi / 2 + idx * 2 * math.pi / n
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        result[str(container["id"])] = (x, y)

    return result


def _edge_points(
    start: Tuple[float, float],
    end: Tuple[float, float],
) -> Tuple[float, float, float, float]:
    """Провести линию от границы одного контейнера до границы другого."""

    x1, y1 = start
    x2, y2 = end

    dx = x2 - x1
    dy = y2 - y1

    distance = math.hypot(dx, dy)

    if distance == 0:
        return x1, y1, x2, y2

    ux = dx / distance
    uy = dy / distance

    offsets = []

    if abs(ux) > 1e-9:
        offsets.append((NODE_W / 2) / abs(ux))

    if abs(uy) > 1e-9:
        offsets.append((NODE_H / 2) / abs(uy))

    boundary_offset = min(offsets)

    gap = 8

    offset = boundary_offset + gap

    sx = x1 + ux * offset
    sy = y1 + uy * offset

    ex = x2 - ux * offset
    ey = y2 - uy * offset

    return sx, sy, ex, ey


def generate_json_report(data: Dict[str, Any], filename: str) -> None:
    _ensure_parent(filename)
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def generate_markdown_report(data: Dict[str, Any], filename: str) -> None:
    _ensure_parent(filename)
    summary = data.get("summary", {})
    with open(filename, "w", encoding="utf-8") as file:
        file.write(f"# Docker Network Profiler — {data.get('stand')}\n\n")
        file.write(f"Интервал: **{data.get('interval_seconds')} сек.**\n\n")
        file.write(
            f"Running: **{summary.get('running', 0)}**, "
            f"активных: **{summary.get('alive', 0)}**, "
            f"без трафика: **{summary.get('inactive', 0)}**, "
            f"мёртвых/остановленных: **{summary.get('dead', 0)}**, "
            f"умерли за интервал: **{summary.get('dead_during_interval', 0)}**, "
            f"реальных связей: **{summary.get('actual_links', 0)}**.\n\n"
        )

        file.write("## Контейнеры\n\n")
        file.write("| Контейнер | Состояние | Статус Docker | IP | Трафик |\n")
        file.write("|---|---|---|---|---|\n")
        for container in data.get("containers", []):
            traffic_md = _traffic_text(container).replace("|", "\\|")
            file.write(
                f"| `{container.get('name')}` | {_node_label(container.get('life'))} | "
                f"{container.get('status')} | `{_ip_text(container)}` | {traffic_md} |\n"
            )

        file.write("\n## Связи\n\n")
        links = data.get("links", [])
        if not links:
            file.write("Связи не найдены.\n")
        for link in links:
            if link.get("type") == "socket":
                file.write(
                    f"- `{link.get('source')}` → `{link.get('target')}`: "
                    f"{link.get('protocol')}:{link.get('target_port')} socket\n"
                )
            else:
                file.write(
                    f"- `{link.get('source')}` — `{link.get('target')}`: "
                    f"общая сеть `{link.get('network')}`, socket не найден\n"
                )


def generate_html_report(data: Dict[str, Any], filename: str) -> None:
    _ensure_parent(filename)
    containers = data.get("containers", [])
    links = data.get("links", [])
    positions = _layout(containers)

    svg_parts: List[str] = []
    node_parts: List[str] = []

    for link in links:
        source = link.get("source_id")
        target = link.get("target_id")
        if source not in positions or target not in positions:
            continue

        sx, sy, ex, ey = _edge_points(positions[source], positions[target])
        mid_x = (sx + ex) / 2
        mid_y = (sy + ey) / 2 - 8

        if link.get("type") == "socket":
            color = "#00ff3b"
            width = 4
            dash = ""
            marker = "arrow-green"
            label = f"{link.get('protocol')}:{link.get('target_port')}"
        else:
            color = "#777777"
            width = 2
            dash = 'stroke-dasharray="7 8"'
            marker = "arrow-gray"
            label = "нет socket"

        svg_parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="{color}" stroke-width="{width}" {dash} marker-end="url(#{marker})" />'
        )
        svg_parts.append(
            f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" class="edge">{html.escape(str(label))}</text>'
        )

    for container in containers:
        x, y = positions[str(container["id"])]
        left = x - NODE_W / 2
        top = y - NODE_H / 2
        css_class = _node_class(str(container.get("life")))
        title = html.escape(str(container.get("image", "")))
        name = html.escape(str(container.get("name")))
        ip = html.escape(_ip_text(container))
        traffic = html.escape(_traffic_text(container))
        life = html.escape(_node_label(str(container.get("life"))))

        node_parts.append(
            f'<div class="node {css_class}" style="left:{left:.1f}px;top:{top:.1f}px" title="{title}">'
            f'<div class="name">📦 {name}</div>'
            f'<div>IP: {ip}</div>'
            f'<div>{traffic}</div>'
            f'<div class="life">{life}</div>'
            f'</div>'
        )

    summary = data.get("summary", {})
    host = data.get("host", {})
    content = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Docker Network Profiler</title>
  <style>
    body{{margin:0;background:#1b1b1b;color:white;font-family:Arial,sans-serif}}
    .header{{padding:18px 24px 8px}}
    h1{{margin:0 0 8px;font-size:24px}}
    .small{{color:#ccc}}
    .legend{{display:flex;gap:16px;flex-wrap:wrap;padding:8px 24px 12px;color:#ddd;font-size:14px}}
    .dot{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px}}
    .g{{background:#00ff3b}} .x{{background:#ffd24a}} .r{{background:#ff4545}}
    .canvas{{position:relative;width:{CANVAS_W}px;height:{CANVAS_H}px;margin:0 auto 24px;background:#1b1b1b}}
    svg{{position:absolute;left:0;top:0;width:{CANVAS_W}px;height:{CANVAS_H}px;z-index:1}}
    .node{{position:absolute;z-index:2;width:{NODE_W}px;height:{NODE_H}px;box-sizing:border-box;border-radius:9px;background:#2d2d2d;padding:11px 14px;text-align:center}}
    .node.alive{{border:3px solid #00ff3b}}
    .node.inactive{{border:3px solid #ffd24a;color:#eee}}
    .node.dead{{border:3px solid #ff4545;background:#3a2222}}
    .name{{font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .life{{font-size:13px;color:#ccc;margin-top:2px}}
    .edge{{fill:#ddd;font-size:13px;text-anchor:middle}}
    .bottom{{max-width:1000px;margin:0 auto 24px;color:#ddd;line-height:1.5}}
  </style>
</head>
<body>
  <div class="header">
    <h1>Docker Network Profiler — {html.escape(str(data.get('stand', 'local')))}</h1>
    <div class="small">Интервал: {data.get('interval_seconds')} сек. | {html.escape(str(data.get('created_at')))}</div>
  </div>
  <div class="legend">
    <span><span class="dot g"></span>running + есть трафик/socket</span>
    <span><span class="dot x"></span>running, но трафика не видно</span>
    <span><span class="dot r"></span>exited/dead</span>
    <span>зелёная стрелка — реальный socket</span>
    <span>пунктир — общая сеть, но общения не видно</span>
  </div>
  <div class="canvas">
    <svg>
      <defs>
        <marker id="arrow-green" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#00ff3b"/></marker>
        <marker id="arrow-gray" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#777"/></marker>
      </defs>
      {''.join(svg_parts)}
    </svg>
    {''.join(node_parts)}
  </div>
  <div class="bottom">
    <b>Итог:</b>
    running: {summary.get('running', 0)},
    активных: {summary.get('alive', 0)},
    без трафика: {summary.get('inactive', 0)},
    мёртвых/остановленных: {summary.get('dead', 0)},
    умерли за интервал: {summary.get('dead_during_interval', 0)},
    реальных связей: {summary.get('actual_links', 0)}.
    <br>
    CPU: {host.get('cpu_percent', 0)}%, RAM: {host.get('ram_percent', 0)}%.
  </div>
</body>
</html>
"""
    with open(filename, "w", encoding="utf-8") as file:
        file.write(content)


def generate_reports(data: Dict[str, Any], out_prefix: str) -> None:
    generate_json_report(data, f"{out_prefix}.json")
    generate_markdown_report(data, f"{out_prefix}.md")
    generate_html_report(data, f"{out_prefix}.html")
