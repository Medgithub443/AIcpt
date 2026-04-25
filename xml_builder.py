"""AIcpt — xml_builder (template-based, full device catalog).

Берёт реальные DEVICE-шаблоны из templates/*.xml (43 шаблона устройств
Cisco Packet Tracer 6.2), подставляет в них имя, IP, координаты,
running-config, серверные сервисы и пр., и вклеивает в white.xml.
"""

from __future__ import annotations

import copy
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Callable


Log = Callable[[str], None]


def _noop(_: str) -> None: ...


HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"


# =============================================================================
# 1. РЕЕСТР МОДЕЛЕЙ
# =============================================================================

def _fa(start: int, count: int) -> list[str]:
    return [f"FastEthernet0/{i}" for i in range(start, start + count)]

def _gi(start: int, count: int) -> list[str]:
    return [f"GigabitEthernet0/{i}" for i in range(start, start + count)]

def _eth(start: int, count: int) -> list[str]:
    return [f"Ethernet0/{i}" for i in range(start, start + count)]

def _hub_ports(count: int) -> list[str]:
    return [f"Port {i}" for i in range(count)]


_MODELS: dict[str, dict] = {
    # ---- маршрутизаторы ------------------------------------------------------
    "1841":             {"file": "1841.xml",            "ports": _fa(0, 2),                    "kind": "router",  "oui": "0001.42"},
    "1941":             {"file": "1941.xml",            "ports": _gi(0, 2),                    "kind": "router",  "oui": "0001.43"},
    "2620XM":           {"file": "2620XM.xml",          "ports": _fa(0, 1),                    "kind": "router",  "oui": "0002.16"},
    "2621XM":           {"file": "2621XM.xml",          "ports": _fa(0, 2),                    "kind": "router",  "oui": "0002.17"},
    "2811":             {"file": "2811.xml",            "ports": _fa(0, 2),                    "kind": "router",  "oui": "0003.E4"},
    "2901":             {"file": "2901.xml",            "ports": _gi(0, 2),                    "kind": "router",  "oui": "0004.9A"},
    "2911":             {"file": "2911.xml",            "ports": _gi(0, 3),                    "kind": "router",  "oui": "0005.5E"},
    "819HGW":           {"file": "819HGW.xml",          "ports": _fa(0, 4) + ["FastEthernet1", "GigabitEthernet0", "Cellular0", "Serial0", "Vlan1"], "kind": "router", "oui": "0006.2A"},
    "Router-PT":        {"file": "Router-PT.xml",       "ports": _fa(0, 2) + ["Serial2/0", "Serial3/0", "FastEthernet4/0", "FastEthernet5/0"], "kind": "router", "oui": "0007.EC"},
    "Router-PT-Empty":  {"file": "Router-PT-Empty.xml", "ports": [],                            "kind": "router",  "oui": "0008.21"},

    # ---- коммутаторы ---------------------------------------------------------
    "2950-24":          {"file": "2950-24.xml",         "ports": _fa(1, 24),                                       "kind": "switch",  "oui": "0010.11"},
    "2950T-24":         {"file": "2950T-24.xml",        "ports": _fa(1, 24) + _gi(1, 2),                           "kind": "switch",  "oui": "0010.A4"},
    "2960-24TT":        {"file": "2960-24TT.xml",       "ports": _fa(1, 24) + _gi(1, 2),                           "kind": "switch",  "oui": "0011.93"},
    "3560-24PS":        {"file": "3560-24PS.xml",       "ports": _fa(1, 24) + _gi(1, 2),                           "kind": "switch",  "oui": "0012.7F"},
    "Switch-PT":        {"file": "Switch-PT.xml",       "ports": _fa(0, 6),                                        "kind": "switch",  "oui": "0030.A3"},
    "Switch-PT-Empty":  {"file": "Switch-PT-Empty.xml", "ports": [],                                                "kind": "switch",  "oui": "0030.B0"},

    # ---- защитный экран ------------------------------------------------------
    "5505":             {"file": "5505.xml",            "ports": _eth(0, 8),                    "kind": "firewall","oui": "0040.0B"},

    # ---- IP-телефон ----------------------------------------------------------
    "7960":             {"file": "7960.xml",            "ports": ["FastEthernet0/0", "PCFastEthernet0/1"], "kind": "ip_phone", "oui": "0050.0F"},

    # ---- беспроводные точки --------------------------------------------------
    "AccessPoint-PT":   {"file": "AccessPoint-PT.xml",  "ports": ["Wireless0", "Ethernet0/1/0"], "kind": "ap",     "oui": "0060.5C"},
    "AccessPoint-PT-A": {"file": "AccessPoint-PT-A.xml","ports": ["Wireless0", "Ethernet0/1/0"], "kind": "ap",     "oui": "0060.5D"},
    "AccessPoint-PT-N": {"file": "AccessPoint-PT-N.xml","ports": ["Wireless0", "Ethernet0/1/0"], "kind": "ap",     "oui": "0060.5E"},

    # ---- беспроводный роутер -------------------------------------------------
    "Linksys-WRT300N":  {"file": "Linksys-WRT300N.xml", "ports": ["Internet", "Ethernet1", "Ethernet2", "Ethernet3", "Ethernet4", "Wireless"], "kind": "wrouter", "oui": "0080.A1"},

    # ---- end-hosts -----------------------------------------------------------
    "PC-PT":            {"file": "pc-pt.xml",           "ports": ["FastEthernet0"],             "kind": "host",   "oui": "00D0.D3"},
    "Laptop-PT":        {"file": "Laptop-PT.xml",       "ports": ["FastEthernet0"],             "kind": "host",   "oui": "00D0.5E"},
    "Server-PT":        {"file": "Server-PT.xml",       "ports": ["FastEthernet0"],             "kind": "server", "oui": "00D0.97"},
    "Printer-PT":       {"file": "Printer-PT.xml",      "ports": ["FastEthernet0"],             "kind": "host",   "oui": "00D0.BC"},
    "WiredEndDevice-PT":   {"file": "WiredEndDevice-PT.xml",   "ports": ["FastEthernet0"], "kind": "host", "oui": "00D0.D0"},
    "WirelessEndDevice-PT":{"file": "WirelessEndDevice-PT.xml","ports": ["Wireless0"],     "kind": "host", "oui": "00D0.D1"},
    "TabletPC-PT":      {"file": "TabletPC-PT.xml",     "ports": ["Bluetooth0", "Wireless0"],   "kind": "host",   "oui": "00D0.E0"},
    "SMARTPHONE-PT":    {"file": "SMARTPHONE-PT.xml",   "ports": ["Bluetooth0", "Wireless0"],   "kind": "host",   "oui": "00D0.E1"},

    # ---- хаб / мост / репитер / сниффер -------------------------------------
    "Hub-PT":           {"file": "Hub-PT.xml",          "ports": _hub_ports(6),                 "kind": "hub",    "oui": "000D.BD"},
    "Bridge-PT":        {"file": "Bridge-PT.xml",       "ports": ["Ethernet0", "Ethernet1"],    "kind": "bridge", "oui": "0090.21"},
    "Repeater-PT":      {"file": "Repeater-PT.xml",     "ports": ["Ethernet0", "Ethernet1"],    "kind": "repeater", "oui": "00B0.C2"},
    "Sniffer":          {"file": "Sniffer.xml",         "ports": ["Ethernet0", "Ethernet1"],    "kind": "sniffer","oui": "00B1.C2"},

    # ---- модемы / облака / тв ------------------------------------------------
    "Cloud-PT":         {"file": "Cloud-PT.xml",        "ports": [f"Modem{i}" for i in range(2)] + [f"Ethernet{i}" for i in range(4)] + ["Coaxial0", "Serial0"], "kind": "cloud", "oui": "0090.A2"},
    "Cloud-PT-Empty":   {"file": "Cloud-PT-Empty.xml",  "ports": [],                                                                     "kind": "cloud", "oui": "0090.A3"},
    "DSL-Modem-PT":     {"file": "DSL-Modem-PT.xml",    "ports": ["Modem0", "Ethernet1"],       "kind": "modem",  "oui": "0090.A4"},
    "Cable-Modem-PT":   {"file": "Cable-Modem-PT.xml",  "ports": ["Coaxial0", "Ethernet1"],     "kind": "modem",  "oui": "0090.A5"},
    "Home-VoIP-PT":     {"file": "Home-VoIP-PT.xml",    "ports": ["Modem0", "Ethernet1"],       "kind": "voip",   "oui": "0090.A6"},
    "Cell-Tower":       {"file": "Cell-Tower.xml",      "ports": ["Coaxial0", "Air"],           "kind": "cell",   "oui": "0090.B0"},
    "CoAxialSplitter-PT":{"file": "CoAxialSplitter-PT.xml","ports": ["Coaxial0", "Coaxial1", "Coaxial2"], "kind": "splitter", "oui": "0090.B1"},
    "Central-Office-Server":{"file": "Central-Office-Server.xml","ports": ["Modem0"] + [f"Coaxial{i}" for i in range(3)] + _fa(0, 4),    "kind": "co_server", "oui": "0090.B2"},
    "TV-PT":            {"file": "TV-PT.xml",           "ports": ["Coaxial0"],                  "kind": "host",   "oui": "0090.C0"},
    "Analog-Phone-PT":  {"file": "Analog-Phone-PT.xml", "ports": ["Modem0"],                    "kind": "host",   "oui": "0090.C1"},
}


