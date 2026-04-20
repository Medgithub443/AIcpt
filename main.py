#!/usr/bin/env python3
"""AIcpt — главный запускатор.

Режимы:
  python main.py --gui              — открыть PyQt5 GUI (по умолчанию)
  python main.py prompt <файл>      — CLI: собрать prompt_for_ai.txt
  python main.py build <simpl.xml>  — CLI: собрать полный XML и .pkt
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import prompt_builder
import xml_builder


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE
WHITE_XML = HERE / "white.xml"


# ---------------------------- CLI -----------------------------------------


def cli_prompt(args: argparse.Namespace) -> int:
    session, prompt_path = prompt_builder.run(
        args.user_file, ASSETS_DIR, HERE / "output"
    )
    print(f"[+] Сессия:  {session}")
    print(f"[+] Промпт:  {prompt_path}")
    print("    Скопируй его содержимое в Claude/ChatGPT и сохрани ответ "
          "нейросети в файл simplified.xml.")
    return 0


def cli_build(args: argparse.Namespace) -> int:
    if not WHITE_XML.exists():
        print(f"[-] Нет {WHITE_XML}. Положи white.xml рядом с main.py.")
        return 2
    simp_path = Path(args.simplified_xml)
    out_dir = simp_path.parent if args.inplace else prompt_builder.make_output_dir(
        HERE / "output"
    )
    full_xml_path = out_dir / "realTopolog.xml"
    pkt_path = out_dir / "realTopolog.pkt"

    xml_builder.build_full_xml_file(
        white_xml_path=WHITE_XML,
        simplified_xml_path=simp_path,
        output_xml_path=full_xml_path,
    )
    print(f"[+] Полный XML: {full_xml_path}")

    xml_builder.xml_to_pkt(full_xml_path, pkt_path)
    print(f"[+] .pkt файл:  {pkt_path}")
    return 0


def build_cli() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="AIcpt")
    ap.add_argument("--gui", action="store_true", help="Открыть GUI (по умолчанию)")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("prompt", help="Собрать prompt_for_ai.txt из txt/pdf/docx")
    p1.add_argument("user_file")

    p2 = sub.add_parser("build", help="Собрать полный XML и .pkt из simplified.xml")
    p2.add_argument("simplified_xml")
    p2.add_argument(
        "--inplace",
        action="store_true",
        help="Класть результат в ту же папку, что и simplified.xml",
    )

    return ap


# ---------------------------- GUI -----------------------------------------


def run_gui() -> int:
    try:
        from PyQt5 import QtCore, QtWidgets
    except ImportError:
        print("[-] PyQt5 не установлен. Установи:  pip install PyQt5")
        return 2

    class AIcptWindow(QtWidgets.QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("AIcpt — описание сети → Cisco Packet Tracer")
            self.resize(1000, 720)
            self.session_dir: Path | None = None
            self.prompt_path: Path | None = None
            self._build_ui()

        # ---- layout ----
        def _build_ui(self) -> None:
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            root = QtWidgets.QVBoxLayout(central)

            tabs = QtWidgets.QTabWidget()
            root.addWidget(tabs, 1)

            tabs.addTab(self._tab_prompt(), "1. Промпт для нейросети")
            tabs.addTab(self._tab_build(), "2. Сборка .pkt")

            self.status = self.statusBar()
            self.status.showMessage("Готово. Выбери txt/pdf/docx с описанием сети.")

        def _tab_prompt(self) -> QtWidgets.QWidget:
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)

            row = QtWidgets.QHBoxLayout()
            self.user_file_edit = QtWidgets.QLineEdit()
            self.user_file_edit.setPlaceholderText(
                "Файл с описанием сети (txt / pdf / docx)"
            )
            btn_browse = QtWidgets.QPushButton("Обзор…")
            btn_browse.clicked.connect(self._pick_user_file)
            row.addWidget(self.user_file_edit, 1)
            row.addWidget(btn_browse)
            lay.addLayout(row)

            btn_build_prompt = QtWidgets.QPushButton(
                "Собрать prompt_for_ai.txt"
            )
            btn_build_prompt.clicked.connect(self._do_build_prompt)
            lay.addWidget(btn_build_prompt)

            self.prompt_view = QtWidgets.QPlainTextEdit()
            self.prompt_view.setReadOnly(True)
            self.prompt_view.setPlaceholderText(
                "Здесь появится собранный промпт. "
                "Кнопкой ниже можно скопировать его в буфер обмена "
                "и вставить в Claude / ChatGPT."
            )
            lay.addWidget(self.prompt_view, 1)

            row2 = QtWidgets.QHBoxLayout()
            btn_copy = QtWidgets.QPushButton("Скопировать в буфер")
            btn_copy.clicked.connect(self._copy_prompt)
            btn_open = QtWidgets.QPushButton("Открыть папку сессии")
            btn_open.clicked.connect(self._open_session_dir)
            row2.addWidget(btn_copy)
            row2.addWidget(btn_open)
            row2.addStretch(1)
            lay.addLayout(row2)

            return w

        def _tab_build(self) -> QtWidgets.QWidget:
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)

            hint = QtWidgets.QLabel(
                "Вставь сюда упрощённый XML, который вернула нейросеть, "
                "либо загрузи его из файла:"
            )
            lay.addWidget(hint)

            row = QtWidgets.QHBoxLayout()
            btn_load = QtWidgets.QPushButton("Загрузить simplified.xml…")
            btn_load.clicked.connect(self._load_simplified)
            row.addWidget(btn_load)
            row.addStretch(1)
            lay.addLayout(row)

            self.simpl_edit = QtWidgets.QPlainTextEdit()
            self.simpl_edit.setPlaceholderText("<network> …упрощённый XML… </network>")
            lay.addWidget(self.simpl_edit, 1)

            btn_build = QtWidgets.QPushButton("Собрать полный XML и .pkt")
            btn_build.clicked.connect(self._do_build_pkt)
            lay.addWidget(btn_build)

            self.build_log = QtWidgets.QPlainTextEdit()
            self.build_log.setReadOnly(True)
            self.build_log.setMaximumBlockCount(500)
            lay.addWidget(self.build_log, 1)

            return w

        # ---- handlers ----
        def _pick_user_file(self) -> None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Выбери файл с описанием сети",
                "",
                "Документы (*.txt *.md *.pdf *.docx);;Все файлы (*)",
            )
            if path:
                self.user_file_edit.setText(path)

        def _do_build_prompt(self) -> None:
            path = self.user_file_edit.text().strip()
            if not path:
                QtWidgets.QMessageBox.warning(
                    self, "AIcpt", "Сначала выбери файл с описанием сети."
                )
                return
            try:
                session, prompt_path = prompt_builder.run(
                    path, ASSETS_DIR, HERE / "output"
                )
            except Exception as e:
                self._show_error("Не удалось собрать промпт", e)
                return

            self.session_dir = session
            self.prompt_path = prompt_path
            text = prompt_path.read_text(encoding="utf-8")
            self.prompt_view.setPlainText(text)
            self.status.showMessage(f"Промпт сохранён: {prompt_path}")

        def _copy_prompt(self) -> None:
            text = self.prompt_view.toPlainText()
            if not text:
                return
            QtWidgets.QApplication.clipboard().setText(text)
            self.status.showMessage("Скопировано в буфер обмена.", 4000)

        def _open_session_dir(self) -> None:
            if not self.session_dir:
                return
            import subprocess
            import platform

            p = str(self.session_dir)
            if platform.system() == "Darwin":
                subprocess.Popen(["open", p])
            elif platform.system() == "Windows":
                subprocess.Popen(["explorer", p])
            else:
                subprocess.Popen(["xdg-open", p])

        def _load_simplified(self) -> None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Выбери simplified.xml от нейросети",
                "",
                "XML (*.xml);;Все файлы (*)",
            )
            if not path:
                return
            try:
                self.simpl_edit.setPlainText(
                    Path(path).read_text(encoding="utf-8", errors="replace")
                )
            except Exception as e:
                self._show_error("Не смог прочитать файл", e)

        def _do_build_pkt(self) -> None:
            simpl_text = self.simpl_edit.toPlainText().strip()
            if not simpl_text:
                QtWidgets.QMessageBox.warning(
                    self, "AIcpt", "Вставь упрощённый XML или загрузи его из файла."
                )
                return
            if not WHITE_XML.exists():
                QtWidgets.QMessageBox.critical(
                    self, "AIcpt", f"Нет шаблона {WHITE_XML}."
                )
                return

            out_dir = self.session_dir or prompt_builder.make_output_dir(
                HERE / "output"
            )
            self.session_dir = out_dir
            simp_path = out_dir / "simplified.xml"
            simp_path.write_text(simpl_text, encoding="utf-8")

            full_xml = out_dir / "realTopolog.xml"
            pkt_path = out_dir / "realTopolog.pkt"

            self.build_log.clear()
            self._log(f"[*] Сессия:   {out_dir}")
            self._log(f"[*] Шаблон:   {WHITE_XML}")
            self._log(f"[*] Входной:  {simp_path}")

            try:
                xml_builder.build_full_xml_file(
                    white_xml_path=WHITE_XML,
                    simplified_xml_path=simp_path,
                    output_xml_path=full_xml,
                    log=self._log,
                )
                self._log(f"[+] Полный XML собран: {full_xml}")
            except Exception as e:
                self._show_error("Ошибка при сборке полного XML", e)
                self._log(f"[-] {e}")
                return

            try:
                xml_builder.xml_to_pkt(full_xml, pkt_path, log=self._log)
                self._log(f"[+] .pkt файл готов: {pkt_path}")
            except Exception as e:
                self._show_error(
                    "Полный XML собран, но не удалось упаковать в .pkt", e
                )
                self._log(f"[-] {e}")
                return

            self.status.showMessage(f".pkt сохранён: {pkt_path}")

        def _log(self, msg: str) -> None:
            self.build_log.appendPlainText(str(msg))
            QtWidgets.QApplication.processEvents()

        def _show_error(self, title: str, exc: Exception) -> None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            QtWidgets.QMessageBox.critical(self, title, f"{exc}\n\n{tb}")

    app = QtWidgets.QApplication(sys.argv)
    win = AIcptWindow()
    win.show()
    return app.exec_()


# ---------------------------- entry ---------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or (len(argv) == 1 and argv[0] == "--gui"):
        return run_gui()

    ap = build_cli()
    args = ap.parse_args(argv)

    if args.cmd == "prompt":
        return cli_prompt(args)
    if args.cmd == "build":
        return cli_build(args)
    if args.gui:
        return run_gui()

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
