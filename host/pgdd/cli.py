"""pgdd command line (runs on the Raspberry Pi 5, or anywhere for --sim/ablation).

  pgdd enrol   --container 101 --angles 8 [--plan 0] [--spi 0.0] [--drdy gpiochip0:25]
  pgdd verify  --container 101 --angles 8
  pgdd sim-demo [--root runs/demo]
  pgdd ablation [--seeds 5] [--rates 0,0.1,0.2,0.3] [--out runs/ablation]
  pgdd ledger-verify runs/demo/ledger.jsonl
  pgdd features --root runs/demo
"""
from __future__ import annotations

import argparse
import json
import sys


def _transport(a):
    from .link import SpiTransport
    bus, dev = (int(x) for x in a.spi.split("."))
    chip = line = None
    if a.drdy:
        chip, line = a.drdy.split(":")
        chip = chip if chip.startswith("/dev/") else f"/dev/{chip}"
        line = int(line)
    return SpiTransport(bus, dev, a.hz, chip, line)


def cmd_enrol(a):
    from .pipeline import Host
    h = Host(a.root, _transport(a))
    print(f"Enrolling container {a.container}: rotate the cradle through {a.angles} detents "
          f"and press the step button at each.")
    cert, path = h.enrol(a.container, a.angles, a.plan)
    for s in cert.steps:
        print("  ", json.dumps(s)[:200])
    print("REFERENCE WRITTEN:" if cert.ok else "REFUSED:", path or cert.reason)
    return 0 if cert.ok else 2


def cmd_verify(a):
    from .pipeline import Host
    h = Host(a.root, _transport(a))
    d = h.verify(a.container, a.angles, a.plan)
    print(json.dumps(d.as_dict(), indent=1, default=str))
    return 0


def cmd_sim_demo(a):
    import numpy as np
    from .forward import LIQUIDS, make_containers
    from .pipeline import Host
    from .sim import Faults, SimPico

    pico = SimPico(a.seed)
    h = Host(a.root, pico)
    cons = make_containers(4, np.random.default_rng(a.seed))
    print("== enrolment (clean) ==")
    for c in cons:
        pico.state.mounted, pico.state.faults = c, Faults()
        cert, _ = h.enrol(c.cid, 8, 0)
        print(f"  {c.cid} ({c.liquid.name}): {'certified' if cert.ok else 'REFUSED ' + cert.reason}")

    print("== enrolment with a mis-seated detent (angle 3) ==")
    pico.state.mounted, pico.state.faults = cons[0], Faults(slip_angles=(3,), slip_k=0.08)
    cert, _ = h.enrol(cons[0].cid, 8, 0)
    print("  ", cert.reason, [s for s in cert.steps if s["step"] == "angle_corroboration"][0]["rejected"])

    print("== verification ==")
    cases = [("unchanged", cons[1], Faults()),
             ("substituted (ethanol)", cons[1].substituted(LIQUIDS["ethanol"]), Faults()),
             ("unchanged + 2.4 GHz interferer", cons[2], Faults(interf_band_khz=(2400000, 2480000), interf_rate=0.5)),
             ("unchanged + transient glitches", cons[3], Faults(glitch_rate=0.3)),
             ("unchanged + link bit errors", cons[3], Faults(link_error_rate=0.05))]
    for name, actual, f in cases:
        claimed = actual.cid            # vial label is unchanged; contents may not be
        pico.state.mounted, pico.state.faults = actual, f
        d = h.verify(claimed, 8, 0)
        print(f"  {name:34s} -> {d.verdict:12s} matched={d.matched} records={d.n_records}")
    print(f"gate: {pico.stats}   link: {h.link.stats}")
    from .ledger import verify
    ok, n, _, err = verify(h.ledger.path)
    print(f"ledger {h.ledger.path}: {'OK' if ok else 'BROKEN ' + err} ({n} entries)")
    return 0


def cmd_ablation(a):
    from .ablation import DISCLAIMER, FAULT_MODES, run
    rates = tuple(float(x) for x in a.rates.split(","))
    modes = tuple(a.modes.split(",")) if a.modes else FAULT_MODES
    _, summ = run(a.out, a.seeds, rates, modes, plot=not a.no_plot)
    print(DISCLAIMER)
    print(f"{'mode':18s}{'rate':>5s}  {'method':30s}{'correct':>16s}{'false acc':>16s}{'false alarm':>16s}{'inconcl':>16s}")
    for s in summ:
        f = lambda t: f"{t[0]:.2f}±{t[1]:.2f}"
        print(f"{s['mode']:18s}{s['rate']:5.2f}  {s['method']:30s}{f(s['correct']):>16s}"
              f"{f(s['false_accept']):>16s}{f(s['false_alarm']):>16s}{f(s['inconclusive']):>16s}")
    print(f"written to {a.out}/")
    return 0


def cmd_ledger_verify(a):
    from .ledger import verify
    ok, n, last, err = verify(a.path)
    print(f"{'OK' if ok else 'BROKEN'}: {n} entries, head {last[:16]}… {err}")
    return 0 if ok else 1


def cmd_features(a):
    from pathlib import Path
    from .ledger import Ledger
    from .reference import ReferenceStore
    from .store import Store
    refs = ReferenceStore(Path(a.root) / "refs", Ledger(Path(a.root) / "ledger.jsonl")).all_latest()
    print(Store(a.root).regenerate_features(refs))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="pgdd")
    sp = p.add_subparsers(dest="cmd", required=True)

    def hw(q):
        q.add_argument("--container", type=int, required=True)
        q.add_argument("--angles", type=int, default=8)
        q.add_argument("--plan", type=int, default=0)
        q.add_argument("--root", default="runs/bench")
        q.add_argument("--spi", default="0.0", help="bus.device of /dev/spidevB.D")
        q.add_argument("--hz", type=int, default=4_000_000)
        q.add_argument("--drdy", default=None, help="gpiochipN:line, e.g. gpiochip0:25")

    q = sp.add_parser("enrol"); hw(q); q.set_defaults(fn=cmd_enrol)
    q = sp.add_parser("verify"); hw(q); q.set_defaults(fn=cmd_verify)
    q = sp.add_parser("sim-demo"); q.add_argument("--root", default="runs/demo")
    q.add_argument("--seed", type=int, default=1); q.set_defaults(fn=cmd_sim_demo)
    q = sp.add_parser("ablation"); q.add_argument("--seeds", type=int, default=5)
    q.add_argument("--rates", default="0,0.1,0.2,0.3"); q.add_argument("--modes", default="")
    q.add_argument("--out", default="runs/ablation"); q.add_argument("--no-plot", action="store_true")
    q.set_defaults(fn=cmd_ablation)
    q = sp.add_parser("ledger-verify"); q.add_argument("path"); q.set_defaults(fn=cmd_ledger_verify)
    q = sp.add_parser("features"); q.add_argument("--root", default="runs/demo"); q.set_defaults(fn=cmd_features)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
