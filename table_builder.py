"""AIcpt — table_builder.

Превращает табличный IP-план (Сеть | Устройство | Интерфейс | IP | Маска |
Шлюз | Тип) в упрощённый XML, который потом скармливается xml_builder.py.

Если столбец «Тип» пустой — определяет тип по имени устройства:
  Server*, Srv*  → server
  Router*, R<N>* → router
  Switch*, SW*   → switch
  Hub*           → hub
  PC*, Comp*     → pc
  Laptop*        → laptop
  Printer*       → printer
  AP*            → access_point
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from typing import Iterable


# =============================================================================
# 1. Авто-определение типа по имени
# =============================================================================

# Префиксы имени → тип. Префикс может оканчиваться на цифру/_/-, ничего не требуем.
_TYPE_PATTERNS = [
    (re.compile(r"^(server|srv|сервер)", re.I), "server"),
    (re.compile(r"^(router|маршрутизатор|rtr|r\d)", re.I), "router"),
    (re.compile(r"^(switch|свич|коммутатор|sw)", re.I), "switch"),
    (re.compile(r"^(hub|хаб|концентратор)", re.I), "hub"),
    (re.compile(r"^(printer|принтер)", re.I), "printer"),
    (re.compile(r"^(laptop|ноутбук|нб)", re.I), "laptop"),
    (re.compile(r"^(ap|accesspoint|wifi|тд)", re.I), "access_point"),
    (re.compile(r"^(bridge|мост)", re.I), "bridge"),
    (re.compile(r"^(repeater|повторитель)", re.I), "repeater"),
    (re.compile(r"^(cloud|облако)", re.I), "cloud"),
    (re.compile(r"^(dsl|cable[-_]?modem|cmodem|modem|модем)", re.I), "modem"),
    (re.compile(r"^(tablet|планшет)", re.I), "tablet"),
    (re.compile(r"^(smart|phone|телефон|смартфон)", re.I), "smartphone"),
    (re.compile(r"^(tv|тв|телевизор)", re.I), "tv"),
    (re.compile(r"^(asa|firewall|фаервол)", re.I), "firewall"),
    (re.compile(r"^(comp|computer|pc|пк|комп|host|client)", re.I), "pc"),
]


def detect_type(name: str) -> str:
    n = name.strip()
    for pattern, t in _TYPE_PATTERNS:
        if pattern.match(n):
            return t
    return "pc"


# =============================================================================
# 2. Нормализация полей
# =============================================================================

# короткое → полное Cisco-имя интерфейса
_IFACE_PREFIX = [
    (re.compile(r"^gig", re.I),  "GigabitEthernet"),
    (re.compile(r"^gi",  re.I),  "GigabitEthernet"),
    (re.compile(r"^fa",  re.I),  "FastEthernet"),
    (re.compile(r"^se",  re.I),  "Serial"),
    (re.compile(r"^eth", re.I),  "Ethernet"),
    (re.compile(r"^vl",  re.I),  "Vlan"),
    (re.compile(r"^wir|^wl", re.I), "Wireless"),
    (re.compile(r"^bt|^blu", re.I), "Bluetooth"),
    (re.compile(r"^port", re.I), "Port "),
]


def normalize_iface_name(s: str, dtype: str) -> str:
    """'Fa0/0' → 'FastEthernet0/0', 'Eth0/1/0 (WIC-1ENET)' → 'Ethernet0/1/0',
       'Fa' для PC → 'FastEthernet0', и т.п."""
    if not s:
        return ""
    raw = s.strip()
    # отрезаем хвост вида " (WIC-1ENET)"
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()

    # Port 1 / Port1 / port 1
    m = re.match(r"^port\s*(\d+)$", raw, re.I)
    if m:
        return f"Port {m.group(1)}"

    # извлекаем prefix + suffix
    m = re.match(r"^([A-Za-zА-Яа-я]+)(.*)$", raw)
    if not m:
        return raw
    prefix, rest = m.group(1), m.group(2).strip()

    canonical = None
    for pat, full in _IFACE_PREFIX:
        if pat.match(prefix):
            canonical = full
            break
    if canonical is None:
        return raw  # незнакомое имя — отдадим как есть

    # для end-host (pc/laptop/server/printer) Fa без слешей → FastEthernet0
    if not rest:
        if dtype in ("pc", "laptop", "server", "printer", "tv"):
            if canonical == "FastEthernet":
                return "FastEthernet0"
            if canonical == "Wireless":
                return "Wireless0"
        # иначе FastEthernet0/0
        return canonical + ("0/0" if "/" in canonical or canonical in ("FastEthernet","GigabitEthernet","Serial","Ethernet") else "0")

    # rest = "0/0" или "0"
    return canonical + rest.lstrip()


def normalize_mask(m: str) -> str:
    """'/24' / '24' / '255.255.255.0' → '255.255.255.0'"""
    if not m:
        return ""
    s = m.strip()
    if s.startswith("/"):
        s = s[1:]
    if s.isdigit():
        bits = int(s)
        if 0 <= bits <= 32:
            mask_int = (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF if bits else 0
            return ".".join(str((mask_int >> (24 - 8 * i)) & 0xFF) for i in range(4))
    return s


def parse_network(s: str) -> tuple[str, str]:
    """'192.168.1.0/24' → ('192.168.1.0', '255.255.255.0')."""
    if not s:
        return ("", "")
    s = s.strip()
    if "/" in s:
        ip, bits = s.split("/", 1)
        return (ip.strip(), normalize_mask("/" + bits.strip()))
    return (s, "")


# =============================================================================
# 3. Строка таблицы
# =============================================================================


class Row:
    __slots__ = ("network", "device", "iface", "ip", "mask", "gateway", "type", "model")

    def __init__(self, network="", device="", iface="", ip="",
                 mask="", gateway="", type="", model=""):
        self.network = network.strip()
        self.device = device.strip()
        self.iface = iface.strip()
        self.ip = ip.strip()
        self.mask = mask.strip()
        self.gateway = gateway.strip()
        self.type = type.strip()
        self.model = model.strip()


# =============================================================================
# 4. Сборка simplified XML
# =============================================================================


def build_simplified_xml(rows: Iterable[Row]) -> str:
    """rows → <network>…</network> с устройствами и (где возможно) линками."""
    rows = [r for r in rows if r.device]

    # Группируем по устройству
    devices: "OrderedDict[str, dict]" = OrderedDict()

    for r in rows:
        dtype = (r.type or detect_type(r.device)).lower().replace(" ", "_")
        # синонимы
        dtype = {"computer": "pc", "комп": "pc", "пк": "pc"}.get(dtype, dtype)
        if r.device not in devices:
            devices[r.device] = {
                "type": dtype,
                "model": r.model or None,
                "interfaces": [],
                "gateway": None,
                "_networks": set(),
            }
        rec = devices[r.device]
        # тип/модель — если уточняется в более поздней строке, перезапишем
        if r.type:
            rec["type"] = dtype
        if r.model:
            rec["model"] = r.model

        # mask — либо из колонки «маска», либо из CIDR в колонке «сеть»
        mask = normalize_mask(r.mask)
        if not mask:
            _, mask = parse_network(r.network)

        iface_name = normalize_iface_name(r.iface, rec["type"])
        if iface_name and (r.ip or mask):
            rec["interfaces"].append({
                "name": iface_name,
                "ip": r.ip,
                "subnet": mask,
                "gateway": r.gateway if r.gateway and r.gateway != "—" else "",
            })

        if r.gateway and r.gateway != "—":
            rec["gateway"] = r.gateway

        if r.network:
            rec["_networks"].add(r.network)

    # Группируем по сети — будем строить связи (если ровно 2 устройства)
    by_network: "OrderedDict[str, list[tuple[str, str]]]" = OrderedDict()
    for r in rows:
        if not r.network or not r.device:
            continue
        iface = normalize_iface_name(r.iface, devices[r.device]["type"])
        by_network.setdefault(r.network, []).append((r.device, iface))

    # === собираем XML ===
    root = ET.Element("network")
    devs_node = ET.SubElement(root, "devices")
    links_node = ET.SubElement(root, "links")

    grid_x, grid_y = 100.0, 100.0
    for i, (name, rec) in enumerate(devices.items()):
        col = i % 6
        row = i // 6
        d = ET.SubElement(devs_node, "device", attrib={
            "name": name,
            "type": rec["type"],
            "x": f"{grid_x + col * 150}",
            "y": f"{grid_y + row * 150}",
        })
        if rec["model"]:
            d.set("model", rec["model"])
        if rec["gateway"]:
            d.set("gateway", rec["gateway"])

        for iface in rec["interfaces"]:
            attrs = {"name": iface["name"]}
            if iface["ip"]:
                attrs["ip"] = iface["ip"]
            if iface["subnet"]:
                attrs["subnet"] = iface["subnet"]
            if iface["gateway"]:
                attrs["gateway"] = iface["gateway"]
            ET.SubElement(d, "interface", attrib=attrs)

    # авто-связи: только для сетей с 2 устройствами (point-to-point)
    seen_pairs: set[frozenset[str]] = set()
    for net, members in by_network.items():
        unique = []
        seen_dev: set[str] = set()
        for dev, iface in members:
            if dev in seen_dev:
                continue
            seen_dev.add(dev)
            unique.append((dev, iface))

        if len(unique) == 2:
            (a, ai), (b, bi) = unique
            pair = frozenset([f"{a}:{ai}", f"{b}:{bi}"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            type_a = devices[a]["type"]
            type_b = devices[b]["type"]
            link_type = _decide_link_type(type_a, type_b, ai, bi)
            ET.SubElement(links_node, "link", attrib={
                "from": a, "from_port": ai,
                "to": b, "to_port": bi,
                "type": link_type,
            })

    return _pretty(root)


def _decide_link_type(t1: str, t2: str, port1: str, port2: str) -> str:
    # serial если хотя бы один порт Serial
    if port1.startswith("Serial") or port2.startswith("Serial"):
        return "serial"
    # crossover между двумя одинаковыми «активными» (router/switch без посредника)
    routers = {"router", "firewall"}
    pcs = {"pc", "laptop", "server", "printer"}
    if t1 in routers and t2 in routers:
        return "crossover"
    if t1 in pcs and t2 in pcs:
        return "crossover"
    return "copper"


def _pretty(elem: ET.Element) -> str:
    _indent(elem)
    return ET.tostring(elem, encoding="unicode")


def _indent(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            _indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i + "  "
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


# =============================================================================
# 5. Парсинг текстовой / TSV таблицы (для CLI)
# =============================================================================


def parse_text_table(text: str) -> list[Row]:
    """Принимает таблицу: поля разделены табом, |, или 2+ пробелами.
    Первая строка — заголовок (детектится по словам «сеть»/«ip»/«устройство»)."""
    rows: list[Row] = []
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return rows

    # обнаружить заголовок и порядок колонок
    header = lines[0]
    is_header = bool(re.search(r"сеть|устройств|интерфейс|ip|маск|шлюз|тип|network|device",
                                header, re.I))
    cols = _detect_columns(header) if is_header else None
    body = lines[1:] if is_header else lines

    def _at(cells: list[str], idx: int) -> str:
        return cells[idx] if 0 <= idx < len(cells) else ""

    for raw in body:
        cells = _split_row(raw)
        if cols is None:
            cells += [""] * (7 - len(cells))
            r = Row(*cells[:7])
        else:
            r = Row(
                network=_at(cells, cols.get("network", -1)),
                device=_at(cells, cols.get("device", -1)),
                iface=_at(cells, cols.get("iface", -1)),
                ip=_at(cells, cols.get("ip", -1)),
                mask=_at(cells, cols.get("mask", -1)),
                gateway=_at(cells, cols.get("gateway", -1)),
                type=_at(cells, cols.get("type", -1)),
            )
        rows.append(r)
    return rows


def _split_row(line: str) -> list[str]:
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    if "|" in line:
        return [c.strip() for c in line.split("|")]
    # >=2 пробелов
    return [c.strip() for c in re.split(r"\s{2,}", line)]


def _detect_columns(header: str) -> dict[str, int]:
    cells = _split_row(header)
    cols: dict[str, int] = {}
    for i, c in enumerate(cells):
        cl = c.lower()
        # порядок важен: «тип устройства» содержит оба ключа,
        # поэтому проверяем «тип/type» РАНЬШЕ, чем «устройство/device».
        if "тип" in cl or cl == "type" or cl.startswith("device type") or cl == "kind":
            cols["type"] = i
        elif "сет" in cl or "network" in cl or "subnet" in cl or "диапаз" in cl:
            cols["network"] = i
        elif "интерф" in cl or "interface" in cl or "порт" in cl or "port" in cl:
            cols["iface"] = i
        elif "маск" in cl or "mask" in cl:
            cols["mask"] = i
        elif "шлюз" in cl or "gateway" in cl:
            cols["gateway"] = i
        elif cl == "ip" or "ip-адрес" in cl or "ip адрес" in cl or "ip address" in cl or "адрес" in cl:
            cols["ip"] = i
        elif "устройст" in cl or "device" in cl or "хост" in cl or "host" in cl:
            cols["device"] = i
    return cols


# =============================================================================
# 6. CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    ap = argparse.ArgumentParser(description="AIcpt: таблица → simplified XML")
    ap.add_argument("table_file", help="txt с таблицей (TSV или с разделителями |)")
    ap.add_argument("--out", default="simplified.xml")
    args = ap.parse_args()

    text = Path(args.table_file).read_text(encoding="utf-8", errors="replace")
    rows = parse_text_table(text)
    if not rows:
        print("[-] В таблице нет данных.", file=sys.stderr)
        sys.exit(1)
    xml = build_simplified_xml(rows)
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"[+] simplified XML: {args.out}  (устройств: {len(set(r.device for r in rows if r.device))})")
