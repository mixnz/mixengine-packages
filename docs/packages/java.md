# Java

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

One publisher, one recipe, every cell borrowed:

| OS / arch | Range | How |
| --- | --- | --- |
| Windows x86_64, aarch64 | **11, 17, 21, 25** | **borrowed** — Microsoft Build of OpenJDK, `microsoft-jdk-<version>-windows-<arch>.zip` |
| macOS aarch64, x86_64 | **11, 17, 21, 25** | ditto, the `macos` tarballs |
| Linux x86_64, aarch64 | **11, 17, 21, 25** | ditto, the `linux` tarballs |

Only LTS lines, read off Adoptium's `available_lts_releases` at or above 11, so the next one is offered
the day it is called one. A feature release is supported for six months, which is not a row worth the
permanence promise. The design, and everything measured before the recipe was written, is
[the spec](../superpowers/specs/2026-09-17-java-packaging-design.md).

## Why Microsoft

**Eclipse Temurin is the build everybody names, and it cannot fill the row.** It publishes a Windows
ARM64 JDK on one LTS line, from 21.0.5, and on no release of 11, 17 or 25. Filling those cells from a
second vendor would put two builds under one version number — the MariaDB lesson — and leaving them
empty would make the newest LTS the least complete row. Microsoft publishes all six cells on all four
lines, from one build system. It does not build 8, which is why 8 is not offered.

**The catalogue is Microsoft's own entry in the Adoptium Marketplace**, which lists every release
Microsoft has shipped on a line, identically for all six cells, with a SHA-256 per archive; Microsoft
also publishes a `.sha256sum.txt` beside each archive, and `tools/java.py` refuses a release whose two
digests disagree. `api.adoptium.net` answers 403 to Python's default `User-Agent`, so the recipe
names itself, as the Redis recipe does.

**The version is Microsoft's file name.** The first release of 25 is `jdk-25+36` in the catalogue and
`microsoft-jdk-25.0.0-…` as a file; the index says `25.0.0`, and the release name travels as
`upstream.release`.

## What goes

About 54–59 MB of every cell, and nothing a process in the JDK reads:

- **`lib/src.zip`**, 50 MB — the class library's sources, which an IDE reads to show them. An IDE
  pointed at this JDK shows decompiled classes instead.
- **`include/`** — `jni.h` and its siblings, which a C compiler building JNI code reads.
- **`lib/jvm.lib` and `lib/jawt.lib`**, on Windows — import libraries for a linker.
- **`man/`**, on the Unix cells of 11, 17 and 21 — 25 ships none, and Windows never has.

**`jmods/` stays**, 80–90 MB of it, because `jlink` reads it and `jlink` is in the archive. So do the
CDS archives — four on 25, which added compact object headers — and `ct.sym`, which `javac --release`
reads.

**Nothing is stripped**: no binary on any cell measured carries debug information; Microsoft publishes
symbols separately.

**On macOS the JDK is a bundle, and it stays one.** The home is `Contents/Home`, which is where
`provides` points, and the three removals above sit inside it. That breaks the *bundle's* seal in
`Contents/_CodeSignature` and no binary's own signature — nothing launches this JDK as a bundle, and
the macOS smoke test is what says the binaries still run.

## Two things that are true of a JDK and of nothing else here

**No `requires.vcredist`, though every Windows cell imports the Visual C++ runtime.** Microsoft ships
it: `vcruntime140.dll`, `msvcp140.dll` and, on newer lines, `ucrtbase.dll` sit beside `jvm.dll` in
`bin/`. The recipe declares a redistributable only for a runtime DLL that is imported and absent from
the tree, which the rule `mongodb.py` uses would not see.

**Every library in the JDK imports the VM by a name no search can find.** `java.dll`, `net.dll`,
`zip.dll` and the rest import `jvm.dll`, which is in `bin/server/`; the launcher loads that file by
path before any of them, and the loader answers their import with the module already in the process.
`relocate.verify` models a file search and reports those imports as unresolved, so `java.verify` sets
aside exactly that complaint, and only while the VM is in `server/` where the launcher looks.

## What a Linux JDK expects of the machine

**The first CI run refused all four Linux cells, and it was right to.** Microsoft links a Linux JDK
against the distribution's libraries and ships none of them: `libz.so.1` is imported by every launcher
and by `libjli`, so no JVM starts without it; `libfreetype.so.6` by `libfontmanager`, which renders
text headless or not; the X11 family by AWT and the splash screen; `libasound.so.2` by `javax.sound`.
Temurin is built the same way.

They are **declared, not bundled** — carrying a stranger's X11 stack in a runtime forever is the wrong
trade, and bundling `libz` alone would raise the glibc floor to the runner's. So the manifest states
them in `requires.libraries`, an optional field the index schema gained for this row: the sonames read
out of each binary's own `DT_NEEDED`, which is what Microsoft linked rather than what one
distribution's loader pulled in behind it. `java.verify` sets exactly those aside, and a release that
links something new is refused until somebody has read what it is.

## What is proven

From a directory the tree has been moved to, with every `JAVA*`, `JDK_*`, `_JAVA*` and `CLASSPATH`
variable of the runner removed: `java --version` has to name Microsoft; `javac` compiles and `java`
runs a program that reports its own `java.home`, `Runtime.version()` and a SHA-256; `jar` and `jshell`
start; `keytool -list -cacerts` finds the CA certificates a TLS connection would trust; and `jlink`
builds a `java.base` runtime out of `jmods/` that itself has to start. Hiding `lib/modules` turns the
first of those into `Failed setting boot class path`.

**`JAVA_HOME` is two directories above `provides.java`.** Nothing in the index states it, because a
daemon that has the path to `java` already has it.

**No end-of-life dates.** Microsoft and Adoptium both state support as prose, and the only
machine-readable table is a third-party mirror.
