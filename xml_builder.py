"""AIcpt — xml_builder (template-based).

Берёт реальные DEVICE-шаблоны из templates/*.xml (извлечены из настоящих
файлов Packet Tracer 6.2), подставляет в них имя, IP, координаты и
running-config и вклеивает в white.xml. Результат — валидный PT XML.

Без шаблонов PT считает файл несовместимым: ему нужны десятки полей
(FILE_MANAGER, ALGORITHM_SETTINGS, SECURITY, VLANS, VTP, TERMINAL_SETTINGS,
WIRELESS_CLIENT, IPV6_*, eTrs35/eUsb SLOT'ы и т.д.). Мы их сохраняем
один-в-один из реального файла.
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
# 1. Шаблоны устройств и их конфигурация
# =============================================================================

# type / model → (template_file, oui_prefix_for_mac, port_mapping)
#
# port_mapping — как имя IOS-интерфейса (FastEthernet0/1) мапится на
# N-ный <PORT> внутри шаблона (по порядку обхода дерева MODULE).

_DEVICE_PROFILE = {
    # end-hosts → pc-pt.xml
    "pc-pt": {
        "template": "pc-pt.xml", "oui": "0060.5C",
        "ports": ["FastEthernet0"],
        "has_running_config": False,
        "has_gateway": True,
    },
    # router → 1841.xml
    "1841": {
        "template": "1841.xml", "oui": "0001.42",
        "ports": ["FastEthernet0/0", "FastEthernet0/1"],
        "has_running_config": True,
        "has_gateway": False,
    },
    # switch → 2950-24.xml
    "2950-24": {
        "template": "2950-24.xml", "oui": "0010.11",
        "ports": [f"FastEthernet0/{i}" for i in range(1, 25)],
        "has_running_config": True,
        "has_gateway": False,
    },
}

# высокоуровневый type → стандартный профиль
_TYPE_DEFAULT = {
    "pc": "pc-pt", "laptop": "pc-pt", "server": "pc-pt", "printer": "pc-pt",
    "ip_phone": "pc-pt",
    "router": "1841",
    "switch": "2950-24",
    # прочее — жёсткий fallback на свитч (хаб и т.п. сложно поддержать)
    "access_point": "pc-pt", "hub": "2950-24", "cloud": "pc-pt",
}

# явные модели, которые мы умеем вернуть в TYPE@model (но шаблон тот же)
_KNOWN_MODELS = {
    "PC-PT", "Laptop-PT", "Server-PT", "Printer-PT", "7960",
    "1841", "1941", "2620XM", "2621XM", "2811", "2901", "2911",
    "2950-24", "2950T-24", "2960-24TT", "3560-24PS",
    "Switch-PT", "Switch-PT-Empty", "Router-PT", "Router-PT-Empty",
    "AccessPoint-PT", "Hub-PT", "Cloud-PT",
}


def _profile_for(dtype: str, model: str) -> tuple[str, dict]:
    """Возвращает (имя_профиля, его_параметры)."""
    key = _TYPE_DEFAULT.get(dtype.lower(), "pc-pt")
    return key, _DEVICE_PROFILE[key]


# =============================================================================
# 2. Утилиты
# =============================================================================


def _gen_mac(oui: str, device_idx: int, port_idx: int) -> str:
    # oui в формате "0060.5C"
    low = (device_idx * 100 + port_idx) & 0xFFFFFF
    return f"{oui}{low >> 16 & 0xFF:02X}.{low & 0xFFFF:04X}"


def _mac_to_eui64_ll(mac: str) -> str:
    """'0060.5CC0.5346' → 'FE80::260:5CFF:FEC0:5346'"""
    hx = mac.replace(".", "").upper()
    b = [int(hx[i : i + 2], 16) for i in range(0, 12, 2)]
    b[0] ^= 0x02
    groups = [
        f"{b[0]:X}{b[1]:02X}",
        f"{b[2]:02X}FF",
        f"FE{b[3]:02X}",
        f"{b[4]:02X}{b[5]:02X}",
    ]
    return "FE80::" + ":".join(groups).upper()


def _gen_serial(profile_key: str, idx: int) -> str:
    if profile_key == "pc-pt":
        return f"PTT{idx:04d}X{idx * 7 % 1000:03d}"
    if profile_key.startswith("29") or profile_key.startswith("39"):
        return f"FOC{idx:04d}Z{idx * 11 % 100:02d}A"
    return f"FTX{idx:04d}Y{idx * 13 % 1000:03d}"


def _set_text(el: ET.Element | None, text: str) -> None:
    if el is not None:
        el.text = text


def _find_all_ports(engine: ET.Element) -> list[ET.Element]:
    """Обходит MODULE-дерево engine и возвращает все <PORT> в DFS-порядке."""
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
# 3. Парсинг упрощённого XML (как было)
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

        gateway = None
        for iface in interfaces:
            if iface.get("gateway"):
                gateway = iface["gateway"]
                break

        devices.append({
            "name": name, "type": dtype, "model": model,
            "x": x, "y": y,
            "interfaces": interfaces, "vlans": vlans,
            "config_lines": cfg_lines, "gateway": gateway,
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


# =============================================================================
# 4. Мутация шаблона под конкретное устройство
# =============================================================================


_TEMPLATE_CACHE: dict[str, bytes] = {}


def _load_template(filename: str) -> ET.Element:
    """Читает templates/filename и парсит в Element. Кеширует байты."""
    path = TEMPLATES_DIR / filename
    if filename not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[filename] = path.read_bytes()
    return ET.fromstring(_TEMPLATE_CACHE[filename])


def _apply_interface(
    port: ET.Element, mac: str, iface: dict | None, is_serial: bool = False
) -> None:
    """Обновляет MACADDRESS/BIA (+IPV6_LL) и, если есть iface, IP/SUBNET."""
    _set_text(port.find("MACADDRESS"), mac)
    _set_text(port.find("BIA"), mac)

    ll = _mac_to_eui64_ll(mac)
    for tag in ("IPV6_LINK_LOCAL", "IPV6_DEFAULT_LINK_LOCAL"):
        el = port.find(tag)
        if el is not None:
            el.text = ll

    if iface is None:
        # пустые IP/SUBNET шаблона оставляем
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
    """Заменяет содержимое <RUNNINGCONFIG> или <STARTUPCONFIG> на lines."""
    cfg = engine.find(tag)
    if cfg is None:
        cfg = ET.SubElement(engine, tag)
    # очистить всех детей
    for c in list(cfg):
        cfg.remove(c)
    for line in lines:
        ln = ET.SubElement(cfg, "LINE")
        ln.text = line


def _replace_vlans(engine: ET.Element, user_vlans: list[dict]) -> None:
    """Добавляет пользовательские VLAN'ы к дефолтным (1/1002-1005)."""
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
        name = str(v.get("name", ""))
        ET.SubElement(vlans, "VLAN", number=num, name=name)
        existing_nums.add(num)


