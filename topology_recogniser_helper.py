"""AIcpt — topology_recogniser_helper  (v 0.4.1-alfa)

Принимает готовое изображение топологии (.png / .jpg / .jpeg),
прогоняет его через topology_recogniser и возвращает текстовое описание
(устройства + связи).

PDF и DOCX в этой версии **не поддерживаются** — пользователь должен
прислать скриншот схемы напрямую.

Использование:
    desc = recognise_from_image(Path("topology.png"))
    if desc:
        # desc — готовый блок текста для prompt_for_ai.txt
        ...

Исправление v 0.4.1-alfa:
    Все пути к файлам передаются через pathlib.Path и конвертируются
    в строку только там, где это необходимо, чтобы корректно обрабатывать
    пути с пробелами в имени каталога.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECOGNISER_DIR = HERE / "topology_recogniser"
ICONS_DIR = RECOGNISER_DIR / "Logical"

_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg"}


def _ensure_recogniser_on_path() -> None:
    p = str(RECOGNISER_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def recognise_from_image(
    path: Path,
    icons_dir: Path | None = None,
    min_devices: int = 2,
) -> str | None:
    """Прогоняет изображение через topology_recogniser.

    Принимает только .png / .jpg / .jpeg.
    Возвращает текстовое описание (aicpt_description) или None, если найдено
    меньше `min_devices` устройств.

    Параметры
    ---------
    path        : путь к файлу изображения (может содержать пробелы)
    icons_dir   : каталог с иконками (по умолчанию рядом со скриптом)
    min_devices : минимальное число устройств для успешного результата
    """
    path = Path(path).resolve()   # нормализуем — пробелы в пути не проблема

    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(
            f"Неподдерживаемый формат: «{ext}». "
            f"Используй .png, .jpg или .jpeg.\n"
            f"PDF и DOCX в этой версии не поддерживаются."
        )

    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    _ensure_recogniser_on_path()
    try:
        import topology_recogniser as tr
    except ImportError as e:
        raise ImportError(
            f"topology_recogniser не загрузился: {e}.\n"
            f"Проверь зависимости: pip install opencv-python numpy pillow"
        ) from e

    icons = (icons_dir or ICONS_DIR).resolve()
    if not icons.exists():
        raise FileNotFoundError(f"Не найдена папка иконок: {icons}")

    try:
        res = tr.recognise(path, icons, ocr_backend="none")
    except SystemExit:
        # topology_recogniser вызывает sys.exit() при ошибке загрузки картинки
        return None
    except Exception:
        return None

    n = len(res.get("devices", []))
    if n < min_devices:
        return None

    return res.get("aicpt_description")


# ---------------------------------------------------------------------------
# Обратная совместимость: старый код мог вызывать recognise_from_document
# ---------------------------------------------------------------------------

def recognise_from_document(
    path: Path,
    icons_dir: Path | None = None,
    min_devices: int = 2,
) -> str | None:
    """Устаревший псевдоним.  Принимает только .png / .jpg / .jpeg.

    PDF и DOCX больше не поддерживаются — передавай скриншот схемы.
    """
    return recognise_from_image(path, icons_dir=icons_dir, min_devices=min_devices)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Распознаёт схему сети из PNG/JPEG."
    )
    ap.add_argument("file", help=".png / .jpg / .jpeg со схемой")
    ap.add_argument("--min-devices", type=int, default=2)
    args = ap.parse_args()

    desc = recognise_from_image(Path(args.file), min_devices=args.min_devices)
    if desc is None:
        print("[!] Схема сети не найдена или устройств слишком мало.", file=sys.stderr)
        sys.exit(1)
    print(desc)
