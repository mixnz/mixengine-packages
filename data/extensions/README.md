# The extension roster

One `<id>.toml` per extension, in the format MixEngine's
`mixengine-core::extensions::manifest` reads — the same file
`mix extension install --path` takes. `.github/workflows/publish-extensions.yml`
renders every file here into the signed `extensions.json` that
`mix extension available` reads. MixEngine's roadmap task T81a.

**The file name is not decoration.** A file's stem must be the `[extension] id`
it declares, and the generator refuses the run otherwise. That is also what makes
a repeated id impossible: a directory holds one `mailpit.toml`.

**Nothing here is validated by this repository.** The generator is built out of a
`mixnz/mixengine` checkout and uses that build's own reader, so what a run refuses
is exactly what an installed MixEngine would refuse — there is no second set of
rules here to drift from it. The same build holds the key constant, so a
`minisign.pub` that is no longer the one MixEngine checks against fails the run
before a manifest is opened.

**The three that arrived with MixEngine's task T82** are Mailpit `1.31.0`,
phpMyAdmin `5.2.3` and Adminer `6.0.1`. Each names an upstream artifact by URL,
SHA-256 and size — none of these files is a mirror, and this repository publishes
none of their bytes.

**MixDB, the fourth, is withdrawn.** It arrived with MixEngine's task T84 as a
`desktop-app` entry: an application MixEngine *finds* on the machine and hands a
connection to, naming no artifact. MixDB then became MixEngine's own window, MixLab
(phase 12), which ships in every installer and takes `mix database open` without
any extension — so an entry offering to find it was offering the application
already running. `git log -- data/extensions/mixdb.toml` has the manifest as it
was.

**A version here is upstream's, and this file is what goes stale.** Raising one
means a new `url`, a new `sha256` and a new `size`, and for phpMyAdmin also
`[web-app].root`, which is the directory its archive unpacks to — the version is
in the name. Adminer's generated `index.php` includes its artifact by file name
for the same reason, so both halves move together. The manifests in
`mixnz/mixengine`'s `crates/mixengine-testkit/fixtures/extensions/` are the same
files, and a change here belongs in both.

Adding or raising one is a file here and a run of
`release/publish-extensions.sh`. `check-extensions.yml` is what notices when the
published document stops matching this directory.
