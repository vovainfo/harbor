"""Оценка объёма набора картографических данных V2 для bbox.

Запуск из корня репозитория:
    python tools/estimate_map_cache.py 131.55 42.80 132.35 43.25
    python tools/estimate_map_cache.py 131.55 42.80 132.35 43.25 --zooms 8-14 --sample 250

Считает векторные тайлы OpenFreeMap (выборкой, если тайлов на уровне больше --sample), шрифты
стилей Positron и Liberty, спрайт 1x/2x и ответ Overpass по морским объектам. Запросы идут напрямую,
без прокси из окружения, и с Accept-Encoding: identity — так же, как будет качать загрузчик 1С.
"""

import argparse
import concurrent.futures
import json
import math
import random
import sys
import urllib.parse
import urllib.request

OPENFREEMAP = "https://tiles.openfreemap.org"
STYLES = ("positron", "liberty")
GLYPH_RANGES = ("0-255", "256-511", "1024-1279", "8192-8447", "8448-8703", "9472-9727")
OVERPASS = ("https://z.overpass-api.de/api/interpreter", "https://overpass-api.de/api/interpreter")
HEADERS = {"User-Agent": "harbor-map-cache-estimate/1.0", "Accept-Encoding": "identity"}

# Прокси из окружения сессии не нужен для внешних запросов; сетевые проверки идут напрямую.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(url, data=None, timeout=30):
    with OPENER.open(urllib.request.Request(url, data=data, headers=HEADERS), timeout=timeout) as response:
        return response.read()


def size_or_none(url):
    try:
        return len(fetch(url))
    except Exception:
        return None


def tiles_in_bbox(bbox, zoom):
    lon_min, lat_min, lon_max, lat_max = bbox
    n = 2 ** zoom

    def tile_x(lon):
        return int((lon + 180) / 360 * n)

    def tile_y(lat):
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    return [(zoom, x, y)
            for x in range(tile_x(lon_min), tile_x(lon_max) + 1)
            for y in range(tile_y(lat_max), tile_y(lat_min) + 1)]


def measure_tiles(template, bbox, zooms, sample_limit):
    total_count = 0
    total_bytes = 0.0
    for zoom in zooms:
        tiles = tiles_in_bbox(bbox, zoom)
        sample = tiles if len(tiles) <= sample_limit else random.Random(zoom).sample(tiles, sample_limit)
        with concurrent.futures.ThreadPoolExecutor(6) as pool:
            sizes = [s for s in pool.map(lambda t: size_or_none(template.format(z=t[0], x=t[1], y=t[2])), sample) if s]
        average = sum(sizes) / len(sizes) if sizes else 0
        estimate = average * len(tiles)
        total_count += len(tiles)
        total_bytes += estimate
        note = "" if len(sample) == len(tiles) else f" (выборка {len(sample)})"
        print(f"  z{zoom:<2} тайлов {len(tiles):>6}{note:<16} средний {average / 1024:6.1f} КБ  итого {estimate / 1048576:7.2f} МБ")
    return total_count, total_bytes


def style_fonts_and_sprite():
    fonts = set()
    sprite = None
    for name in STYLES:
        style = json.loads(fetch(f"{OPENFREEMAP}/styles/{name}"))
        sprite = style.get("sprite") if isinstance(style.get("sprite"), str) else sprite
        for layer in style.get("layers", []):
            font = layer.get("layout", {}).get("text-font")
            if isinstance(font, list) and all(isinstance(f, str) for f in font):
                fonts.add(",".join(font))
    return sorted(fonts), sprite


def overpass_size(bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    query = f'[out:json][timeout:120];(nwr["seamark:type"]({lat_min},{lon_min},{lat_max},{lon_max}););out geom;'
    for endpoint in OVERPASS:
        try:
            body = fetch(endpoint, urllib.parse.urlencode({"data": query}).encode(), timeout=150)
            return endpoint, len(body), len(json.loads(body).get("elements", []))
        except Exception as error:
            print(f"  Overpass {endpoint}: {type(error).__name__}: {error}")
    return None, 0, 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bbox", nargs=4, type=float, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    parser.add_argument("--zooms", default="8-14", help="диапазон масштабов, например 8-14")
    parser.add_argument("--sample", type=int, default=250, help="тайлов на уровень для выборки")
    args = parser.parse_args()
    first, last = (int(v) for v in args.zooms.split("-"))
    bbox = tuple(args.bbox)

    tilejson = json.loads(fetch(f"{OPENFREEMAP}/planet"))
    print(f"Векторные тайлы, сборка {tilejson['tiles'][0]}")
    tile_count, tile_bytes = measure_tiles(tilejson["tiles"][0], bbox, range(first, last + 1), args.sample)

    fonts, sprite = style_fonts_and_sprite()
    glyph_bytes = sum(size_or_none(f"{OPENFREEMAP}/fonts/{urllib.parse.quote(f)}/{r}.pbf") or 0
                      for f in fonts for r in GLYPH_RANGES)
    sprite_bytes = sum(size_or_none(sprite + suffix) or 0 for suffix in (".json", ".png", "@2x.json", "@2x.png"))
    style_bytes = sum(size_or_none(f"{OPENFREEMAP}/styles/{name}") or 0 for name in STYLES) + len(json.dumps(tilejson))
    endpoint, seamark_bytes, seamark_count = overpass_size(bbox)

    total = tile_bytes + glyph_bytes + sprite_bytes + style_bytes + seamark_bytes
    print(f"\nТайлы: {tile_count}, {tile_bytes / 1048576:.1f} МБ")
    print(f"Шрифты: {len(fonts)} стеков × {len(GLYPH_RANGES)} диапазонов, {glyph_bytes / 1048576:.2f} МБ ({', '.join(fonts)})")
    print(f"Спрайт 1x/2x: {sprite_bytes / 1024:.0f} КБ ({sprite})")
    print(f"Стили и TileJSON: {style_bytes / 1024:.0f} КБ")
    print(f"Морская обстановка: {seamark_count} объектов, {seamark_bytes / 1024:.0f} КБ ({endpoint or 'Overpass недоступен'})")
    print(f"ИТОГО ≈ {total / 1048576:.1f} МБ, в base64 ≈ {total * 4 / 3 / 1048576:.1f} МБ")


if __name__ == "__main__":
    main()
