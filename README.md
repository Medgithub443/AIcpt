# AIcpt — описание сети → Cisco Packet Tracer .pkt

AIcpt берёт описание сети на естественном языке (или текст лабораторной
работы в txt/pdf/docx), превращает его в **prompt для нейросети**,
а упрощённый XML, который вернёт Claude/ChatGPT, превращает в **валидный
Cisco Packet Tracer 6.2 XML** и затем шифрует в формат **.pkt**.

## Как это работает

```
[описание сети]        ┌────────────────┐        ┌─────────────┐
  txt / pdf / docx ──► │ prompt_builder │ ──►    │ prompt_for_ │ ──► Claude / ChatGPT
                       └────────────────┘        │  ai.txt     │           │
                                                 └─────────────┘           ▼
                                                                     [упрощённый XML]
                                                                           │
                       ┌────────────────┐        ┌──────────────┐          │
     network.pkt ◄──── │ Twofish / EAX  │ ◄───── │ xml_builder  │  ◄───────┘
                       └────────────────┘        │ + white.xml  │
                                                 └──────────────┘
```

## Установка

Нужен Python 3.10+.

```bash
pip install PyQt5 pypdf python-docx
```

Всё остальное (zlib, xml.etree, struct) — стандартная библиотека.
Модули Twofish/EAX лежат рядом, отдельно ставить не нужно.

## Запуск

### GUI (PyQt5) — рекомендуется

```bash
python main.py
```

Открывается окно с двумя вкладками:

1. **«Промпт для нейросети»** — выбери txt/pdf/docx с описанием сети,
   нажми «Собрать prompt_for_ai.txt», скопируй получившийся текст и
   вставь в Claude или ChatGPT.

2. **«Сборка .pkt»** — вставь упрощённый XML от нейросети (или загрузи
   из файла), нажми «Собрать полный XML и .pkt». Готовый `network.pkt`
   появится в каталоге сессии `output/YYYY-MM-DD_HH-MM-SS/`.

### CLI

```bash
# Шаг 1: собрать prompt_for_ai.txt
python main.py prompt "моё_задание.pdf"
# → output/2026-04-18_14-33-09/prompt_for_ai.txt

# скопировал промпт в Claude, получил XML, сохранил в simplified.xml

# Шаг 2: собрать полный XML и упаковать в .pkt
python main.py build simplified.xml
# → output/…/realTopolog.xml и realTopolog.pkt
```

## Структура проекта

```
AIcpt/
├── main.py                  # CLI + PyQt5 GUI
├── prompt_builder.py        # step 1-3: собрать prompt_for_ai.txt
├── xml_builder.py           # step 4-7: simplified → полный XML → .pkt
├── repacket.py              # оригинальный конвертер XML → .pkt (как есть)
├── unpacket.py              # оригинальный конвертер .pkt → XML (как есть)
├── white.xml                # пустой шаблон Cisco PT 6.2
├── Decipher/                # крипто-модули (Twofish + EAX + CMAC)
│   ├── eax.py
│   ├── twofish.py
│   ├── cmac.py
│   ├── ctr.py
│   └── pt_crypto.py
├── pre_prompt.txt           # инструкция для нейросети (роль + правила)
├── specification_guide.txt  # спецификация упрощённого XML и полного PT-XML
├── devices_reference.txt    # справочник моделей и их интерфейсов
└── output/                  # рабочие сессии (создаются автоматически)
    └── 2026-04-18_14-33-09/
        ├── user_input.txt
        ├── prompt_for_ai.txt
        ├── simplified.xml
        ├── realTopolog.xml
        └── realTopolog.pkt
```

## Формат упрощённого XML

Нейросеть должна вернуть один блок `<network>` с двумя секциями:

```xml
<network>
  <devices>
    <device name="R1" type="router" model="1841" x="200" y="200">
      <interface name="FastEthernet0/0" ip="10.0.0.1" subnet="255.255.255.0"/>
      <config>
        <line>hostname R1</line>
        <line>interface FastEthernet0/0</line>
        <line> ip address 10.0.0.1 255.255.255.0</line>
        <line> no shutdown</line>
      </config>
    </device>
    <device name="PC1" type="pc" model="PC-PT" x="400" y="200">
      <interface name="FastEthernet0" ip="10.0.0.10" subnet="255.255.255.0"
                 gateway="10.0.0.1"/>
    </device>
  </devices>
  <links>
    <link from="R1" from_port="FastEthernet0/0"
          to="PC1" to_port="FastEthernet0" type="copper"/>
  </links>
</network>
```

Полный справочник разрешённых тегов — в `specification_guide.txt`,
список моделей — в `devices_reference.txt`. Оба файла автоматически
включаются в `prompt_for_ai.txt`, так что нейросеть их увидит.

## Частые проблемы

**«PyQt5 не установлен»**
```bash
pip install PyQt5
```

**«ModuleNotFoundError: No module named 'pypdf'»**
```bash
pip install pypdf
# или старая альтернатива:
pip install PyPDF2
```

**«ModuleNotFoundError: No module named 'docx'»**
```bash
pip install python-docx   # пакет называется python-docx, а import — docx
```

**«В ответе нейросети не найдено `<network>…</network>`»**
Нейросеть обернула XML в markdown-блок или добавила текст до/после.
Удали всё лишнее и оставь только `<network>…</network>`.

**Файл .pkt не открывается в Packet Tracer**
- Убедись, что версия Packet Tracer — **6.2**. Файлы несовместимы с 7.x/8.x.
- Открой `output/…/realTopolog.xml` вручную и проверь, что он валиден.
- Проверь, что все устройства в `<link>` существуют как `<device>` с тем
  же именем буква-в-букву.

## Лицензия

Скрипты шифрования (repacket/unpacket/Decipher/*) взяты из публичного
проекта, используются «как есть» для образовательных целей.
