import os
import struct
from typing import Optional, Tuple


class EBMLPatcher:
    """
    Pure Python WebM EBML Duration Patcher.
    Modifies the Segment -> Info -> Duration tag in WebM files in-place
    to spoof Telegram's 3.0s duration check.
    """

    # EBML Element IDs
    ID_EBML = 0x1A45DFA3
    ID_SEGMENT = 0x18538067
    ID_INFO = 0x1549A966
    ID_TIMESTAMPSCALE = 0x2AD7B1
    ID_DURATION = 0x4489

    @staticmethod
    def _read_vint(data: bytes, offset: int) -> Tuple[int, int, int]:
        """
        Reads a variable-length integer (VINT) from data at offset.
        Returns (value, length, raw_id_or_size).
        """
        if offset >= len(data):
            raise ValueError("Offset out of bounds while reading VINT")

        first_byte = data[offset]
        if first_byte == 0:
            raise ValueError("Invalid VINT with first byte 0")

        # Find length by leading zeros
        length = 1
        mask = 0x80
        while not (first_byte & mask):
            mask >>= 1
            length += 1
            if length > 8:
                raise ValueError("VINT exceeds 8 bytes")

        if offset + length > len(data):
            raise ValueError("Unexpected end of data while reading VINT")

        raw_bytes = data[offset : offset + length]
        raw_int = int.from_bytes(raw_bytes, byteorder="big")

        # Value with marker bit cleared
        value = raw_int & ((1 << (7 * length)) - 1)
        return value, length, raw_int

    @classmethod
    def get_duration(cls, file_path: str) -> Optional[float]:
        """
        Reads the Duration element (in seconds) from the WebM header.
        Returns None if not found.
        """
        with open(file_path, "rb") as f:
            # We usually only need the first 64KB to find Segment -> Info
            header = f.read(65536)

        info_data, timecode_scale, duration_info = cls._find_duration_element(header)
        if duration_info is None:
            return None

        dur_offset, dur_size, dur_val = duration_info
        return dur_val

    @classmethod
    def _find_duration_element(
        cls, data: bytes
    ) -> Tuple[Optional[int], int, Optional[Tuple[int, int, float]]]:
        """
        Scans data to locate Info and Duration.
        Returns:
            (info_offset, timecode_scale, (dur_offset, dur_size, duration_in_seconds) or None)
        """
        offset = 0
        total_len = len(data)

        # 1. Look for Segment (0x18538067)
        segment_offset = None
        while offset + 4 <= total_len:
            elem_id = int.from_bytes(data[offset : offset + 4], "big")
            if elem_id == cls.ID_SEGMENT:
                segment_offset = offset
                offset += 4
                # Skip segment size vint
                _, size_len, _ = cls._read_vint(data, offset)
                offset += size_len
                break
            offset += 1

        if segment_offset is None:
            return None, 1_000_000, None

        # 2. Look for Info (0x1549A966) inside Segment
        info_offset = None
        info_end = None
        while offset + 4 <= total_len:
            elem_id = int.from_bytes(data[offset : offset + 4], "big")
            if elem_id == cls.ID_INFO:
                info_offset = offset
                offset += 4
                info_size, size_len, _ = cls._read_vint(data, offset)
                offset += size_len
                info_end = offset + info_size
                break
            else:
                # Read ID and skip element
                try:
                    val, id_len, raw_id = cls._read_vint(data, offset)
                    offset += id_len
                    size_val, size_len, _ = cls._read_vint(data, offset)
                    offset += size_len + size_val
                except Exception:
                    offset += 1

        if info_offset is None or info_end is None:
            return None, 1_000_000, None

        # 3. Inside Info, look for TimestampScale (0x2AD7B1) and Duration (0x4489)
        timecode_scale = 1_000_000  # default 1ms = 1,000,000 ns
        duration_info = None

        curr = offset
        limit = min(info_end, total_len)

        while curr < limit:
            try:
                _, id_len, raw_id = cls._read_vint(data, curr)
            except Exception:
                break
            curr += id_len
            if curr >= limit:
                break

            try:
                elem_size, size_len, _ = cls._read_vint(data, curr)
            except Exception:
                break
            curr += size_len

            elem_data = data[curr : curr + elem_size]

            if raw_id == cls.ID_TIMESTAMPSCALE:
                timecode_scale = int.from_bytes(elem_data, "big")
            elif raw_id == cls.ID_DURATION:
                dur_offset = curr
                dur_size = elem_size
                if dur_size == 4:
                    raw_float = struct.unpack(">f", elem_data)[0]
                elif dur_size == 8:
                    raw_float = struct.unpack(">d", elem_data)[0]
                else:
                    raw_float = 0.0
                # Duration in seconds = (raw_float * timecode_scale) / 1,000,000,000
                duration_sec = (raw_float * timecode_scale) / 1_000_000_000.0
                duration_info = (dur_offset, dur_size, duration_sec)

            curr += elem_size

        return info_offset, timecode_scale, duration_info

    @classmethod
    def patch_duration(cls, file_path: str, target_seconds: float = 2.99) -> bool:
        """
        Modifies the WebM file's Duration in-place to target_seconds.
        Preserves original file size and avoids rebuilding or remuxing.
        Returns True if successful, False otherwise.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, "r+b") as f:
            header = f.read(65536)
            _, timecode_scale, duration_info = cls._find_duration_element(header)

            if duration_info is None:
                # Duration tag not found in existing header
                return False

            dur_offset, dur_size, _ = duration_info

            # Calculate raw float value for the target duration
            # raw_float = target_seconds * 1,000,000,000 / timecode_scale
            target_raw = (target_seconds * 1_000_000_000.0) / float(timecode_scale)

            if dur_size == 4:
                packed = struct.pack(">f", target_raw)
            elif dur_size == 8:
                packed = struct.pack(">d", target_raw)
            else:
                return False

            # In-place write
            f.seek(dur_offset)
            f.write(packed)
            f.flush()

        return True
