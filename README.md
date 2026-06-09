# fpga-embedded-studio

> Unified toolchain front-end for Intel/Altera FPGA embedded development.

A web-based GUI that ties together the tools needed to take a Platform Designer project through to a bootable embedded Linux system:

* sopc2dts — generates devicetree source from Platform Designer .sopcinfo / .qsys files (submodule)
* dtmerge (planned) — interactive 3-way DTS merge: sopc2dts output × Quartus-generated DTS × kernel/Poky ARM DTS → merged .dts
* cheby (planned) — register map tooling; cross-links component addresses to register definitions (submodule)

The GUI is intentionally minimal — functional over fancy. Each underlying tool remains a standalone CLI; the studio is orchestration and a diff/merge UI on top.
Targets: Agilex 7, Agilex 5 (in progress), Cyclone V SoC, Arria 10 SoC.