# Тип устройства (из simplified XML) → дефолтная модель, если model не задан.
_TYPE_DEFAULT = {
    "router":       "1841",
    "switch":       "2960-24TT",
    "pc":           "PC-PT",
    "laptop":       "Laptop-PT",
    "server":       "Server-PT",
    "printer":      "Printer-PT",
    "ip_phone":     "7960",
    "access_point": "AccessPoint-PT",
    "hub":          "Hub-PT",
    "bridge":       "Bridge-PT",
    "repeater":     "Repeater-PT",
    "sniffer":      "Sniffer",
    "cloud":        "Cloud-PT",
    "modem":        "DSL-Modem-PT",
    "tablet":       "TabletPC-PT",
    "smartphone":   "SMARTPHONE-PT",
    "tv":           "TV-PT",
    "firewall":     "5505",
    "wireless_router": "Linksys-WRT300N",
    "voip":         "Home-VoIP-PT",
}


def resolve_model(dtype: str, model: str | None) -> tuple[str, dict]:
    """type+model → (resolved_model, model_info). Если ничего не подошло — PC-PT."""
    if model and model in _MODELS:
        return model, _MODELS[model]
    fallback = _TYPE_DEFAULT.get((dtype or "").lower(), "PC-PT")
    return fallback, _MODELS[fallback]


