# fpga-embedded-studio

Unified toolchain front-end for Intel/Altera FPGA embedded development.

A minimal web-based GUI that ties together the tools needed to go from a Platform Designer project to a bootable embedded Linux system with a correct devicetree.

## What it does

```
sopcinfo / .qsys  ──► sopc2dts (qualified FPGA-fabric DTS) ──┐
                                                              ▼
                                                    dts-merge ► merged.dts
                                                              ▲
HPS / Kernel / Poky ARM DTS  ────────────────────────────────┘

(future) Quartus-generated DTS ──► third input to dts-merge
(future) cheby register maps ──► register headers + annotated DTS
(future) overlay export scoped to user-level vs admin/calibration-level registers
```

## Components

| Submodule | Role | Status |
|-----------|------|--------|
| [sopc2dts](https://github.com/LaurenceA4L/sopc2dts) | Parse `.sopcinfo` / `.qsys` → DTS/DTB/headers | Active |
| [dts-merge](https://github.com/LaurenceA4L/dts-merge) | Interactive merge of sopc2dts output onto an HPS/kernel DTS | Active |
| [cheby](https://gitlab.cern.ch/be-cem-edl/general/cheby) | Register map tooling | Planned |

## Target hardware

- Intel Agilex 7 (active)
- Intel Agilex 5 (planned)
- Intel Agilex 3 (maybe)
- Intel Cyclone V SoC / Arria 10 SoC

## Design philosophy

Each underlying tool is a standalone CLI. The studio is orchestration and a diff/merge UI on top. No GUI logic lives in the submodules. Functional over fancy — the GUI must not become more work to maintain than the tools it wraps.

## Structure

```
fpga-embedded-studio/
├── submodules/
│   ├── sopc2dts/      # sopcinfo → DTS generator
│   ├── dts-merge/     # DTS parser + interactive merge onto HPS/kernel DTS
│   └── cheby/         # register map tooling (planned)
├── web/               # FastAPI + HTMX front-end
└── pyproject.toml
```

## License

GPLv3 — see [COPYING](COPYING).
