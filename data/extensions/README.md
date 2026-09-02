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

There is no manifest here yet. The first three — Mailpit, phpMyAdmin and Adminer
— are MixEngine's task T82, and one of them needs T81b before it can be served at
all. Until then the published document is
`{"schema": 1, "generated_at": …, "extensions": []}`, which is an answer rather
than a 404.

Adding one is a file here and a run of `release/publish-extensions.sh`.
