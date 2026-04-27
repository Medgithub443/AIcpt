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
import table_builder
import xml_builder


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE
WHITE_XML = HERE / "white.xml"


# ---------------------------- CLI -----------------------------------------


def cli_prompt(args: argparse.Namespace) -> int:
    auto_topo = not args.no_topology
    session, prompt_path = prompt_builder.run(
        args.user_file, ASSETS_DIR, HERE / "output",
        auto_topology=auto_topo,
        topology_log=lambda m: print(m),
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
    p1.add_argument("--no-topology", action="store_true",
                    help="Не запускать topology_recogniser (по умолчанию запускается для PDF/DOCX)")

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
            self.setWindowTitle("AIcpt 0.4.2-alfa — описание сети → Cisco Packet Tracer")
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
            tabs.addTab(self._tab_table(), "3. Таблица IP-плана")
            self._tabs = tabs

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
            self.user_file_edit.textChanged.connect(self._update_topology_checkbox)
            btn_browse = QtWidgets.QPushButton("Обзор…")
            btn_browse.clicked.connect(self._pick_user_file)
            row.addWidget(self.user_file_edit, 1)
            row.addWidget(btn_browse)
            lay.addLayout(row)

            self.topology_cb = QtWidgets.QCheckBox(
                "Добавить авто-распознанную топологию по скриншоту схемы [BETA]"
            )
            self.topology_cb.setChecked(False)   # по умолчанию снята
            self.topology_cb.setToolTip(
                "Если поставить галочку и нажать «Собрать prompt_for_ai.txt», "
                "откроется диалог загрузки скриншота схемы (.png / .jpg / .jpeg).\n"
                "topology_recogniser попробует распознать устройства и связи;\n"
                "результат добавится в prompt_for_ai.txt.\n\n"
                "BETA: распознавание не идеально, всегда проверяй результат.\n"
                "PDF и DOCX в этой версии не поддерживаются."
            )
            lay.addWidget(self.topology_cb)

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

        # ---------- TAB 3: TABLE ----------
        def _tab_table(self) -> QtWidgets.QWidget:
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)

            hint = QtWidgets.QLabel(
                "Заполни IP-план. Если столбец «Тип устройства» пуст — "
                "программа сама определит тип по имени (Server… → server, "
                "Router…/R1 → router, SW… → switch, Hub… → hub, Comp…/PC… → pc)."
            )
            hint.setWordWrap(True)
            lay.addWidget(hint)

            self.table = QtWidgets.QTableWidget(8, 7)
            self.table.setHorizontalHeaderLabels([
                "Сеть (IP/CIDR)", "Устройство", "Интерфейс",
                "IP-адрес", "Маска", "Шлюз", "Тип (опц.)",
            ])
            self.table.horizontalHeader().setSectionResizeMode(
                QtWidgets.QHeaderView.Stretch
            )
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(
                QtWidgets.QAbstractItemView.AllEditTriggers
            )
            lay.addWidget(self.table, 1)

            row = QtWidgets.QHBoxLayout()
            btn_add = QtWidgets.QPushButton("+ строка")
            btn_add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
            btn_del = QtWidgets.QPushButton("− строка")
            btn_del.clicked.connect(self._table_del_row)
            btn_clear = QtWidgets.QPushButton("Очистить")
            btn_clear.clicked.connect(self._table_clear)
            btn_load = QtWidgets.QPushButton("Загрузить TSV/CSV…")
            btn_load.clicked.connect(self._table_load)
            btn_save = QtWidgets.QPushButton("Сохранить TSV…")
            btn_save.clicked.connect(self._table_save)
            row.addWidget(btn_add)
            row.addWidget(btn_del)
            row.addWidget(btn_clear)
            row.addStretch(1)
            row.addWidget(btn_load)
            row.addWidget(btn_save)
            lay.addLayout(row)

            btn_gen = QtWidgets.QPushButton(
                "Сгенерировать simplified XML и перейти к сборке .pkt"
            )
            btn_gen.clicked.connect(self._table_to_simplified)
            lay.addWidget(btn_gen)

            return w

        def _table_del_row(self) -> None:
            r = self.table.currentRow()
            if r >= 0:
                self.table.removeRow(r)

        def _table_clear(self) -> None:
            self.table.clearContents()
            self.table.setRowCount(8)

        def _table_load(self) -> None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Загрузить таблицу", "",
                "TSV/CSV (*.tsv *.csv *.txt);;Все файлы (*)"
            )
            if not path:
                return
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                self._show_error("Ошибка чтения", e)
                return
            rows = table_builder.parse_text_table(text)
            self.table.setRowCount(max(len(rows) + 2, 4))
            for ri, r in enumerate(rows):
                for ci, val in enumerate([
                    r.network, r.device, r.iface, r.ip, r.mask, r.gateway, r.type
                ]):
                    self.table.setItem(ri, ci, QtWidgets.QTableWidgetItem(val))
            self.status.showMessage(f"Загружено {len(rows)} строк из {path}", 4000)

        def _table_save(self) -> None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Сохранить таблицу", "table.tsv",
                "TSV (*.tsv);;CSV (*.csv);;Все файлы (*)"
            )
            if not path:
                return
            sep = "," if path.lower().endswith(".csv") else "\t"
            lines = [sep.join([
                "Сеть", "Устройство", "Интерфейс", "IP", "Маска", "Шлюз", "Тип",
            ])]
            for r in range(self.table.rowCount()):
                cells = []
                for c in range(7):
                    item = self.table.item(r, c)
                    cells.append(item.text() if item else "")
                if any(cells):
                    lines.append(sep.join(cells))
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            self.status.showMessage(f"Сохранено: {path}", 4000)

        def _table_to_simplified(self) -> None:
            rows: list[table_builder.Row] = []
            for r in range(self.table.rowCount()):
                cells = [
                    (self.table.item(r, c).text() if self.table.item(r, c) else "")
                    for c in range(7)
                ]
                if not any(cells):
                    continue
                rows.append(table_builder.Row(*cells))
            if not rows:
                QtWidgets.QMessageBox.warning(
                    self, "AIcpt", "Таблица пустая. Заполни хотя бы одну строку."
                )
                return
            try:
                xml = table_builder.build_simplified_xml(rows)
            except Exception as e:
                self._show_error("Не удалось собрать simplified XML", e)
                return

            self.simpl_edit.setPlainText(xml)
            self._tabs.setCurrentIndex(1)  # переключиться на «Сборка .pkt»
            self.status.showMessage(
                f"Собрано {len(set(r.device for r in rows if r.device))} устройств. "
                f"Нажми «Собрать полный XML и .pkt»."
            )

        # ---- handlers ----
        def _pick_user_file(self) -> None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Выбери файл с описанием сети",
                "",
                "Документы (*.txt *.md *.pdf *.docx);;Все файлы (*)",
            )
            if path:
                # Path.resolve() нормализует путь (в т.ч. с пробелами)
                self.user_file_edit.setText(str(Path(path).resolve()))

        def _update_topology_checkbox(self) -> None:
            # Галочка всегда активна (не зависит от типа входного файла)
            self.topology_cb.setEnabled(True)

        # ---- topology image dialog ----
        def _ask_topology_image(self) -> Path | None:
            """Открывает диалоговое окно для загрузки скриншота топологии.

            Поддерживает:
              • drag-and-drop файла на область предпросмотра
              • Ctrl+V (вставка из буфера обмена)
              • кнопку «Выбрать файл…» (проводник, PNG / JPEG)

            Возвращает Path к временному файлу изображения или None.
            """
            from PyQt5 import QtCore, QtGui, QtWidgets
            import tempfile, io

            class _DropArea(QtWidgets.QLabel):
                image_ready = QtCore.pyqtSignal(Path)

                def __init__(self) -> None:
                    super().__init__()
                    self.setAcceptDrops(True)
                    self.setAlignment(QtCore.Qt.AlignCenter)
                    self.setMinimumHeight(200)
                    self.setSizePolicy(
                        QtWidgets.QSizePolicy.Expanding,
                        QtWidgets.QSizePolicy.Expanding,
                    )
                    self._reset_text()
                    self.setStyleSheet(
                        "border: 2px dashed #888; border-radius: 8px; "
                        "background: #f9f9f9; color: #555;"
                    )

                def _reset_text(self) -> None:
                    self.setText(
                        "Перетащи сюда PNG или JPEG\n"
                        "— или нажми Ctrl+V для вставки из буфера —"
                    )

                def dragEnterEvent(self, e: QtGui.QDragEnterEvent) -> None:
                    if e.mimeData().hasUrls():
                        exts = {".png", ".jpg", ".jpeg"}
                        if any(
                            Path(u.toLocalFile()).suffix.lower() in exts
                            for u in e.mimeData().urls()
                        ):
                            e.acceptProposedAction()
                            return
                    e.ignore()

                def dropEvent(self, e: QtGui.QDropEvent) -> None:
                    for url in e.mimeData().urls():
                        p = Path(url.toLocalFile())
                        if p.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                            self._show_preview(p)
                            self.image_ready.emit(p)
                            return

                def _show_preview(self, path: Path) -> None:
                    pix = QtGui.QPixmap(str(path))
                    if not pix.isNull():
                        self.setPixmap(
                            pix.scaled(
                                self.width() - 20, self.height() - 20,
                                QtCore.Qt.KeepAspectRatio,
                                QtCore.Qt.SmoothTransformation,
                            )
                        )
                    else:
                        self.setText(f"✔ {path.name}")

            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Загрузка скриншота топологии [BETA]")
            dlg.resize(560, 420)
            dlg.setWindowFlags(
                dlg.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
            )
            v = QtWidgets.QVBoxLayout(dlg)

            hint = QtWidgets.QLabel(
                "<b>Прикрепи скриншот схемы Cisco Packet Tracer</b><br>"
                "Поддерживаются форматы: <b>PNG, JPEG</b>"
            )
            hint.setWordWrap(True)
            v.addWidget(hint)

            drop_area = _DropArea()
            v.addWidget(drop_area, 1)

            selected_path: list[Path] = []   # изменяемый контейнер

            def _on_image(p: Path) -> None:
                selected_path.clear()
                selected_path.append(p)

            drop_area.image_ready.connect(_on_image)

            def _pick_file() -> None:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    dlg,
                    "Выбери скриншот схемы",
                    "",
                    "Изображения (*.png *.jpg *.jpeg);;Все файлы (*)",
                )
                if path:
                    p = Path(path)
                    drop_area._show_preview(p)
                    _on_image(p)

            def _paste_clipboard() -> None:
                cb = QtWidgets.QApplication.clipboard()
                img = cb.image()
                if img.isNull():
                    QtWidgets.QMessageBox.warning(
                        dlg, "AIcpt",
                        "Буфер обмена не содержит изображения.\n"
                        "Скопируй скриншот, затем нажми Ctrl+V снова."
                    )
                    return
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="aicpt_topo_", delete=False
                )
                tmp.close()
                p = Path(tmp.name)
                img.save(str(p), "PNG")
                drop_area._show_preview(p)
                _on_image(p)

            # Ctrl+V shortcut
            sc = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+V"), dlg)
            sc.activated.connect(_paste_clipboard)

            row = QtWidgets.QHBoxLayout()
            btn_file = QtWidgets.QPushButton("Выбрать файл…")
            btn_file.clicked.connect(_pick_file)
            btn_paste = QtWidgets.QPushButton("Вставить из буфера (Ctrl+V)")
            btn_paste.clicked.connect(_paste_clipboard)
            row.addWidget(btn_file)
            row.addWidget(btn_paste)
            row.addStretch(1)
            v.addLayout(row)

            bbox = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            )
            bbox.accepted.connect(dlg.accept)
            bbox.rejected.connect(dlg.reject)
            v.addWidget(bbox)

            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return None
            return selected_path[0] if selected_path else None

        def _do_build_prompt(self) -> None:
            path = Path(self.user_file_edit.text().strip()).resolve()
            if not self.user_file_edit.text().strip():
                QtWidgets.QMessageBox.warning(
                    self, "AIcpt", "Сначала выбери файл с описанием сети."
                )
                return

            # Если галочка стоит — запросить скриншот топологии
            topo_image_path: Path | None = None
            if self.topology_cb.isChecked():
                topo_image_path = self._ask_topology_image()
                # Пользователь закрыл диалог — не прерываем основной поток
                # (продолжаем без топологии, но предупреждаем)
                if topo_image_path is None:
                    reply = QtWidgets.QMessageBox.question(
                        self, "AIcpt",
                        "Скриншот не выбран. Продолжить без авто-топологии?",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    )
                    if reply != QtWidgets.QMessageBox.Yes:
                        return

            log_lines: list[str] = []

            def _log(msg: str) -> None:
                log_lines.append(msg)
                self.status.showMessage(msg, 6000)
                QtWidgets.QApplication.processEvents()

            self.status.showMessage("Собираю промпт…")
            QtWidgets.QApplication.processEvents()

            # --- распознавание топологии (если задан скриншот) ---
            topology_desc: str | None = None
            if topo_image_path is not None:
                try:
                    import topology_recogniser_helper as trh
                    topology_desc = trh.recognise_from_image(topo_image_path)
                    if topology_desc:
                        n_devs = topology_desc.count("name=")
                        _log(
                            f"[+] topology_recogniser: распознано "
                            f"~{n_devs} устройств, добавлено в промпт."
                        )
                    else:
                        _log("[!] topology_recogniser: схему сети не нашёл.")
                except Exception as e:
                    _log(f"[-] topology_recogniser: {e}")

            try:
                # Используем Path.resolve() чтобы пути с пробелами передавались корректно
                user_text = prompt_builder.read_user_input(path)
                from prompt_builder import build_prompt, make_output_dir
                session = make_output_dir(HERE / "output")
                prompt_text = build_prompt(
                    user_text, ASSETS_DIR, topology_description=topology_desc
                )
                prompt_path = session / "prompt_for_ai.txt"
                prompt_path.write_text(prompt_text, encoding="utf-8")
                (session / "user_input.txt").write_text(user_text, encoding="utf-8")
                if topology_desc:
                    (session / "topology_recognised.txt").write_text(
                        topology_desc, encoding="utf-8"
                    )
            except Exception as e:
                self._show_error("Не удалось собрать промпт", e)
                return

            self.session_dir = session
            self.prompt_path = prompt_path
            text = prompt_path.read_text(encoding="utf-8")
            self.prompt_view.setPlainText(text)
            tail = log_lines[-1] if log_lines else f"Промпт сохранён: {prompt_path}"
            self.status.showMessage(tail)

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

            # Используем Path.resolve() + передаём как один аргумент — пробелы в пути не проблема
            p = Path(self.session_dir).resolve()
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(p)])
            elif platform.system() == "Windows":
                subprocess.Popen(["explorer", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])

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
