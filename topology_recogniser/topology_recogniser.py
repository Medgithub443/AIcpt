#!/usr/bin/env python3
"""
topology_recogniser.py
======================
Анализирует PNG/JPEG/PDF с топологией Cisco Packet Tracer.

Ключевые возможности:
  · Template matching с автоматическим определением масштаба изображения
  · Улучшенный NMS (не даёт одному устройству детектироваться дважды)
  · Верификация кабелей по тёмным пикселям (убирает ложные связи)
  · Ограничение: max 1 кабель на пару устройств
  · Опциональный OCR (easyocr или tesseract, на выбор пользователя)

Зависимости (только pip):
    pip install opencv-python numpy pillow pymupdf

Опциональный OCR:
    pip install easyocr       # ~1 GB, самодостаточный
    pip install pytesseract   # лёгкий, нужен системный tesseract

Иконки:  папка Logical/ из установки PT 6.2 рядом со скриптом,
         или указать через --icons.

Запуск:
    python topology_recogniser.py diagram.png
    python topology_recogniser.py diagram.png --table
    python topology_recogniser.py diagram.png --ocr easyocr
    python topology_recogniser.py diagram.png --aicpt-desc
    python topology_recogniser.py diagram.png --json
    python topology_recogniser.py diagram.png --debug ./dbg
"""

import argparse
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Карта иконок → (type, model, display)
# ─────────────────────────────────────────────────────────────────────────────
ICON_MAP: dict[str, tuple[str, str, str]] = {
    "iRouter.png":              ("router",          "1841",                 "Router"),
    "iSwitch.png":              ("switch",          "2950-24",              "Switch"),
    "iSwitch3560.png":          ("switch",          "3560-24PS",            "Switch3560"),
    "iWorkstation.png":         ("pc",              "PC-PT",                "PC"),
    "iServer.png":              ("server",          "Server-PT",            "Server"),
    "iServerCO.png":            ("server",          "Server-PT",            "Server"),
    "iHub.png":                 ("hub",             "Hub-PT",               "Hub"),
    "iLaptop.png":              ("laptop",          "Laptop-PT",            "Laptop"),
    "iAccessPoint.png":         ("access_point",    "AccessPoint-PT",       "AP"),
    "iLinksys.png":             ("wireless_router", "Linksys-WRT300N",      "WirelessRouter"),
    "iASA.png":                 ("firewall",        "5505",                 "ASA"),
    "iDSL.png":                 ("modem",           "DSL-Modem-PT",         "DSL-Modem"),
    "iCable.png":               ("modem",           "Cable-Modem-PT",       "Cable-Modem"),
    "iIPPhone.png":             ("ip_phone",        "7960",                 "IPPhone"),
    "iAnalogPhone.png":         ("voip",            "Analog-Phone-PT",      "Phone"),
    "iPrinter.png":             ("printer",         "Printer-PT",           "Printer"),
    "iTV.png":                  ("tv",              "TV-PT",                "TV"),
    "iTabletPC.png":            ("tablet",          "TabletPC-PT",          "Tablet"),
    "iPda.png":                 ("smartphone",      "SMARTPHONE-PT",        "PDA"),
    "iCloud.png":               ("cloud",           "Cloud-PT",             "Cloud"),
    "iRepeater.png":            ("repeater",        "Repeater-PT",          "Repeater"),
    "iBridge.png":              ("bridge",          "Bridge-PT",            "Bridge"),
    "iSniffer.png":             ("sniffer",         "Sniffer",              "Sniffer"),
    "iCellTower.png":           ("access_point",    "Cell-Tower",           "CellTower"),
    "iHomeGateway.png":         ("wireless_router", "HomeGateway-PT",       "HomeGW"),
    "iHomeVoip.png":            ("voip",            "Home-VoIP-PT",         "VoIP"),
    "iWiredEndDevice.png":      ("pc",              "WiredEndDevice-PT",    "WiredDev"),
    "iWirelessEndDevice.png":   ("laptop",          "WirelessEndDevice-PT", "WirelessDev"),
}

