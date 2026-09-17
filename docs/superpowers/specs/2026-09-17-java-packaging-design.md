# Java, and why the publisher is not the one everybody names

*Design for a proposed **P20**. It settles which JDK lines are offered, **whose** build each cell is,
what the rule takes out of a 373 MB tree, and what the artifact promises a daemon. `JAVA_HOME`, the
build tools a Java project reaches for, and how MixEngine renders any of it are that repository's
work.*

---

## Why this row exists at all

The index has no runtime for the JVM, so a Java, Kotlin or Scala project — or a tool written in one,
like a Gradle build or a local Elasticsearch — has nothing to resolve. Every JDK below is a borrow, so
the cost is an evaluation and a recipe that chooses once, not a build pipeline.

What the row does **not** have behind it is blueprint demand, and this document does not claim any.

## What is offered

Four LTS lines, every cell borrowed from **one publisher, Microsoft Build of OpenJDK**:

| Version | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **11** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **17** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **21** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **25** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Lines are keyed by major, the way Node.js's are: `21` is the line and `21.0.12.1` is a release of it.
Only LTS lines are offered. A feature release is supported for six months, and a row that grows by a
version nobody patches after March is not one worth the permanence promise.

## Why Microsoft and not Temurin

**Eclipse Temurin is the build everybody names, and it cannot fill the row.** Asked of
`api.adoptium.net/v3/assets/latest/<major>/hotspot` on 2026-09-17, cell by cell:

| Line | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| 8 | — | ✅ | ✅ | ✅ | ✅ | — |
| 11 | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 17 | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 21 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ from 21.0.5 |
| 25 | ✅ | ✅ | ✅ | ✅ | ✅ | — |

Temurin has a Windows ARM64 JDK on **one** line, from `21.0.5+11`, and none on 25 at any release
(`jdk-25+36` through `jdk-25.0.4.1+1` checked). Filling those cells from a second publisher would put
two vendors' builds under one version number — the MariaDB lesson, which is where *one version means
one thing* came from — and leaving them empty would make the newest LTS the least complete row.

**Microsoft publishes all six cells on all four lines**, from one build system, with the same
`release` file shape on every cell. Its builds are OpenJDK from `microsoft/openjdk-jdk<major>u`, pass
the same AQAvit suite Temurin does (Microsoft publishes the results), and are GPLv2 with the
Classpath Exception like every OpenJDK. The honest cost is that Microsoft does not build **8**, which
is why 8 is not in the table — see *What this does not do*.

## Where each cell comes from

The catalogue is `marketplace-api.adoptium.net/v1/assets/feature_releases/microsoft/<major>`: the
Adoptium Marketplace, which serves each vendor's own submitted data — Microsoft's lives in
`microsoft/openjdk-adoptium-marketplace-data`. One entry per release carries, per binary, the
archive's `link` on `aka.ms/download-jdk`, a `sha256sum`, and a `sha256sum_link` to Microsoft's own
`.sha256sum.txt` beside the file. The recipe checks the archive against **both** and fails if they
disagree; the checksum file for `microsoft-jdk-21.0.12.1-windows-aarch64.zip` was read and matches
the catalogue's `6581076267…`.

One detail the recipe has to be written against rather than find: every package in that document
carries `sha256sum` **and** a misspelled `sha265sum` with the same value. The recipe reads the correct
key and ignores the other.

**The version is Microsoft's file name, not the release name.** `release_name` for the first release of
25 is `jdk-25+36`, one number, while its package is `microsoft-jdk-25.0.0-linux-x64.tar.gz`. The index
version is read out of the package name (`25.0.0`, `21.0.12.1`), and `release_name` travels as
`upstream.release`, which is what that field is for. **The catalogue is complete**, measured on
2026-09-17: every release Microsoft has shipped on a line is listed, identically for all six cells —
16 on 11 (from 11.0.17), 16 on 17 (from 17.0.5), 12 on 21 (from 21.0.2) and 6 on 25 (from 25.0.0) — so
a pinned older release can be re-resolved.

