#!/usr/bin/env python3
"""Read the import and export tables of a Windows DLL, so a borrowed extension can be checked
against the PHP it is going into *before* it is shipped.

PECL builds a Windows extension per PHP branch, against whatever patch of that branch is newest on
the day. When a patch adds a function to `php8.dll` and the extension's headers use it, the
extension imports a symbol every older patch of the same branch lacks — `php_mongodb` 2.5.3 imports
`php_win32_ioutil_path_kind_w`, which PHP 8.4 exports from 8.4.26 on — and Windows refuses to load
it with "the specified procedure could not be found". The branch and compiler tags in the file name
cannot say that; only the tables can.

Python 3 stdlib only, and runs on any OS: the tables are read, nothing is loaded.
"""

from __future__ import annotations

import struct
from pathlib import Path


def _layout(data: bytes) -> tuple[list[tuple[int, int, int]], int, bool]:
    """``(sections as (va, size, raw offset), data directory offset, is PE32+)``."""
    header = struct.unpack_from("<I", data, 0x3C)[0]
    if data[header:header + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    count = struct.unpack_from("<H", data, header + 6)[0]
    optional_size = struct.unpack_from("<H", data, header + 20)[0]
    optional = header + 24
    wide = struct.unpack_from("<H", data, optional)[0] == 0x20B
    sections = []
    for index in range(count):
        entry = optional + optional_size + index * 40
        virtual_size, va, raw_size, raw = struct.unpack_from("<IIII", data, entry + 8)
        sections.append((va, max(virtual_size, raw_size), raw))
    return sections, optional + (112 if wide else 96), wide


def _offset(sections: list[tuple[int, int, int]], rva: int) -> int:
    for va, size, raw in sections:
        if va <= rva < va + size:
            return rva - va + raw
    raise ValueError(f"RVA {rva:#x} is in no section")


def _string(data: bytes, at: int) -> str:
    return data[at:data.index(b"\0", at)].decode("ascii", "replace")


def exports(data: bytes) -> set[str]:
    """Every name the DLL exports. Ordinal-only exports have no name and are not listed."""
    sections, directories, _ = _layout(data)
    rva = struct.unpack_from("<I", data, directories)[0]
    if not rva:
        return set()
    table = _offset(sections, rva)
    count = struct.unpack_from("<I", data, table + 24)[0]
    names = _offset(sections, struct.unpack_from("<I", data, table + 32)[0])
    return {
        _string(data, _offset(sections, struct.unpack_from("<I", data, names + 4 * index)[0]))
        for index in range(count)
    }


def imports(data: bytes) -> dict[str, list[str]]:
    """``{dll (lowercased): [symbols imported by name]}``. Imports by ordinal are skipped."""
    sections, directories, wide = _layout(data)
    rva = struct.unpack_from("<I", data, directories + 8)[0]
    if not rva:
        return {}
    width, flag = (8, 1 << 63) if wide else (4, 1 << 31)
    found: dict[str, list[str]] = {}
    descriptor = _offset(sections, rva)
    while True:
        lookup, _, _, name, thunks = struct.unpack_from("<IIIII", data, descriptor)
        if not name:
            return found
        symbols = found.setdefault(_string(data, _offset(sections, name)).lower(), [])
        entry = _offset(sections, lookup or thunks)
        while value := int.from_bytes(data[entry:entry + width], "little"):
            if not value & flag:
                symbols.append(_string(data, _offset(sections, value & 0x7FFFFFFF) + 2))
            entry += width
        descriptor += 20


def unresolved(binary: bytes, tree: Path) -> dict[str, list[str]]:
    """What *binary* imports from a DLL at the root of *tree* that the DLL does not export.

    Only DLLs *tree* ships are judged. A system DLL (`kernel32.dll`) is the machine's business, and
    the CRT is checked elsewhere by `deplister`.
    """
    shipped = {path.name.lower(): path for path in tree.glob("*.dll")}
    missing: dict[str, list[str]] = {}
    for dll, symbols in imports(binary).items():
        if dll not in shipped:
            continue
        offered = exports(shipped[dll].read_bytes())
        absent = [symbol for symbol in symbols if symbol not in offered]
        if absent:
            missing[dll] = absent
    return missing
