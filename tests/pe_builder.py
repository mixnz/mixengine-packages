"""A minimal PE32+ DLL, built in memory, so the PE reader can be tested on any runner."""

import struct

SECTION_VA = 0x1000
SECTION_RAW = 0x200


def make_dll(exports: list[str] = (), imports: dict[str, list[str]] | None = None) -> bytes:
    imports = imports or {}
    body = bytearray()

    def place(blob: bytes) -> int:
        while len(body) % 8:
            body.append(0)
        at = SECTION_VA + len(body)
        body.extend(blob)
        return at

    export_rva = export_size = 0
    if exports:
        names = [place(name.encode() + b"\0") for name in exports]
        name_table = place(b"".join(struct.pack("<I", rva) for rva in names))
        ordinals = place(b"".join(struct.pack("<H", i) for i in range(len(exports))))
        functions = place(b"".join(struct.pack("<I", SECTION_VA) for _ in exports))
        dll_name = place(b"test.dll\0")
        directory = struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, dll_name, 1, len(exports),
                                len(exports), functions, name_table, ordinals)
        export_rva, export_size = place(directory), len(directory)

    descriptors = []
    for dll, symbols in imports.items():
        hints = [place(b"\0\0" + symbol.encode() + b"\0") for symbol in symbols]
        thunks = place(b"".join(struct.pack("<Q", rva) for rva in hints) + b"\0" * 8)
        descriptors.append((thunks, place(dll.encode() + b"\0")))
    import_rva = import_size = 0
    if descriptors:
        table = b"".join(struct.pack("<IIIII", thunks, 0, 0, name, thunks)
                         for thunks, name in descriptors) + b"\0" * 20
        import_rva, import_size = place(table), len(table)

    size = max(0x200, (len(body) + 0x1FF) & ~0x1FF)
    body.extend(b"\0" * (size - len(body)))

    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<II", optional, 112, export_rva, export_size)
    struct.pack_into("<II", optional, 120, import_rva, import_size)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, len(optional), 0x2022)
    section = struct.pack("<8sIIIIIIHHI", b".data", size, SECTION_VA, size, SECTION_RAW,
                          0, 0, 0, 0, 0xC0000040)
    dos = bytearray(64)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    headers = bytes(dos) + b"PE\0\0" + coff + bytes(optional) + section
    return headers + b"\0" * (SECTION_RAW - len(headers)) + bytes(body)