The archive taken is `.tar.gz` on macOS and Linux and `.zip` on Windows. `.pkg`, `.msi` and `.exe` are
installers and are ignored. The Alpine (`musl`) archives are not a cell here.

## What the rule takes out

Measured on the two Windows x86_64 zips:

| | `microsoft-jdk-25.0.4.1-windows-x64.zip` | `microsoft-jdk-21.0.12.1-windows-x64.zip` |
| --- | ---: | ---: |
| compressed | 210.5 MB | 191.8 MB |
| unpacked | 373.1 MB, 584 entries | 327.0 MB, 573 entries |
| `lib/modules` | 138.2 MB | 134.4 MB |
| `lib/src.zip` | **50.0 MB** | **50.6 MB** |
| `lib/ct.sym` | 10.4 MB | 10.2 MB |
| `jmods/` | **84.0 MB** | **79.6 MB** |
| `bin/server/` | 77.3 MB — `jvm.dll` 14.8 + four CDS archives 62.5 | 39.0 MB — `jvm.dll` 13.3 + two CDS archives 25.6 |
| `.pdb` / `.diz` / `.map` | none | none |

Each large directory, against the rule:

- **`lib/modules`, `lib/ct.sym`, the CDS archives (`classes*.jsa`)** — read by `java` and `javac` on
  every start or compile. Kept. The four archives on 25 against two on 21 are the compact-object-
  headers variants 25 added; they are what `-XX:+UseCompactObjectHeaders` maps, so they stay.
- **`jmods/`** — read by `jlink` and `jpackage`, both executables in `bin/` of the same archive. A
  process in the archive reads it, so by the rule it stays. JEP 493 lets a JDK from 24 onward be built
  without `jmods`; if Microsoft ever ships one cell of 25 that way, `parity.py` is what reports it.
- **`lib/src.zip`, 50 MB** — the JDK's own Java sources. **No process in the archive reads it.** An
  IDE does, to show library source and step into it while debugging. By the rule it goes, and that
  is **decided**, in the line Ruby's 225 MB of documentation went in P5. It is also the one decision
  here a reader could reasonably argue the other way, which is why it is named rather than buried in
  a recipe: an IDE pointed at this JDK shows decompiled classes instead of source.

**No debug symbols are inside.** Microsoft publishes them in a separate `debugsymbols` archive, and the
Windows zips contain no `.pdb`, `.diz` or `.map`. Measured before the recipe was written, with this
repository's own `strip.debug_sections` over every binary of the 25.0.4.1 Windows x64 (124), Linux x64
(71) and macOS aarch64 (73) trees and the 11.0.32.1 Linux x64 (73) and Windows ARM64 (81) ones: **not
one carries debug information**, so nothing is stripped on any cell.

**Three more things go, which the Windows-only table above could not show:**

- **`include/`** — `jni.h` and its siblings, 0.2–0.3 MB on every cell. They are read by a C compiler
  building JNI code against this JDK, and no compiler is in the archive. This is Node's `include/node`
  decision again, and `parity.py` names `include` as surplus at the root.
- **`lib/jvm.lib` and `lib/jawt.lib`**, on the Windows cells only — the import libraries for linking
  native code against `jvm.dll`. The same reason, and `parity.py` names `*.lib` as surplus. The Unix
  cells have no counterpart to remove: there the shared library is its own link target.
- **`man/`**, on the Unix cells of 11 and 17 — 75 manual pages in two languages on 11.0.32.1 Linux,
  and none on 21 or 25. A Windows cell has never had them.

**`lib/src.zip`, `include/` and `man/` sit under `Contents/Home/` on macOS**, which is inside a signed
bundle: the tarball carries `Contents/_CodeSignature/CodeResources`. Removing a file from `Home`
breaks the *bundle's* seal and no binary's own signature, and nothing here launches the JDK as a
bundle — `provides` points at `Contents/Home/bin/java`, which is signed on its own. The macOS smoke
test is what proves that rather than this paragraph.

## What the artifact promises

