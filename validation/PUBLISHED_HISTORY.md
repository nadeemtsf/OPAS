# Published commit history

The research report and validation manifests identify the local commits that
were measured. Publication used the connected GitHub app because command-line
Git in this workspace had no write credentials. The app creates commit metadata
on GitHub, so the published commit IDs differ from the local IDs.

Each published stage was checked against its original Git tree hash. Matching
trees establish identical tracked file names, contents and modes at that stage;
the change in commit IDs does not change the measured code or result files.

| Stage | Local commit recorded in the evidence | Published GitHub commit | Verified file tree |
| --- | --- | --- | --- |
| Interval refinement and ten-second window checks | `19548cdbc9486f1b990fd2ad881544e6482d02d3` | [6dc21469c916d72d4b319aeabef1879d759212fb](https://github.com/nadeemtsf/OPAS/commit/6dc21469c916d72d4b319aeabef1879d759212fb) | `fe55a9e4df219567f1385c35e9cc7d131e41c57a` |
| Exact UTC selection and explicit incomplete-search handling | `9637985be260c7476759ae6ebe246f18f074514e` | [fbb9993ede1a001d21429a29d1aa58c229e1a42c](https://github.com/nadeemtsf/OPAS/commit/fbb9993ede1a001d21429a29d1aa58c229e1a42c) | `565d6b0119c7d032e64be25a7cb28884cd7c7050` |
| Live diagnostics, five-second final checks and report guides | `b0acf9a60d99455deed9d421764fcc55c92951ea` | [09124420b84647d75b0c7a4a25f5c32bd27017cf](https://github.com/nadeemtsf/OPAS/commit/09124420b84647d75b0c7a4a25f5c32bd27017cf) | `7bf655db8f9b06299b23480bc12c5d8104ab82af` |

The published history starts from the same `fix/scanner-accuracy` base,
`50fb28f61a2fef1a1f29ea1d92e2089333fb24cc`. The original local commits remain
preserved in a local archive branch for the research provenance. Historical
research links still pin `8fef312648e542060256b94fef2cbce49be4e161`.

This mapping is a later documentation addition, so the final branch head
can differ from the third published ID in the table while retaining the tested
application files. [The evidence index](EVIDENCE.md) locates result files;
[runtime checks](RUNTIME_CHECKS.md) describes the current application guards.

No pull request or merge is part of this publication.
