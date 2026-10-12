#!/usr/bin/env python3
"""Rebuild the pinned public-domain land outline; strictly offline, never a downloader."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import stat
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'src/media/maps'
ARCHIVE_SHA = '1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de'
VERSION = '4.1.0'
ARCHIVE = 'ne_110m_land_v4_1_0.zip'
DERIVED = 'ne_110m_land_v4_1_0.json'
CRS = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.017453292519943295]]'
NAMES = {'ne_110m_land.' + suffix for suffix in ('README.html', 'VERSION.txt', 'cpg', 'dbf', 'prj', 'shp', 'shx')}


def require(condition, reason):
    if not condition:
        raise ValueError('Basemap refused: ' + reason)


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':'), sort_keys=True, allow_nan=False) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def members(raw):
    require(len(raw) <= 1024 * 1024, 'archive byte bound')
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        infos = archive.infolist()
        require(len(infos) <= 16 and {i.filename for i in infos} == NAMES and len(infos) == len(NAMES), 'member inventory')
        require(sum(i.file_size for i in infos) <= 4 * 1024 * 1024, 'expanded total')
        result = {}
        for item in infos:
            require(not item.flag_bits & 1 and stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG), 'member type')
            require(0 <= item.file_size <= 2 * 1024 * 1024, 'member bound')
            with archive.open(item) as stream:
                data = stream.read(2 * 1024 * 1024 + 1)
            require(len(data) == item.file_size, 'member actual bound')
            result[item.filename] = data
    require(result['ne_110m_land.VERSION.txt'].decode('ascii').strip() == VERSION, 'version')
    require(result['ne_110m_land.prj'].decode('ascii') == CRS, 'CRS')
    return result


def rings_from_shp(data):
    require(len(data) >= 100 and len(data) % 2 == 0, 'shape header')
    require(struct.unpack_from('>i', data)[0] == 9994 and data[4:24] == b'\0' * 20, 'shape signature')
    require(struct.unpack_from('>i', data, 24)[0] * 2 == len(data), 'shape length')
    require(struct.unpack_from('<2i', data, 28) == (1000, 5), 'shape type')
    bounds = struct.unpack_from('<8d', data, 36)
    require(all(math.isfinite(n) for n in bounds), 'shape finite bounds')
    result, offset, sequence, vertices = [], 100, 1, 0
    while offset < len(data):
        require(offset + 8 <= len(data), 'record header')
        number, words = struct.unpack_from('>2i', data, offset)
        require(number == sequence and words >= 24 and offset + 8 + words * 2 <= len(data), 'record length/order')
        record = data[offset + 8:offset + 8 + words * 2]
        require(struct.unpack_from('<i', record)[0] == 5, 'polygon required')
        box = struct.unpack_from('<4d', record, 4)
        require(all(math.isfinite(n) for n in box), 'record bounds')
        parts, count = struct.unpack_from('<2i', record, 36)
        require(0 < parts <= 512 and 4 <= count <= 20_000 and len(record) == 44 + 4 * parts + 16 * count, 'record dimensions')
        starts = list(struct.unpack_from('<' + str(parts) + 'i', record, 44))
        require(starts[0] == 0 and starts == sorted(set(starts)) and starts[-1] < count, 'part indices')
        coordinates = [list(struct.unpack_from('<2d', record, 44 + 4 * parts + 16 * i)) for i in range(count)]
        require(all(math.isfinite(x) and math.isfinite(y) and -180 - 1e-12 <= x <= 180 + 1e-12 and -90 - 1e-12 <= y <= 90 + 1e-12 for x, y in coordinates), 'coordinate bounds')
        for start, end in zip(starts, starts[1:] + [count]):
            ring = coordinates[start:end]
            require(len(ring) >= 4 and ring[0] == ring[-1], 'closed ring required')
            result.append(ring)
        vertices += count
        require(len(result) <= 512 and vertices <= 20_000, 'geometry bound')
        offset += 8 + words * 2
        sequence += 1
    require(result and offset == len(data), 'complete geometry')
    return result


def build(raw, *, converter_sha256):
    require(digest(raw) == ARCHIVE_SHA, 'original archive hash')
    inventory = members(raw)
    rings = rings_from_shp(inventory['ne_110m_land.shp'])
    data = encoded(dict(schema_version=1, product='Natural Earth 110m land', version=VERSION, crs='EPSG:4326', rings=rings))
    require(len(data) <= 512 * 1024, 'derived byte bound')
    manifest = dict(schema_version=1, product='Natural Earth 110m land', version=VERSION, crs='EPSG:4326',
        source_url='https://naciscdn.org/naturalearth/110m/physical/ne_110m_land.zip',
        product_page='https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/',
        terms_url='https://www.naturalearthdata.com/about/terms-of-use/', license='public_domain',
        source_page_version='4.0.0', archive_version=VERSION, original_sha256=digest(raw), derived_sha256=digest(data),
        converter_version='p31-land-outline-1', converter_sha256=converter_sha256,
        original_bytes=len(raw), derived_bytes=len(data), rings=len(rings), vertices=sum(map(len, rings)),
        members={name:dict(bytes=len(value), sha256=digest(value)) for name, value in sorted(inventory.items())})
    return data, encoded(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    raw = (FOLDER / ARCHIVE).read_bytes()
    data, manifest = build(raw, converter_sha256=digest(Path(__file__).read_bytes()))
    for name, value in ((DERIVED, data), ('manifest.json', manifest)):
        path = FOLDER / name
        if args.check:
            require(path.is_file() and path.read_bytes() == value, 'derived resources changed; review before rebuilding')
        else:
            path.write_bytes(value)


if __name__ == '__main__':
    main()
