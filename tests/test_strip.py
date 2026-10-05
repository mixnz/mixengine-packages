import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import strip  # noqa: E402

BASE = 0x400000
DATA_AT = 0x100          # file offset of the one allocated section, and of the segment mapping it
DATA = b"\x11" * 0x2C    # ends four bytes short of the segment, which is the shape issue #10 found


def elf(filesz: int, tail: bytes = b"\0" * 4) -> bytes:
    """A 64-bit little-endian ELF with one `PT_LOAD` over one allocated section, and *tail* after
    it — the bytes the segment maps that no section owns."""
    names = b"\0.data\0.shstrtab\0"
    body = DATA + tail
    names_at = DATA_AT + len(body)
    shoff = (names_at + len(names) + 7) & ~7
    header = struct.pack("<4sBBBBB7xHHIQQQIHHHHHH", b"\x7fELF", 2, 1, 1, 0, 0, 2, 0x3E, 1,
                         BASE + DATA_AT, 0x40, shoff, 0, 0x40, 0x38, 1, 0x40, 3, 2)
    program = struct.pack("<IIQQQQQQ", strip.PT_LOAD, 0x6, DATA_AT, BASE + DATA_AT,
                          BASE + DATA_AT, filesz, filesz, 0x1000)
    sections = (bytes(0x40)
                + struct.pack("<IIQQQQIIQQ", 1, 1, strip.SHF_ALLOC | 0x1, BASE + DATA_AT, DATA_AT,
                              len(DATA), 0, 0, 8, 0)
                + struct.pack("<IIQQQQIIQQ", 7, 3, 0, 0, names_at, len(names), 0, 0, 1, 0))
    blob = bytearray(header + program)
    blob += bytes(DATA_AT - len(blob)) + body + names
    blob += bytes(shoff - len(blob)) + sections
    return bytes(blob)


class Mapped(unittest.TestCase):
    def mapped(self, blob: bytes) -> dict:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch, "a.out")
            path.write_bytes(blob)
            return strip.mapped(path)

    def test_zero_padding_past_the_last_section_is_not_part_of_the_image(self):
        # What `strip --strip-all` did to python-build-standalone 20261003's interpreter.
        self.assertEqual(self.mapped(elf(len(DATA) + 4)), self.mapped(elf(len(DATA), tail=b"")))

    def test_bytes_past_the_last_section_that_are_not_zero_still_count(self):
        written = elf(len(DATA) + 4, tail=b"\x01\0\0\0")
        self.assertNotEqual(self.mapped(written), self.mapped(elf(len(DATA), tail=b"")))

    def test_a_segment_shrinking_into_a_section_still_counts(self):
        self.assertNotEqual(self.mapped(elf(len(DATA) + 4)), self.mapped(elf(len(DATA) - 4)))


if __name__ == "__main__":
    unittest.main()