# Иконки-эталоны для определения масштаба (наиболее стабильные)
_SCALE_REF_ICONS = [
    "iRouter.png", "iServer.png", "iSwitch.png",
    "iWorkstation.png", "iHub.png",
]

DEFAULT_THRESHOLD  = 0.65
CABLE_VERIFY_RATE  = 0.45
PT_BG              = 255
NMS_SEP_RATIO      = 0.80   # min расстояние между центрами = max(w,h) * ratio


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Загрузка изображения
# ─────────────────────────────────────────────────────────────────────────────

def load_image(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".pdf":
        try:
            import fitz
        except ImportError:
            sys.exit("PyMuPDF не найден. Установи: pip install pymupdf")
        doc = fitz.open(str(path))
        pix = doc[0].get_pixmap(dpi=150)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pix.save(tmp.name)
            img = cv2.imread(tmp.name)
        os.unlink(tmp.name)
        if img is None:
            sys.exit("Не удалось растеризовать PDF.")
        return img
    img = cv2.imread(str(path))
    if img is None:
        sys.exit(f"Не удалось открыть: {path}")
    return img


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Подготовка шаблонов
# ─────────────────────────────────────────────────────────────────────────────

def _tpl_to_gray(path: Path) -> np.ndarray | None:
    """Загружает иконку и конвертирует в grayscale, заменяя прозрачность на белый фон."""
    tpl = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if tpl is None:
        return None
    if tpl.ndim == 3 and tpl.shape[2] == 4:
        alpha   = tpl[:, :, 3].astype(np.float32) / 255.0
        bgr     = tpl[:, :, :3].astype(np.float32)
        for c in range(3):
            bgr[:, :, c] = bgr[:, :, c] * alpha + PT_BG * (1.0 - alpha)
        bgr = bgr.astype(np.uint8)
    elif tpl.ndim == 3:
        bgr = tpl[:, :, :3]
    else:
        bgr = cv2.cvtColor(tpl, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def load_templates(icons_dir: Path) -> list[dict]:
    """Загружает все иконки из ICON_MAP."""
    templates = []
    for fname, (dev_type, model, display) in ICON_MAP.items():
        path = icons_dir / fname
        if not path.exists():
            continue
        gray = _tpl_to_gray(path)
        if gray is None:
            continue
        h, w = gray.shape
        templates.append(dict(fname=fname, type=dev_type, model=model,
                              display=display, gray=gray, h=h, w=w))
    return templates


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Автоматическое определение масштаба
# ─────────────────────────────────────────────────────────────────────────────

def detect_scale(img_gray: np.ndarray, icons_dir: Path,
                 scale_range: tuple[float, float] = (0.6, 2.5),
                 scale_step: float = 0.05) -> float:
    """
    Подбирает масштаб при котором reference-иконки дают максимальный средний score.
    Если иконки в схеме совпадают с эталонами 1:1 → вернёт 1.0.
    Работает для любого DPI/zoom Packet Tracer.
    """
    H, W = img_gray.shape
    ref_grays = []
    for fname in _SCALE_REF_ICONS:
        gray = _tpl_to_gray(icons_dir / fname)
        if gray is not None:
            ref_grays.append(gray)

    if not ref_grays:
        return 1.0

    best_scale, best_avg = 1.0, 0.0
    for scale in np.arange(scale_range[0], scale_range[1], scale_step):
        total, count = 0.0, 0
        for g in ref_grays:
            tw = int(g.shape[1] * scale)
            th = int(g.shape[0] * scale)
            if th > H or tw > W or th < 5 or tw < 5:
                continue
            resized = cv2.resize(g, (tw, th))
            res = cv2.matchTemplate(img_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, mv, _, _ = cv2.minMaxLoc(res)
            total += mv
            count += 1
        if count > 0:
            avg = total / count
            if avg > best_avg:
                best_avg, best_scale = avg, round(float(scale), 3)

    return best_scale


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Детектирование устройств (multi-scale template matching + NMS)
# ─────────────────────────────────────────────────────────────────────────────

def detect_devices(img: np.ndarray,
                   templates: list[dict],
                   threshold: float = DEFAULT_THRESHOLD,
                   scale: float = 1.0) -> list[dict]:
    """
    Для каждого шаблона:
      · масштабирует его на коэффициент `scale`
      · прогоняет matchTemplate
      · собирает все совпадения выше порога

    Затем применяет глобальный NMS:
      · сортировка по score (лучшие первыми)
      · два кандидата считаются дублями если расстояние между их центрами
        меньше max(w, h) * NMS_SEP_RATIO
    """
    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray_img.shape

    candidates = []
    for tpl in templates:
        base_h, base_w = tpl["h"], tpl["w"]
        tw = int(base_w * scale)
        th = int(base_h * scale)
        if th > H or tw > W or th < 5 or tw < 5:
            continue
        scaled_gray = cv2.resize(tpl["gray"], (tw, th))
        res = cv2.matchTemplate(gray_img, scaled_gray, cv2.TM_CCOEFF_NORMED)
        locs = np.argwhere(res >= threshold)
        for y, x in locs:
            candidates.append(dict(
                score=float(res[y, x]),
                cx=x + tw // 2,
                cy=y + th // 2,
                w=tw, h=th,
                fname=tpl["fname"],
                type=tpl["type"],
                model=tpl["model"],
                display=tpl["display"],
            ))

    # Глобальный NMS
    candidates.sort(key=lambda c: -c["score"])
    final: list[dict] = []
    for cand in candidates:
        cx, cy, cw, ch = cand["cx"], cand["cy"], cand["w"], cand["h"]
        sep = max(cw, ch) * NMS_SEP_RATIO
        if not any(
            math.sqrt((cx - d["cx"]) ** 2 + (cy - d["cy"]) ** 2) < max(sep, max(d["w"], d["h"]) * NMS_SEP_RATIO)
            for d in final
        ):
            final.append(cand)

    final.sort(key=lambda d: (d["cy"] // 40, d["cx"]))
    return final


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Детектирование цветных точек-портов
# ─────────────────────────────────────────────────────────────────────────────

def find_colour_dots(img: np.ndarray, colour: str,
                     min_area: int = 8, max_dim: int = 40) -> list[tuple[int, int]]:
    b = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    r = img[:, :, 2].astype(int)
    if colour == "red":
        mask = (r - g > 60) & (r - b > 60) & (r > 150)
    else:
        mask = (g - r > 50) & (g - b > 20) & (g > 150)
    m8 = mask.astype(np.uint8) * 255
    m8 = cv2.morphologyEx(m8, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _, stats, centroids = cv2.connectedComponentsWithStats(m8, 8)
    dots = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        if max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) > max_dim:
            continue
        dots.append((int(centroids[i][0]), int(centroids[i][1])))
    return dots


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Верификация кабеля (dark-pixel sampling)
# ─────────────────────────────────────────────────────────────────────────────

def _verify_cable(img: np.ndarray,
                  d1: tuple[int, int], d2: tuple[int, int],
                  n_samples: int = 25,
                  radius: int = 3,
                  min_hit_rate: float = CABLE_VERIFY_RATE) -> bool:
    """
    Сэмплирует точки вдоль прямой d1→d2 (пропуская крайние 15%).
    Возвращает True если >= min_hit_rate точек имеют тёмный пиксель рядом.
    """
    b  = img[:, :, 0].astype(int)
    g  = img[:, :, 1].astype(int)
    r  = img[:, :, 2].astype(int)
    dark = (b < 100) & (g < 100) & (r < 100)
    H, W = dark.shape

    hits = 0
    for t in np.linspace(0.15, 0.85, n_samples):
        px = int(d1[0] + t * (d2[0] - d1[0]))
        py = int(d1[1] + t * (d2[1] - d1[1]))
        found = False
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = px + dx, py + dy
                if 0 <= ny < H and 0 <= nx < W and dark[ny, nx]:
                    found = True
                    break
            if found:
                break
        if found:
            hits += 1
    return hits / n_samples >= min_hit_rate


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Сопоставление кабелей
# ─────────────────────────────────────────────────────────────────────────────

def _euc(p1, p2) -> float:
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _nearest_dev(dot, centers) -> int:
    return int(min(range(len(centers)), key=lambda i: _euc(dot, centers[i])))


def match_cables(red_dots: list, green_dots: list,
                 devices: list[dict],
                 img: np.ndarray) -> list[tuple[int, int]]:
    """
    Жадный matching с тремя ограничениями:
      1. Каждая точка используется не более одного раза.
      2. Каждая пара устройств — max 1 кабель.
      3. Принимается только если dark-pixel verification пройдена.
    """
    centers  = [(d["cx"], d["cy"]) for d in devices]
    all_dots = red_dots + green_dots
    if not all_dots or not centers:
        return []

    dot_dev = {dot: _nearest_dev(dot, centers) for dot in all_dots}

    pairs = []
    n = len(all_dots)
    for i in range(n):
        for j in range(i + 1, n):
            d1, d2 = all_dots[i], all_dots[j]
            dv1, dv2 = dot_dev[d1], dot_dev[d2]
            if dv1 != dv2:
                pairs.append((_euc(d1, d2), d1, d2, dv1, dv2))
    pairs.sort()

    used_dots:  set                  = set()
    used_pairs: set[tuple[int, int]] = set()
    cables:     list[tuple[int, int]] = []

    for _, d1, d2, dv1, dv2 in pairs:
        if d1 in used_dots or d2 in used_dots:
            continue
        pair_key = (min(dv1, dv2), max(dv1, dv2))
        if pair_key in used_pairs:
            continue
        if not _verify_cable(img, d1, d2):
            continue
        cables.append((dv1, dv2))
        used_dots.add(d1)
        used_dots.add(d2)
        used_pairs.add(pair_key)

    return cables


# ─────────────────────────────────────────────────────────────────────────────
# 8.  OCR (опциональный)
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_FIXES = {"184f": "1841", "18417": "1841", "29502": "2950",
                "29602": "2960", "pc-pt": "PC-PT", "pcpt": "PC-PT"}
_NAME_PFXS   = ("router", "switch", "pc", "server", "laptop", "hub",
                "ap", "dsl", "comp", "provider", "hub")
_MODEL_KNOWN = ["1841", "2811", "2901", "2911", "2950", "2960", "3560",
                "PC-PT", "Server-PT", "Laptop-PT"]


def _is_model(t: str) -> bool:
    return any(m.upper() in t.upper() for m in _MODEL_KNOWN)


def _is_name(t: str) -> bool:
    low = t.lower()
    return low.startswith(_NAME_PFXS) and not (_is_model(t) and "-" in t)


def _fix_name_tok(t: str) -> str:
    return re.sub(r'[Oo0]+$', '0', t)


def _extract_name(tokens: list[str]) -> str | None:
    fixed = [_TOKEN_FIXES.get(t.lower(), t) for t in tokens if len(t.strip()) >= 2]
    names = [_fix_name_tok(t) for t in fixed if _is_name(t)]
    return names[0] if names else None


def _ocr_tesseract(crop: np.ndarray) -> str | None:
    try:
        import pytesseract
        d = pytesseract.image_to_data(crop, config="--psm 11 --oem 3",
                                      output_type=pytesseract.Output.DICT)
        tokens = [d["text"][i] for i in range(len(d["text"]))
                  if d["text"][i].strip() and int(d["conf"][i]) >= 20]
        return _extract_name(tokens)
    except Exception:
        return None


def _ocr_easyocr(crop: np.ndarray, reader) -> str | None:
    try:
        return _extract_name(reader.readtext(crop, detail=0))
    except Exception:
        return None


def ocr_devices(img: np.ndarray, devices: list[dict],
                backend: str = "none", scale: int = 3) -> None:
    if backend == "none":
        cnt: dict[str, int] = {}
        for d in devices:
            k = d["type"]
            d["name"] = f"{d['display']}{cnt.get(k, 0)}"
            cnt[k] = cnt.get(k, 0) + 1
        return

    H, W = img.shape[:2]
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray_big = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    gray_big = cv2.filter2D(gray_big, -1,
                             np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]]))
    reader = None
    if backend == "easyocr":
        try:
            import easyocr
            reader = easyocr.Reader(["en"], verbose=False)
        except ImportError:
            print("[OCR] easyocr не установлен — авто-нумерация.", file=sys.stderr)
            backend = "none"
            return ocr_devices(img, devices, "none")

    cnt: dict[str, int] = {}
    for d in devices:
        cx, cy, dw, dh = d["cx"], d["cy"], d["w"], d["h"]
        pad = max(dw, dh)
        rx1 = max(0, cx - dw // 2 - pad);  ry1 = max(0, cy - dh // 2 - pad)
        rx2 = min(W, cx + dw // 2 + pad);  ry2 = min(H, cy + dh // 2 + pad)
        crop = gray_big[ry1*scale:ry2*scale, rx1*scale:rx2*scale]
        name = None
        if crop.size > 0:
            name = (_ocr_easyocr(crop, reader) if backend == "easyocr"
                    else _ocr_tesseract(crop))
        if not name:
            k = d["type"]
            name = f"{d['display']}{cnt.get(k, 0)}"
            cnt[k] = cnt.get(k, 0) + 1
        d["name"] = name


# ─────────────────────────────────────────────────────────────────────────────
# 9.  Форматирование вывода
# ─────────────────────────────────────────────────────────────────────────────

def build_table(cables: list[tuple[int, int]], devices: list[dict]) -> list[dict]:
    port_cnt: dict[int, int] = {}
    rows, row_id = [], 0
    for dv_a, dv_b in cables:
        pa = port_cnt.get(dv_a, 0);  port_cnt[dv_a] = pa + 1
        pb = port_cnt.get(dv_b, 0);  port_cnt[dv_b] = pb + 1
        ia = f"int{dv_a}_{pa}";  ib = f"int{dv_b}_{pb}"
        la = f"{devices[dv_a]['model']} ({devices[dv_a]['name']})"
        lb = f"{devices[dv_b]['model']} ({devices[dv_b]['name']})"
        rows.append({"id": row_id, "device": la, "interface": ia,
                     "connected_to": f"{ib} ({lb})"});  row_id += 1
        rows.append({"id": row_id, "device": lb, "interface": ib,
                     "connected_to": f"{ia} ({la})"});  row_id += 1
    return rows


def render_table(rows: list[dict]) -> str:
    if not rows:
        return "(связи не найдены)"
    headers = ["ID", "Device", "Interface", "Connected To"]
    cols = [[str(r["id"]) for r in rows], [r["device"] for r in rows],
            [r["interface"] for r in rows], [r["connected_to"] for r in rows]]
    widths = [max(len(headers[i]), max(len(v) for v in cols[i])) for i in range(4)]
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    hdr = "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(4)) + " |"
    lines = [sep, hdr, sep]
    for r in rows:
        cells = [str(r["id"]), r["device"], r["interface"], r["connected_to"]]
        lines.append("| " + " | ".join(cells[i].ljust(widths[i]) for i in range(4)) + " |")
    lines.append(sep)
    return "\n".join(lines)


def render_links(cables: list[tuple[int, int]], devices: list[dict]) -> str:
    lines = []
    for dv_a, dv_b in cables:
        lines.append(f"  {devices[dv_a]['name']} — {devices[dv_b]['name']}")
    return "\n".join(lines)


def render_devices(devices: list[dict]) -> str:
    lines = []
    for i, d in enumerate(devices):
        lines.append(f"  [{i:2d}] {d['model']:<22} {d['name']:<20} score={d['score']:.3f}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 10. AIcpt description
# ─────────────────────────────────────────────────────────────────────────────

def build_aicpt_description(devices: list[dict],
                             cables: list[tuple[int, int]]) -> str:
    SEP = "=" * 72
    lines = [SEP,
             "# TOPOLOGY RECOGNISED FROM DIAGRAM (auto-generated, do not edit)",
             SEP, "",
             f"Devices found : {len(devices)}",
             f"Links found   : {len(cables)}", "",
             "## DEVICES", ""]
    for i, d in enumerate(devices):
        lines.append(f"  [{i}]  name={d['name']!r:<22} "
                     f"type={d['type']:<18} model={d['model']}")
    lines.append("")
    lines.append("## PHYSICAL LINKS")
    lines.append("")
    port_cnt: dict[int, int] = {}
    for dv_a, dv_b in cables:
        pa = port_cnt.get(dv_a, 0);  port_cnt[dv_a] = pa + 1
        pb = port_cnt.get(dv_b, 0);  port_cnt[dv_b] = pb + 1
        na, nb = devices[dv_a]["name"], devices[dv_b]["name"]
        ma, mb = devices[dv_a]["model"], devices[dv_b]["model"]
        lines.append(f"  {na} ({ma})  ──  {nb} ({mb})")
    lines += ["",
              "## INSTRUCTIONS FOR AI", "",
              "  - Use the device list and link list above to build the <network> XML.",
              "  - Preserve device names exactly as shown (they come from the diagram).",
              "  - IP addresses, subnets and gateway values are NOT known — assign them.",
              "  - Choose interface names per model from the devices_reference.",
              "  - Wire devices in <links> exactly as shown in PHYSICAL LINKS.",
              "  - Add routing / VLAN / DHCP config as required by the task description.",
              "", SEP]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Debug overlay
# ─────────────────────────────────────────────────────────────────────────────

def save_debug(img, devices, cables, red_dots, green_dots, path):
    vis = img.copy()
    centers = [(d["cx"], d["cy"]) for d in devices]
    for dv_a, dv_b in cables:
        cv2.line(vis, centers[dv_a], centers[dv_b], (255, 140, 0), 2)
    for i, d in enumerate(devices):
        x, y = d["cx"] - d["w"] // 2, d["cy"] - d["h"] // 2
        cv2.rectangle(vis, (x, y), (x + d["w"], y + d["h"]), (0, 200, 0), 1)
        cv2.putText(vis, f"[{i}]{d.get('name', d['display'])}",
                    (x, max(y - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (0, 160, 0), 1, cv2.LINE_AA)
    for dot in red_dots:
        cv2.circle(vis, dot, 5, (0, 0, 255), -1)
    for dot in green_dots:
        cv2.circle(vis, dot, 5, (0, 200, 0), -1)
    cv2.imwrite(path, vis)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Главный pipeline
# ─────────────────────────────────────────────────────────────────────────────

def recognise(image_path: Path,
              icons_dir: Path,
              ocr_backend: str = "none",
              threshold: float = DEFAULT_THRESHOLD,
              scale: float | None = None,
              debug_dir: str | None = None) -> dict:
    """
    Публичный API.

    scale=None → масштаб определяется автоматически.
    scale=1.0  → без масштабирования (поведение предыдущих версий).
    """
    img = load_image(image_path)
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "0_input.png"), img)

    templates = load_templates(icons_dir)
    if not templates:
        sys.exit(f"Иконки не найдены в {icons_dir}.")

    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Автоматическое определение масштаба
    if scale is None:
        scale = detect_scale(gray_img, icons_dir)
        print(f"[topology_recogniser] Auto scale: {scale:.2f}", file=sys.stderr)

    devices    = detect_devices(img, templates, threshold, scale)
    ocr_devices(img, devices, backend=ocr_backend)
    red_dots   = find_colour_dots(img, "red")
    green_dots = find_colour_dots(img, "green")
    cables     = match_cables(red_dots, green_dots, devices, img)

    if debug_dir:
        save_debug(img, devices, cables, red_dots, green_dots,
                   os.path.join(debug_dir, "9_annotated.png"))

    return dict(devices=devices, cables=cables,
                rows=build_table(cables, devices),
                aicpt_description=build_aicpt_description(devices, cables),
                scale=scale)


# ─────────────────────────────────────────────────────────────────────────────
# 13. CLI
# ─────────────────────────────────────────────────────────────────────────────

def _find_icons_dir() -> Path:
    for c in [Path(__file__).parent / "Logical",
              Path(__file__).parent / "icons",
              Path(r"C:\Program Files\Cisco Packet Tracer 6.2sv\art\Workspace\Logical"),
              Path("/opt/pt/art/Workspace/Logical")]:
        if c.exists():
            return c
    return Path(__file__).parent / "Logical"


def main():
    ap = argparse.ArgumentParser(
        description="topology_recogniser — детектирование топологии Cisco PT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
примеры:
  python topology_recogniser.py diagram.png
  python topology_recogniser.py diagram.png --table
  python topology_recogniser.py diagram.png --ocr easyocr
  python topology_recogniser.py diagram.png --aicpt-desc
  python topology_recogniser.py diagram.png --json
  python topology_recogniser.py diagram.png --scale 1.2
  python topology_recogniser.py diagram.png --debug ./dbg
""")
    ap.add_argument("file")
    ap.add_argument("--icons",      default=str(_find_icons_dir()),
                    help="Папка Logical/ с иконками PT (default: ./Logical)")
    ap.add_argument("--ocr",        choices=["none", "easyocr", "tesseract"],
                    default="none", help="OCR-бэкенд (default: none)")
    ap.add_argument("--threshold",  type=float, default=DEFAULT_THRESHOLD,
                    help=f"Порог template matching (default: {DEFAULT_THRESHOLD})")
    ap.add_argument("--scale",      type=float, default=None,
                    help="Масштаб иконок (default: авто-определение)")
    ap.add_argument("--table",      action="store_true",
                    help="Вывести полную таблицу ID/Device/Interface/Connected To")
    ap.add_argument("--json",       action="store_true",
                    help="Вывод в JSON")
    ap.add_argument("--aicpt-desc", action="store_true",
                    help="Вывести блок описания для AIcpt prompt_builder")
    ap.add_argument("--debug",      metavar="DIR",
                    help="Сохранить отладочные изображения в DIR")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"Файл не найден: {path}")

    icons_dir = Path(args.icons)
    if not icons_dir.exists():
        sys.exit(f"Папка иконок не найдена: {icons_dir}\n"
                 f"Положи Logical/ рядом со скриптом или укажи --icons /путь")

    n_icons = sum(1 for f in icons_dir.iterdir() if f.suffix == ".png")
    print(f"[topology_recogniser] {path.name}  |  иконки: {icons_dir} ({n_icons} PNG)",
          file=sys.stderr)

    result = recognise(path, icons_dir,
                       ocr_backend=args.ocr,
                       threshold=args.threshold,
                       scale=args.scale,
                       debug_dir=args.debug)

    devices = result["devices"]
    cables  = result["cables"]
    rows    = result["rows"]

    if args.aicpt_desc:
        print(result["aicpt_description"])
        return

    if args.json:
        print(json.dumps({
            "scale":   result["scale"],
            "devices": [{"idx": i, "name": d["name"], "type": d["type"],
                         "model": d["model"], "cx": d["cx"], "cy": d["cy"],
                         "score": round(d["score"], 3)}
                        for i, d in enumerate(devices)],
            "cables": [{"from": a, "to": b} for a, b in cables],
            "table":  rows,
        }, indent=2, ensure_ascii=False))
        return

    print()
    print("Devices:")
    print(render_devices(devices))
    print()
    print("Links:")
    print(render_links(cables, devices))
    print()
    if args.table:
        print(render_table(rows))
        print()
    print(f"  Устройств : {len(devices)}")
    print(f"  Кабелей   : {len(cables)}")
    print(f"  Масштаб   : {result['scale']:.2f}")
    print()


if __name__ == "__main__":
    main()
