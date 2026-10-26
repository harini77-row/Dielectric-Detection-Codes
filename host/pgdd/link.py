"""Host side of the SPI boundary. The Pi 5 is SPI controller; the Pico is the
peripheral. The host can request sessions and acknowledge frames. It has no
command that writes record content, tolerances, frequencies or angles.

Transport: anything with .xfer(bytes64) -> bytes64 (SpiTransport or SimPico).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .record import (CMD_ABORT, CMD_NOP, CMD_START, FrameError, Record, Status,
                     pack_cmd, parse_frame)


class SpiTransport:
    """Raspberry Pi 5: /dev/spidevB.C, mode 3. Optional DRDY on a GPIO line
    (libgpiod v2). Pico PL022 slave limit is clk_peri/12, so stay <= 8 MHz."""

    def __init__(self, bus: int = 0, dev: int = 0, hz: int = 4_000_000,
                 drdy_chip: str | None = None, drdy_line: int | None = None,
                 gap_s: float = 0.0004):
        import spidev  # type: ignore
        self.spi = spidev.SpiDev()
        self.spi.open(bus, dev)
        self.spi.mode = 0b11
        self.spi.max_speed_hz = hz
        self.spi.bits_per_word = 8
        self.gap_s = gap_s
        self._req = None
        if drdy_chip is not None and drdy_line is not None:
            import gpiod  # type: ignore
            from gpiod.line import Direction
            self._req = gpiod.request_lines(drdy_chip, consumer="pgdd-drdy",
                                            config={drdy_line: gpiod.LineSettings(direction=Direction.INPUT)})
            self._line = drdy_line

    @property
    def drdy(self) -> bool:
        if self._req is None:
            return True
        from gpiod.line import Value
        return self._req.get_value(self._line) == Value.ACTIVE

    def xfer(self, cmd: bytes) -> bytes:
        out = bytes(self.spi.xfer2(list(cmd)))
        time.sleep(self.gap_s)          # let the Pico re-arm after CS rises
        return out

    def close(self):
        self.spi.close()


@dataclass
class LinkStats:
    frames: int = 0
    records: int = 0
    status: int = 0
    crc_errors: int = 0
    duplicates: int = 0
    gaps: int = 0
    seq_gaps: int = 0       # attempts the Pico made but did not commit (rejects)


@dataclass
class HostLink:
    t: object
    on_record: Callable[[Record, bytes], None] | None = None
    poll_s: float = 0.0             # >0 on hardware: clock frames only on DRDY ...
    idle_poll_s: float = 0.5        # ... plus a status poll this often while idle
    stats: LinkStats = field(default_factory=LinkStats)
    boot_id: int | None = None
    expected: int = 0               # next commit_idx we need
    nack: bool = False
    last_seq: int | None = None
    host_seq: int = 0
    last_status: Status | None = None

    def _cmd(self, **kw) -> bytes:
        self.host_seq += 1
        return pack_cmd(host_seq=self.host_seq, ack=self.expected, nack=self.nack, **kw)

    def exchange(self, **kw) -> Record | Status | None:
        raw = self.t.xfer(self._cmd(**kw))
        self.stats.frames += 1
        self.nack = False
        try:
            fr = parse_frame(raw)
        except FrameError:
            self.stats.crc_errors += 1
            self.nack = True
            return None
        if isinstance(fr, Status):
            self.stats.status += 1
            self._boot(fr.boot_id)
            self.last_status = fr
            if fr.head > self.expected:   # something committed we have not got
                self.nack = True
            return fr
        self._boot(fr.boot_id)
        if fr.commit_idx < self.expected:
            self.stats.duplicates += 1
            return None
        if fr.commit_idx > self.expected:
            self.stats.gaps += 1
            self.nack = True
            return None
        if self.last_seq is not None and fr.seq > self.last_seq + 1:
            self.stats.seq_gaps += fr.seq - self.last_seq - 1
        self.last_seq = fr.seq
        self.expected += 1
        self.stats.records += 1
        if self.on_record:
            self.on_record(fr, raw)
        return fr

    def _boot(self, boot_id: int):
        if self.boot_id != boot_id:
            self.boot_id = boot_id
            self.expected = 0
            self.last_seq = None

    def run_session(self, container_id: int, session_id: int, mode: int, plan_id: int = 0,
                    n_angles: int = 8, timeout_s: float = 3600, max_frames: int = 10_000_000) -> list[Record]:
        got: list[Record] = []
        # sync first so ack counts refer to this boot
        for _ in range(3):
            self.exchange()
        self.exchange(cmd=CMD_START, mode=mode, plan_id=plan_id, n_angles=n_angles,
                      container_id=container_id, session_id=session_id)
        t0 = last = time.monotonic()
        for _ in range(max_frames):
            if self.poll_s and not self.nack and not getattr(self.t, "drdy", True):
                # Nothing committed is waiting. Stay off the bus so a logic-analyser
                # capture shows comparator rejects (DBG_REJECT pulses) with no frame.
                if time.monotonic() - last < self.idle_poll_s:
                    time.sleep(self.poll_s)
                    continue
            last = time.monotonic()
            fr = self.exchange()
            if isinstance(fr, Record) and fr.session_id == session_id:
                got.append(fr)
            elif isinstance(fr, Status):
                if fr.session_id == session_id and fr.state == 0 and fr.head == self.expected:
                    self.exchange()           # deliver the final ack
                    return got
            if time.monotonic() - t0 > timeout_s:
                self.exchange(cmd=CMD_ABORT)
                raise TimeoutError("session timed out")
        raise TimeoutError("frame budget exhausted")