```
kind        "java"
provides    { "java": ".../bin/java[.exe]", "javac": ..., "jar": ..., "jshell": ...,
              "keytool": ..., "jlink": ... }
source      "borrowed"
upstream    { url, sha256 (catalogue, cross-checked against .sha256sum.txt),
              verified_against, project: "microsoft/openjdk",
              release: <release_name, e.g. "jdk-21.0.12.1+1"> }
requires    glibc     Linux, measured
            macos     measured from LC_BUILD_VERSION
            vcredist  Windows, measured — expected absent, see below
smoke       { relocated: true, ran: [...] }
```

Three things said out loud:

- **`JAVA_HOME` is two directories above `provides.java`.** Nothing in the index states it and
  nothing needs to; a daemon that needs `JAVA_HOME` derives it from the path it already has.
- **The macOS tarball keeps its bundle layout.** A macOS JDK is a `Contents/Home/` tree, so
  `provides.java` there is deeper than on Linux and Windows. *Repack, do not rearrange* says it stays
  that way, and `provides` is what absorbs the difference.
- **No `requires.vcredist`, and the rule that says so is not MongoDB's.** Every Windows cell imports
  `vcruntime140.dll` and `msvcp140.dll` — and every one ships them in `bin/` beside `jvm.dll`
  (`vcruntime140`, `vcruntime140_1`, `msvcp140` and `ucrtbase` on 21 and 25 x64; `vcruntime140` and
  `msvcp140` on 11 ARM64). `mongodb.vcredist` reads only the import table, and would declare a
  requirement this archive already satisfies. So the recipe declares a redistributable only for a
  runtime DLL that is imported **and not in the tree**, and expects that set to be empty.

## Licence

GPL-2.0 with the Classpath Exception, plus the third-party notices in `legal/`, which is kept on every
cell. The source for each release is a tag Microsoft publishes, `release/jdk-<version>_1` in
`microsoft/openjdk-jdk<major>u`, and `upstream.release` names it — the MongoDB shape, where the
manifest itself is the route to the source. No source tarball is mirrored.

## No end-of-life dates, on purpose

Microsoft states its support dates on a Learn page, which is prose. Adoptium's roadmap is prose too,
and the machine-readable table that exists is `endoflife.date`, a third-party mirror, which
[P10](../../roadmap-history.md) excludes by name. So `java` has no `eol` field.

## How it is proven

1. Unpack, move the tree somewhere unrelated.
2. `java -version` answers the version the manifest names, and the `release` file's `JAVA_VERSION`
   and `IMPLEMENTOR="Microsoft"` agree with it.
3. `java Hello.java` — the single-file source launcher, so `javac` and `java` are both exercised
   without a build tool.
4. `jlink --add-modules java.base --output <tmp>` produces a runtime that itself answers
   `-version` — which is what proves `jmods/` is present and usable, and is the reason it is kept.

## What this does not do

- **No Java 8.** Microsoft does not build it and points to Temurin, whose 8 has neither ARM64 macOS
  nor ARM64 Windows. It would be a second publisher under this kind and a line with two empty cells;
  if it is wanted, that is its own evaluation.
- **No feature releases** (26, and the 27 and 28 in progress).
- **No Maven, Gradle, Kotlin or sbt.** Separate release trains; each is its own proposal.
- **No `src.zip`.**
- **Nothing in MixEngine.**

## What is left to measure before a line of the recipe is written

1. ~~Layout of the Unix cells~~ — measured: `jmods/` and `src.zip` are on every cell, macOS wraps the
   tree in `Contents/Home`, and `man/` exists on the Unix cells of 11 and 17 only.
2. ~~Import tables on Windows~~ — measured on x64 25 and ARM64 11: the C runtime is bundled.
3. The glibc floor of `libjvm.so` on both Linux architectures, and the macOS floor on both — only a
   runner of that OS can read them with `relocate.floor`.
4. ~~DWARF~~ — measured: none on any cell examined.
5. ~~Marketplace completeness~~ — measured: complete and symmetric.

## The task

**P20 — Java**: `tools/java.py`, `.github/workflows/build-java.yml`, `docs/packages/java.md`, a row in
the README table, and the absence in `eol.py`'s docstring. No pipeline module changes.
