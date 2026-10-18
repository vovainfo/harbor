"""Переносит MapLibre GL JS из vendor/ в текстовые макеты обработки карты.

Запуск из корня репозитория:
    python tools/vendor_to_templates.py 1.15.3 --target КартаПодходаСудовV2

Скрипт не скачивает библиотеку: файлы кладутся в vendor/maplibre-gl/<версия>/ вручную
(https://unpkg.com/maplibre-gl@<версия>/dist/). Перед записью проверяет, что текст можно
вставить в <script>/<style> страницы, собранной строкой: нет закрывающего тега и плейсхолдеров.
Обработки прошлых версий (суффикс V1) заморожены — их макеты скрипт трогать не должен.
"""

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Источник, макет, запрещённый закрывающий тег.
FILES = [
    ("maplibre-gl.js", "МаплибреJS", "</script"),
    ("maplibre-gl.css", "МаплибреCSS", "</style"),
]

PLACEHOLDER_MARK = "/*@@"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="версия MapLibre, каталог vendor/maplibre-gl/<версия>")
    parser.add_argument("--target", required=True, help="имя обработки, например КартаПодходаСудовV2")
    args = parser.parse_args()

    vendor = ROOT / "vendor" / "maplibre-gl" / args.version
    templates = ROOT / "src" / "DataProcessors" / args.target / "Templates"
    if not templates.parent.is_dir():
        print(f"Нет обработки {templates.parent}")
        return 1

    texts = {}
    for source_name, template_name, closing_tag in FILES:
        source = vendor / source_name
        if not source.is_file():
            print(f"Нет файла {source}")
            return 1
        text = source.read_text(encoding="utf-8")
        if closing_tag in text.lower():
            print(f"{source_name}: найден {closing_tag}, вставка в страницу сломает разметку")
            return 1
        if PLACEHOLDER_MARK in text:
            print(f"{source_name}: найдена разметка плейсхолдера {PLACEHOLDER_MARK}")
            return 1
        header = f"/* MapLibre GL JS {args.version}, vendor/maplibre-gl/{args.version}/{source_name} */\n"
        texts[template_name] = header + text

    # Пишем только после проверки обоих файлов, чтобы макеты не разошлись по версии.
    for template_name, text in texts.items():
        target = templates / template_name / "Template.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")
        print(f"{args.target}/{template_name}: {len(text)} символов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