# =============================================================================
# 2. УТИЛИТЫ
# =============================================================================


def _gen_mac(oui: str, device_idx: int, port_idx: int) -> str:
    low = (device_idx * 100 + port_idx + 1) & 0xFFFFFF
    return f"{oui}{low >> 16 & 0xFF:02X}.{low & 0xFFFF:04X}"


def _mac_to_eui64_ll(mac: str) -> str:
    hx = mac.replace(".", "").replace(":", "").upper()
    if len(hx) != 12:
        return ""
    b = [int(hx[i : i + 2], 16) for i in range(0, 12, 2)]
    b[0] ^= 0x02
    groups = [
        f"{b[0]:X}{b[1]:02X}",
        f"{b[2]:02X}FF",
        f"FE{b[3]:02X}",
        f"{b[4]:02X}{b[5]:02X}",
    ]
    return "FE80::" + ":".join(groups).upper()


def _gen_serial(kind: str, idx: int) -> str:
    if kind in ("host", "server", "ap", "hub", "ip_phone", "bridge", "repeater"):
        return f"PTT{idx:04d}X{idx * 7 % 1000:03d}"
    if kind == "switch":
        return f"FOC{idx:04d}Z{idx * 11 % 100:02d}A"
    return f"FTX{idx:04d}Y{idx * 13 % 1000:03d}"


def _set_text(el: ET.Element | None, text: str) -> None:
    if el is not None:
        el.text = text


def _find_all_ports(engine: ET.Element) -> list[ET.Element]:
    ports: list[ET.Element] = []

    def walk(e: ET.Element) -> None:
        for child in list(e):
            if child.tag == "PORT":
                ports.append(child)
            else:
                walk(child)

    module = engine.find("MODULE")
    if module is not None:
        walk(module)
    return ports


# =============================================================================
# 3. ПАРСИНГ УПРОЩЁННОГО XML
# =============================================================================


def _extract_network_root(text: str) -> ET.Element:
    s = text.strip()
    start = s.find("<network")
    end = s.rfind("</network>")
    if start == -1 or end == -1:
        raise ValueError("В ответе нейросети не найдено <network>…</network>.")
    chunk = s[start : end + len("</network>")]
    try:
        return ET.fromstring(chunk)
    except ET.ParseError as e:
        raise ValueError(f"Невалидный XML от нейросети: {e}") from e