def _update_workspace(dev_node: ET.Element, x: float, y: float, name: str) -> None:
    ws = dev_node.find("WORKSPACE")
    if ws is None:
        return
    logical = ws.find("LOGICAL")
    if logical is not None:
        _set_text(logical.find("X"), f"{x}")
        _set_text(logical.find("Y"), f"{y}")
        # MEM_ADDR / DEV_ADDR — оставить или обнулить
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


def _effective_config_lines(dev: dict, profile_key: str) -> list[str] | None:
    """Если config пустой — синтезируем минимальный running-config для router/switch."""
    if dev["config_lines"]:
        return dev["config_lines"]

    is_router = profile_key == "1841"
    is_switch = profile_key == "2950-24"
    if not (is_router or is_switch):
        return None

    lines = [
        "!",
        "version 12.4" if is_router else "version 12.1",
        "no service timestamps log datetime msec",
        "no service timestamps debug datetime msec",
        "no service password-encryption",
        "!",
        f"hostname {dev['name']}",
        "!",
        "spanning-tree mode pvst",
        "!",
    ]

    if is_router:
        cfg_ports = ["FastEthernet0/0", "FastEthernet0/1"]
        iface_map = {i["name"]: i for i in dev["interfaces"]}
        for p in cfg_ports:
            iface = iface_map.get(p)
            lines.append(f"interface {p}")
            if iface and iface.get("ip") and iface.get("subnet"):
                lines.append(f" ip address {iface['ip']} {iface['subnet']}")
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
            "ip classless", "!",
            "line con 0", "!",
            "line aux 0", "!",
            "line vty 0 4", " login", "!",
            "end",
        ])
    else:  # switch
        iface_map = {i["name"]: i for i in dev["interfaces"]}
        for i in range(1, 25):
            p = f"FastEthernet0/{i}"
            iface = iface_map.get(p)
            lines.append(f"interface {p}")
            if iface and iface.get("vlan"):
                lines.append(" switchport mode access")
                lines.append(f" switchport access vlan {iface['vlan']}")
            lines.append("!")
        lines.extend([
            "interface Vlan1", " no ip address", " shutdown", "!",
            "line con 0", "!",
            "line vty 0 4", " login",
            "line vty 5 15", " login", "!",
            "end",
        ])
    return lines


