"""Wire formats shared with the Pico firmware (firmware/pico2/include/record.h,
src/host_link.h). Layout changes must be made on both sides."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, asdict

FRAME_LEN = 64
REC_MAGIC = 0x44444750      # "PGDD"
STAT_MAGIC = 0x54534750     # "PGST"
CMD_MAGIC = 0x444D4348      # "HCMD"
REC_COMMITTED = 0xFFFFFFFF

F_ENROL, F_VERIFY, F_LOCK_A, F_LOCK_B, F_TEMP_OK = 1, 2, 4, 8, 16

CMD_NOP, CMD_START, CMD_ABORT = 0, 1, 2
MODE_ENROL, MODE_VERIFY = 1, 2

_REC = struct.Struct("<IIHHIQIHBBIhhhhhHIBBHII")
_STAT = struct.Struct("<IIIIBBH40sI")
_CMD = struct.Struct("<IBBBBIHHIB39sI")
assert _REC.size == _STAT.size == _CMD.size == FRAME_LEN


def crc32(b: bytes) -> int:
    return zlib.crc32(b) & 0xFFFFFFFF


@dataclass(frozen=True)
class Record:
    commit: int
    magic: int
    version: int
    flags: int
    seq: int
    t_us: int
    container_id: int
    session_id: int
    angle_idx: int
    port: int
    freq_khz: int
    vmag_a: int
    vphs_a: int
    vmag_b: int
    vphs_b: int
    temp_c16: int
    n_avg: int
    boot_id: int
    plan_id: int
    n_angles: int
    reserved0: int
    commit_idx: int
    crc32: int

    @property
    def is_enrol(self) -> bool:
        return bool(self.flags & F_ENROL)

    @property
    def temp_c(self) -> float | None:
        return self.temp_c16 / 16.0 if self.flags & F_TEMP_OK else None

    def pack(self) -> bytes:
        return _REC.pack(*astuple_ordered(self))

    def as_dict(self) -> dict:
        return asdict(self)


def astuple_ordered(r: Record) -> tuple:
    return tuple(getattr(r, f) for f in Record.__dataclass_fields__)


def make_record(**kw) -> Record:
    """Build a sealed record (CRC filled). commit defaults to 0 = not committed."""
    fields = {f: 0 for f in Record.__dataclass_fields__}
    fields.update(kw)
    fields["magic"] = REC_MAGIC
    fields["version"] = 1
    tmp = Record(**{**fields, "crc32": 0})
    body = tmp.pack()[4:60]
    fields["crc32"] = crc32(body)
    return Record(**fields)


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Status:
    boot_id: int
    head: int
    state: int
    angle: int
    session_id: int


def parse_frame(b: bytes) -> Record | Status:
    """Classify and verify a Pico->host frame. Raises FrameError on anything
    that is not a CRC-valid committed record or status frame."""
    if len(b) != FRAME_LEN:
        raise FrameError("bad length")
    commit, magic = struct.unpack_from("<II", b, 0)
    stored = struct.unpack_from("<I", b, 60)[0]
    if crc32(b[4:60]) != stored:
        raise FrameError("crc mismatch")
    if magic == REC_MAGIC:
        if commit != REC_COMMITTED:
            raise FrameError("record without commit token")
        return Record(*_REC.unpack(b))
    if magic == STAT_MAGIC:
        _, _, boot_id, head, state, angle, sid, _, _ = _STAT.unpack(b)
        return Status(boot_id, head, state, angle, sid)
    raise FrameError("unknown magic")


def pack_status(boot_id: int, head: int, state: int = 0, angle: int = 0, session_id: int = 0) -> bytes:
    b = bytearray(_STAT.pack(0, STAT_MAGIC, boot_id, head, state, angle, session_id, b"\0" * 40, 0))
    struct.pack_into("<I", b, 60, crc32(bytes(b[4:60])))
    return bytes(b)


def pack_cmd(cmd: int = CMD_NOP, mode: int = 0, plan_id: int = 0, n_angles: int = 0,
             container_id: int = 0, session_id: int = 0, host_seq: int = 0,
             ack: int = 0, nack: bool = False) -> bytes:
    b = bytearray(_CMD.pack(CMD_MAGIC, cmd, mode, plan_id, n_angles, container_id,
                            session_id, host_seq & 0xFFFF, ack, 1 if nack else 0, b"\0" * 39, 0))
    struct.pack_into("<I", b, 60, crc32(bytes(b[:60])))
    return bytes(b)


def parse_cmd(b: bytes) -> dict | None:
    if len(b) != FRAME_LEN:
        return None
    t = _CMD.unpack(b)
    if t[0] != CMD_MAGIC or crc32(b[:60]) != t[-1]:
        return None
    keys = ["magic", "cmd", "mode", "plan_id", "n_angles", "container_id",
            "session_id", "host_seq", "ack", "nack"]
    return dict(zip(keys, t[:10]))