def _as_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_simplified(text: str) -> tuple[list[dict], list[dict]]:
    root = _extract_network_root(text)

    devices: list[dict] = []
    devices_node = root.find("devices")
    for idx, d in enumerate(list(devices_node or [])):
        if d.tag.lower() != "device":
            continue
        name = d.get("name") or f"Device{idx}"
        dtype = (d.get("type") or "router").lower()
        model = d.get("model")
        col = idx % 6
        row = idx // 6
        x = _as_float(d.get("x"), 100.0 + col * 150)
        y = _as_float(d.get("y"), 100.0 + row * 150)

        interfaces: list[dict] = []
        for i in d.findall("interface"):
            interfaces.append(dict(i.attrib))

        vlans: list[dict] = []
        vnode = d.find("vlans")
        if vnode is not None:
            for v in vnode.findall("vlan"):
                vlans.append(dict(v.attrib))

        cfg_lines: list[str] = []
        cnode = d.find("config")
        if cnode is not None:
            for ln in cnode.findall("line"):
                cfg_lines.append(ln.text or "")

        gateway = d.get("gateway")
        for iface in interfaces:
            if iface.get("gateway"):
                gateway = iface["gateway"]
                break

        services_node = d.find("services")
        services = _parse_services(services_node) if services_node is not None else None

        modules: list[dict] = []
        mnode = d.find("modules")
        if mnode is not None:
            for m in mnode.findall("module"):
                modules.append(dict(m.attrib))

        devices.append({
            "name": name, "type": dtype, "model": model,
            "x": x, "y": y,
            "interfaces": interfaces, "vlans": vlans,
            "config_lines": cfg_lines, "gateway": gateway,
            "services": services, "modules": modules,
        })

    links: list[dict] = []
    links_node = root.find("links")
    for link in list(links_node or []):
        if link.tag.lower() != "link":
            continue
        links.append({
            "from": link.get("from"),
            "to": link.get("to"),
            "from_port": link.get("from_port"),
            "to_port": link.get("to_port"),
            "type": (link.get("type") or "copper").lower(),
        })

    return devices, links


def _parse_services(node: ET.Element) -> dict:
    out: dict = {}
    for child in list(node):
        tag = child.tag.lower()
        if tag == "dhcp":
            pools = []
            for pool in child.findall("pool"):
                pools.append(dict(pool.attrib))
            out["dhcp"] = {
                "enabled": child.get("enabled", "true").lower() == "true",
                "pools": pools,
            }
        elif tag == "dns":
            records = []
            for rec in child.findall("record"):
                records.append(dict(rec.attrib))
            out["dns"] = {
                "enabled": child.get("enabled", "true").lower() == "true",
                "records": records,
            }
        elif tag in ("http", "https", "ftp", "tftp", "ntp", "syslog", "email"):
            out[tag] = {
                "enabled": child.get("enabled", "true").lower() == "true",
            }
    return out


# =============================================================================
# 4. МУТАЦИЯ ШАБЛОНА
# =============================================================================


_TEMPLATE_CACHE: dict[str, bytes] = {}


def _load_template(filename: str) -> ET.Element:
    path = TEMPLATES_DIR / filename
    if filename not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[filename] = path.read_bytes()
    return ET.fromstring(_TEMPLATE_CACHE[filename])


def _apply_interface(port: ET.Element, mac: str, iface: dict | None) -> None:
    _set_text(port.find("MACADDRESS"), mac)
    _set_text(port.find("BIA"), mac)

    ll = _mac_to_eui64_ll(mac)
    for tag in ("IPV6_LINK_LOCAL", "IPV6_DEFAULT_LINK_LOCAL"):
        el = port.find(tag)
        if el is not None and ll:
            el.text = ll

    if iface is None:
        return

    ip_el = port.find("IP")
    sub_el = port.find("SUBNET")
    if ip_el is None:
        ip_el = ET.SubElement(port, "IP")
    if sub_el is None:
        sub_el = ET.SubElement(port, "SUBNET")
    ip_el.text = iface.get("ip") or ""
    sub_el.text = iface.get("subnet") or ""

    if iface.get("clockrate"):
        cr = port.find("CLOCKRATE")
        if cr is None:
            cr = ET.SubElement(port, "CLOCKRATE")
        cr.text = str(iface["clockrate"])
        crf = port.find("CLOCKRATEFLAG")
        if crf is None:
            crf = ET.SubElement(port, "CLOCKRATEFLAG")
        crf.text = "true"
    if iface.get("bandwidth"):
        bw = port.find("BANDWIDTH")
        if bw is None:
            bw = ET.SubElement(port, "BANDWIDTH")
        bw.text = str(iface["bandwidth"])
    if iface.get("mac"):
        _set_text(port.find("MACADDRESS"), iface["mac"])
        _set_text(port.find("BIA"), iface["mac"])