def build_device(dev: dict, device_idx: int) -> ET.Element:
    """Строит полный <DEVICE> на базе шаблона."""
    profile_key, profile = _profile_for(dev["type"], dev.get("model") or "")
    template = _load_template(profile["template"])
    node = copy.deepcopy(template)

    engine = node.find("ENGINE")
    if engine is None:
        raise RuntimeError(f"шаблон {profile['template']} без <ENGINE>?")

    # --- TYPE / NAME / SYS_NAME ---
    type_el = engine.find("TYPE")
    if type_el is not None:
        # Если юзер задал явную модель — подставим; иначе оставим шаблонную
        if dev.get("model") and dev["model"] in _KNOWN_MODELS:
            type_el.set("model", dev["model"])
        # customModel всегда пусто
        type_el.set("customModel", "")
        # текст (Router / Switch / Pc) оставляем из шаблона

    name_el = engine.find("NAME")
    if name_el is not None:
        name_el.text = dev["name"]

    sys_name_el = engine.find("SYS_NAME")
    if sys_name_el is not None:
        sys_name_el.text = dev["name"]

    serial_el = engine.find("SERIALNUMBER")
    if serial_el is not None:
        serial_el.text = _gen_serial(profile_key, device_idx + 1)

    # --- MAC + IPV6-LL + IP/SUBNET по PORT'ам ---
    ports = _find_all_ports(engine)
    port_names = profile["ports"]
    iface_map = {i["name"]: i for i in dev["interfaces"]}

    for pi, port in enumerate(ports):
        mac = _gen_mac(profile["oui"], device_idx + 1, pi + 1)
        pname = port_names[pi] if pi < len(port_names) else None
        iface = iface_map.get(pname) if pname else None
        _apply_interface(port, mac, iface)

    # --- GATEWAY для endpoint'ов ---
    if profile["has_gateway"] and dev.get("gateway"):
        gw = engine.find("GATEWAY")
        if gw is None:
            gw = ET.SubElement(engine, "GATEWAY")
        gw.text = dev["gateway"]

    # --- RUNNING/STARTUP config ---
    if profile["has_running_config"]:
        lines = _effective_config_lines(dev, profile_key)
        if lines is not None:
            _replace_config(engine, "RUNNINGCONFIG", lines)
            _replace_config(engine, "STARTUPCONFIG", lines)

    # --- VLANS (switch) ---
    if profile_key == "2950-24" and dev["vlans"]:
        _replace_vlans(engine, dev["vlans"])

    # --- WORKSPACE ---
    _update_workspace(node, dev["x"], dev["y"], dev["name"])

    return node


# =============================================================================
# 5. LINK
# =============================================================================

_LINK_TYPE = {
    "copper":    ("eCopper", "eStraightThrough"),
    "crossover": ("eCopper", "eCrossOver"),
    "serial":    ("eSerial", "eStraightThrough"),
    "fiber":     ("eFiber",  "eStraightThrough"),
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
# 6. Сборка итогового XML
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


def build_full_xml(
    white_xml_text: str,
    simplified_xml_text: str,
    log: Log = _noop,
) -> str:
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
        node = build_device(dev, idx)
        devices_node.append(node)
        log(f"    + {dev['name']} ({dev['type']}, {dev.get('model') or 'default'})")

    for link in links:
        devices_node  # just to silence
        n = build_link(link, name_to_index)
        links_node.append(n)
        log(f"    + {link['from']}:{link['from_port']} "
            f"<-{link['type']}-> {link['to']}:{link['to_port']}")

    _indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def build_full_xml_file(
    white_xml_path: str | Path,
    simplified_xml_path: str | Path,
    output_xml_path: str | Path,
    log: Log = _noop,
) -> Path:
    white = Path(white_xml_path).read_text(encoding="utf-8")
    simp = Path(simplified_xml_path).read_text(encoding="utf-8", errors="replace")
    full = build_full_xml(white, simp, log=log)
    out = Path(output_xml_path)
    out.write_text(full, encoding="utf-8")
    return out


# =============================================================================
# 7. Шифрование XML → .pkt
# =============================================================================


def _compress_qt(xml_data: bytes) -> bytes:
    return struct.pack(">I", len(xml_data)) + zlib.compress(xml_data)


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


def xml_to_pkt(xml_path: str | Path, pkt_path: str | Path, log: Log = _noop) -> Path:
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
# 8. CLI
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