def _replace_config(engine: ET.Element, tag: str, lines: list[str]) -> None:
    cfg = engine.find(tag)
    if cfg is None:
        cfg = ET.SubElement(engine, tag)
    for c in list(cfg):
        cfg.remove(c)
    for line in lines:
        ln = ET.SubElement(cfg, "LINE")
        ln.text = line


def _replace_vlans(engine: ET.Element, user_vlans: list[dict]) -> None:
    if not user_vlans:
        return
    vlans = engine.find("VLANS")
    if vlans is None:
        return
    existing_nums = {v.get("number") for v in vlans.findall("VLAN")}
    for v in user_vlans:
        num = str(v.get("number") or v.get("id") or "")
        if not num or num in existing_nums:
            continue
        ET.SubElement(vlans, "VLAN", number=num, name=str(v.get("name", "")))
        existing_nums.add(num)


def _update_workspace(dev_node: ET.Element, x: float, y: float, name: str) -> None:
    ws = dev_node.find("WORKSPACE")
    if ws is None:
        return
    logical = ws.find("LOGICAL")
    if logical is not None:
        _set_text(logical.find("X"), f"{x}")
        _set_text(logical.find("Y"), f"{y}")
        for t in ("MEM_ADDR", "DEV_ADDR"):
            el = logical.find(t)
            if el is not None:
                el.text = "0"

    phys = ws.find("PHYSICAL")
    if phys is not None and phys.text:
        parts = phys.text.split(",")
        if parts:
            parts[-1] = name
        phys.text = ",".join(parts)


def _apply_server_services(engine: ET.Element, services: dict, port_name: str) -> None:
    """Применяет настройки сервисов к шаблону Server-PT."""
    boolean_services = {
        "http": ("HTTP_SERVER", "ENABLED"),
        "https": ("HTTPS_SERVER", "HTTPSENABLED"),
        "tftp": ("TFTP_SERVER", "ENABLED"),
        "ftp": ("FTP_SERVER", "ENABLED"),
        "ntp": ("NTP_SERVER", "ENABLED"),
        "syslog": ("SYSLOG_SERVER", "ENABLED"),
    }
    for svc, (block, flag) in boolean_services.items():
        cfg = services.get(svc)
        if not cfg:
            continue
        block_el = engine.find(block)
        if block_el is None:
            continue
        flag_el = block_el.find(flag)
        if flag_el is None:
            flag_el = ET.SubElement(block_el, flag)
        flag_el.text = "1" if cfg.get("enabled") else "0"

    if services.get("email"):
        es = engine.find("EMAIL_SERVER")
        if es is not None:
            for tag in ("SMTP_ENABLED", "POP3_ENABLED"):
                el = es.find(tag)
                if el is None:
                    el = ET.SubElement(es, tag)
                el.text = "1" if services["email"].get("enabled") else "0"

    if services.get("dhcp"):
        dhcp_block = engine.find("DHCP_SERVERS")
        if dhcp_block is not None:
            ports_node = dhcp_block.find("ASSOCIATED_PORTS")
            if ports_node is not None:
                for c in list(ports_node):
                    ports_node.remove(c)
                ap = ET.SubElement(ports_node, "ASSOCIATED_PORT")
                ET.SubElement(ap, "NAME").text = port_name
                dhcp_srv = ET.SubElement(ap, "DHCP_SERVER")
                ET.SubElement(dhcp_srv, "ENABLED").text = "1" if services["dhcp"].get("enabled") else "0"
                pools_node = ET.SubElement(dhcp_srv, "POOLS")
                for pool in services["dhcp"].get("pools", []):
                    p = ET.SubElement(pools_node, "POOL")
                    ET.SubElement(p, "NAME").text = pool.get("name", "serverPool")
                    ET.SubElement(p, "NETWORK").text = pool.get("network", "0.0.0.0")
                    ET.SubElement(p, "MASK").text = pool.get("mask", "0.0.0.0")
                    ET.SubElement(p, "DEFAULT_ROUTER").text = pool.get("default_router", "0.0.0.0")
                    ET.SubElement(p, "TFTP_ADDRESS").text = pool.get("tftp", "0.0.0.0")
                    ET.SubElement(p, "START_IP").text = pool.get("start", "0.0.0.0")
                    ET.SubElement(p, "END_IP").text = pool.get("end", "0.0.2.0")
                    ET.SubElement(p, "DNS_SERVER").text = pool.get("dns", "0.0.0.0")
                    ET.SubElement(p, "MAX_USERS").text = str(pool.get("max_users", 512))
                    ET.SubElement(p, "DOMAIN_NAME").text = pool.get("domain", "")
                    ET.SubElement(p, "DHCP_POOL_LEASES")
                ET.SubElement(dhcp_srv, "DHCP_RESERVATIONS")
                ET.SubElement(dhcp_srv, "AUTOCONFIG")

    if services.get("dns"):
        dns_block = engine.find("DNS_SERVER")
        if dns_block is not None:
            en = dns_block.find("ENABLED")
            if en is None:
                en = ET.SubElement(dns_block, "ENABLED")
            en.text = "1" if services["dns"].get("enabled") else "0"
            db = dns_block.find("NAMESERVER-DATABASE")
            if db is None:
                db = ET.SubElement(dns_block, "NAMESERVER-DATABASE")
            for c in list(db):
                db.remove(c)
            for rec in services["dns"].get("records", []):
                r = ET.SubElement(db, "RECORD")
                ET.SubElement(r, "NAME").text = rec.get("name", "")
                ET.SubElement(r, "TYPE").text = rec.get("type", "A")
                ET.SubElement(r, "ADDRESS").text = rec.get("ip") or rec.get("address", "")


def _running_config_for_router(dev: dict, port_names: list[str]) -> list[str]:
    lines = [
        "!", "version 12.4",
        "no service timestamps log datetime msec",
        "no service timestamps debug datetime msec",
        "no service password-encryption", "!",
        f"hostname {dev['name']}", "!",
        "ip cef", "no ipv6 cef", "!",
        "spanning-tree mode pvst", "!",
    ]
    iface_map = {i["name"]: i for i in dev["interfaces"]}
    for p in port_names:
        iface = iface_map.get(p)
        lines.append(f"interface {p}")
        if iface and iface.get("ip") and iface.get("subnet"):
            lines.append(f" ip address {iface['ip']} {iface['subnet']}")
            if p.startswith("Serial") and iface.get("clockrate"):
                lines.append(f" clock rate {iface['clockrate']}")
            lines.append(" duplex auto")
            lines.append(" speed auto")
            lines.append(" no shutdown")
        else:
            lines.append(" no ip address")
            lines.append(" duplex auto")
            lines.append(" speed auto")
            lines.append(" shutdown")
        lines.append("!")
    lines.extend([
        "interface Vlan1", " no ip address", " shutdown", "!",
        "ip classless", "!", "ip flow-export version 9", "!",
        "line con 0", "!", "line aux 0", "!",
        "line vty 0 4", " login", "!", "end",
    ])
    return lines


def _running_config_for_switch(dev: dict, port_names: list[str]) -> list[str]:
    lines = [
        "!", "version 12.1",
        "no service timestamps log datetime msec",
        "no service timestamps debug datetime msec",
        "no service password-encryption", "!",
        f"hostname {dev['name']}", "!", "spanning-tree mode pvst", "!",
    ]
    iface_map = {i["name"]: i for i in dev["interfaces"]}
    for p in port_names:
        iface = iface_map.get(p)
        lines.append(f"interface {p}")
        if iface and iface.get("vlan"):
            lines.append(" switchport mode access")
            lines.append(f" switchport access vlan {iface['vlan']}")
        elif iface and iface.get("trunk"):
            lines.append(" switchport mode trunk")
        lines.append("!")
    lines.extend([
        "interface Vlan1", " no ip address", " shutdown", "!",
        "line con 0", "!",
        "line vty 0 4", " login",
        "line vty 5 15", " login", "!", "end",
    ])
    return lines


# =============================================================================
# 5. СБОРКА DEVICE
# =============================================================================


def build_device(dev: dict, device_idx: int, log: Log = _noop) -> ET.Element:
    model_name, info = resolve_model(dev["type"], dev.get("model"))
    template = _load_template(info["file"])
    node = copy.deepcopy(template)

    engine = node.find("ENGINE")
    if engine is None:
        raise RuntimeError(f"шаблон {info['file']} без <ENGINE>?")

    type_el = engine.find("TYPE")
    if type_el is not None:
        type_el.set("model", model_name)
        type_el.set("customModel", "")

    name_el = engine.find("NAME")
    if name_el is not None:
        name_el.text = dev["name"]
    sys_name_el = engine.find("SYS_NAME")
    if sys_name_el is not None:
        sys_name_el.text = dev["name"]
    serial_el = engine.find("SERIALNUMBER")
    if serial_el is not None:
        serial_el.text = _gen_serial(info["kind"], device_idx + 1)

    ports = _find_all_ports(engine)
    port_names = info["ports"]
    iface_map = {i["name"]: i for i in dev["interfaces"]}

    for pi, port in enumerate(ports):
        mac = _gen_mac(info["oui"], device_idx + 1, pi + 1)
        pname = port_names[pi] if pi < len(port_names) else None
        iface = iface_map.get(pname) if pname else None
        _apply_interface(port, mac, iface)

    if dev.get("gateway"):
        gw = engine.find("GATEWAY")
        if gw is None:
            gw = ET.SubElement(engine, "GATEWAY")
        gw.text = dev["gateway"]

    if engine.find("RUNNINGCONFIG") is not None:
        if dev["config_lines"]:
            lines = dev["config_lines"]
        elif info["kind"] == "router":
            lines = _running_config_for_router(dev, port_names)
        elif info["kind"] == "switch":
            lines = _running_config_for_switch(dev, port_names)
        else:
            lines = None
        if lines is not None:
            _replace_config(engine, "RUNNINGCONFIG", lines)
            if engine.find("STARTUPCONFIG") is not None:
                _replace_config(engine, "STARTUPCONFIG", lines)

    if info["kind"] == "switch" and dev["vlans"]:
        _replace_vlans(engine, dev["vlans"])

    if info["kind"] == "server" and dev.get("services"):
        port_for_dhcp = port_names[0] if port_names else "FastEthernet0"
        _apply_server_services(engine, dev["services"], port_for_dhcp)

    if dev.get("modules"):
        log(f"    [warn] модули указаны для {dev['name']}: "
            f"физическая вставка не реализована, используй модель с готовыми WIC.")

    _update_workspace(node, dev["x"], dev["y"], dev["name"])
    return node


# =============================================================================
# 6. LINK
# =============================================================================

_LINK_TYPE = {
    "copper":    ("eCopper", "eStraightThrough"),
    "crossover": ("eCopper", "eCrossOver"),
    "serial":    ("eSerial", "eStraightThrough"),
    "fiber":     ("eFiber",  "eStraightThrough"),
    "coaxial":   ("eCoaxial","eStraightThrough"),
    "phone":     ("ePhone",  "eStraightThrough"),
}


def build_link(link: dict, name_to_index: dict[str, int]) -> ET.Element:
    outer, inner = _LINK_TYPE.get(link["type"], _LINK_TYPE["copper"])
    if link["from"] not in name_to_index:
        raise ValueError(f"LINK: неизвестное устройство from='{link['from']}'")
    if link["to"] not in name_to_index:
        raise ValueError(f"LINK: неизвестное устройство to='{link['to']}'")

    n = ET.Element("LINK")
    ET.SubElement(n, "TYPE").text = outer
    cable = ET.SubElement(n, "CABLE")
    ET.SubElement(cable, "LENGTH").text = "1.0"
    ET.SubElement(cable, "FROM").text = str(name_to_index[link["from"]])
    ET.SubElement(cable, "PORT").text = link["from_port"] or ""
    ET.SubElement(cable, "TO").text = str(name_to_index[link["to"]])
    ET.SubElement(cable, "PORT").text = link["to_port"] or ""
    ET.SubElement(cable, "GEO_VIEW_COLOR").text = "#000000"
    ET.SubElement(cable, "TYPE").text = inner
    return n


# =============================================================================
# 7. ИТОГОВЫЙ XML
# =============================================================================


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


def build_full_xml(white_xml_text: str, simplified_xml_text: str, log: Log = _noop) -> str:
    devices, links = parse_simplified(simplified_xml_text)
    log(f"[*] Разобрано устройств: {len(devices)}, связей: {len(links)}")

    root = ET.fromstring(white_xml_text)
    network = root.find("NETWORK")
    if network is None:
        raise ValueError("white.xml не содержит <NETWORK>.")

    devices_node = network.find("DEVICES")
    if devices_node is None:
        devices_node = ET.SubElement(network, "DEVICES")
    else:
        for c in list(devices_node):
            devices_node.remove(c)

    links_node = network.find("LINKS")
    if links_node is None:
        links_node = ET.SubElement(network, "LINKS")
    else:
        for c in list(links_node):
            links_node.remove(c)

    name_to_index: dict[str, int] = {}
    for idx, dev in enumerate(devices):
        if dev["name"] in name_to_index:
            raise ValueError(f"Дублирующееся имя устройства: {dev['name']}")
        name_to_index[dev["name"]] = idx

    for idx, dev in enumerate(devices):
        node = build_device(dev, idx, log=log)
        devices_node.append(node)
        log(f"    + {dev['name']} ({dev['type']}, "
            f"{dev.get('model') or _TYPE_DEFAULT.get(dev['type'].lower(), 'PC-PT')})")

    for link in links:
        n = build_link(link, name_to_index)
        links_node.append(n)
        log(f"    + {link['from']}:{link['from_port']} "
            f"<-{link['type']}-> {link['to']}:{link['to_port']}")

    _indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def build_full_xml_file(white_xml_path, simplified_xml_path, output_xml_path, log=_noop) -> Path:
    white = Path(white_xml_path).read_text(encoding="utf-8")
    simp = Path(simplified_xml_path).read_text(encoding="utf-8", errors="replace")
    full = build_full_xml(white, simp, log=log)
    out = Path(output_xml_path)
    out.write_text(full, encoding="utf-8")
    return out


# =============================================================================
# 8. ШИФРОВАНИЕ XML → .pkt
# =============================================================================


def _compress_qt(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + zlib.compress(data)


def _obf_stage2(data: bytes) -> bytes:
    L = len(data)
    return bytes(b ^ (L - i & 0xFF) for i, b in enumerate(data))


def _obf_stage1(data: bytes) -> bytes:
    L = len(data)
    out = bytearray(L)
    for i in range(L):
        key_byte = (L - i * L) & 0xFF
        out[L - 1 - i] = data[i] ^ key_byte
    return bytes(out)


def _encrypt_pkt(data: bytes) -> bytes:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from Decipher.eax import EAX
    from Decipher.twofish import Twofish

    key = bytes([137]) * 16
    iv = bytes([16]) * 16
    tf = Twofish(key)
    eax = EAX(tf.encrypt)
    ct, tag = eax.encrypt(nonce=iv, plaintext=data)
    return ct + tag


def xml_to_pkt(xml_path, pkt_path, log: Log = _noop) -> Path:
    xml_bytes = Path(xml_path).read_bytes()
    log("[*] Сжатие zlib…")
    s2 = _compress_qt(xml_bytes)
    log("[*] Обфускация (stage 2)…")
    s2d = _obf_stage2(s2)
    log("[*] Шифрование Twofish/EAX…")
    s1 = _encrypt_pkt(s2d)
    log("[*] Обфускация (stage 1)…")
    final = _obf_stage1(s1)
    out = Path(pkt_path)
    out.write_bytes(final)
    log(f"[+] .pkt записан: {out}")
    return out


# =============================================================================
# 9. CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="AIcpt: simplified XML → полный PT XML → .pkt")
    ap.add_argument("--white", default=str(HERE / "white.xml"))
    ap.add_argument("simplified_xml")
    ap.add_argument("--out-xml", default="realTopolog.xml")
    ap.add_argument("--out-pkt", default="realTopolog.pkt")
    args = ap.parse_args()

    def _log(m: str) -> None:
        print(m)

    build_full_xml_file(args.white, args.simplified_xml, args.out_xml, log=_log)
    xml_to_pkt(args.out_xml, args.out_pkt, log=_log)
