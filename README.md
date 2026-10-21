# flybrainlabs research

Reproducible preparation and evaluation for [flybrainlabs](https://flybrain.work/).

## Scope

Official-source preparation, graph/model generation, immutable scientific task definitions, calibration, independent numerical references and authorized model evaluation. Public descriptors are included; full datasets and cached model binaries are not.

## Source map

- `tools/prepare_graph.py`
- `tools/prepare_model_v0.py`
- `tools/reference_sim.py`
- `tools/evaluate_model.py`
- `web/data/target-mining-v2/`

Each maintained file has one owning repository. `component.json` maps maintained
files into the shared build layout. Dependencies are pinned by commit in the
[infrastructure release manifest](https://github.com/flybrainlabs/infra/blob/main/release-manifest.json).

## Build and test

Use Rust 1.90 or newer (the source uses edition 2024), Node 22 or newer and Python
3.11 or newer. Optional scientific Python dependencies are in
`tools/requirements-research.txt` in the assembled workspace. SBF builds require
the compatible Solana/Agave build tools.

First assemble the exact source revisions:

```sh
git clone https://github.com/flybrainlabs/infra.git flybrainlabs/infra
python3 flybrainlabs/infra/tools/workspace.py checkout --repos flybrainlabs
python3 flybrainlabs/infra/tools/workspace.py assemble --repos flybrainlabs --output flybrainlabs-workspace
cd flybrainlabs-workspace
npm ci
```

Run the applicable checks from the assembled workspace:

```sh
python3 -B -m unittest discover -s tests -p test_model_evaluation.py -v
python3 -B -m unittest discover -s tests -p test_connectome_coverage.py -v
```

The assembled layout keeps cross-component import paths intact. Cloning
this repository alone does not supply its external components. The assembler
creates a disposable build layout; all maintained edits belong to the owning
repositories. Use `workspace.py sync` for intentional changes made in that layout,
then review the component diffs and validate them before publication.

Full-model and browser integration checks require existing, verified local
resources and explicit arguments. They do not download a model or reset a
browser profile by default. Isolated chain checks require their own local bank;
production funds and addresses are never substituted.

## Development policy

- All maintained documentation, commit messages, issues, PRs and release notes
  are written in English. Product interfaces may remain bilingual.
- Completed, verified updates are committed and pushed automatically to
  `flybrainlabs/research` using normal fast forwards.
- Keys, wallets, customer inputs, node databases, private artifacts, browser
  profiles and model caches stay outside Git and website exports.
- Production payment and reward configuration remains disabled until its actual
  asset identities, authorities, funds and operating gates are satisfied.

See [AGENTS.md](AGENTS.md), the
[development guide](https://github.com/flybrainlabs/docs/blob/main/docs/DEVELOPMENT.md),
[architecture](https://github.com/flybrainlabs/docs/blob/main/docs/ARCHITECTURE.md)
and [status](https://github.com/flybrainlabs/docs/blob/main/docs/STATUS.md).

## License and provenance

Project code retains the declared `MIT OR Apache-2.0` license. Data descriptors
and third-party assets retain their own source attribution and licenses; this
code license does not relicense MaleCNS data or third-party libraries. The
maintained sources preserve numerical/identity fixtures and the meaning of
existing scientific and financial records. See [NOTICE](NOTICE).

## Wallet mining V3

The finite Solana Devnet wallet-mining extension is described in the
[execution and acceptance record](https://github.com/flybrainlabs/docs/blob/main/docs/WALLET_MINING_V3_EXECUTION.md)
and [canonical Result layout](https://github.com/flybrainlabs/docs/blob/main/docs/WALLET_MINING_V3_RESULT_LAYOUT.md).
Use the assembled workspace for cross-component imports and pinned release
verification. Public receipts are in the contracts repository under
`deploy/wallet-mining-v3/`; private signers, signed journals and full response
archives remain outside source repositories. The two-unit acceptance budget is
complete. Future paid work requires a new prospectively frozen finite plan.
Actual extension-wallet and physical-device confirmation remain separate gates.

## V4 task reserve calibration

`tools/calibrate_factory_reserve_v4.py` prospectively selects new disjoint
downstream readouts outside the complete historical and registered V4 inventory.
Run it from an assembled workspace with NumPy, the retained full native model,
and its verified event cache:

```sh
python tools/calibrate_factory_reserve_v4.py --historical-inventory /private/history.json --output /private/reserve-batch --groups 16
```

The output is an unregistered reserve with frozen preregistration and independent
evaluation of complete-model events. It never signs, registers tasks, allocates
FBW, or claims biological validation. Existing simulation kernels are reused
only when all simulation inputs match. Include registered and previously
reserved scientific identities in each following inventory. A completed batch
is retained and cannot be silently replaced.

## Exact event execution and scientific round fixtures

`tools/scientific_fixture_v5.mjs` creates an explicitly synthetic six-cell cyclic
fixture for native/WASM, evidence and settlement acceptance. It is not connectome
data or biological validation. The retained 165,122-cell model was separately
measured on sparse and dense inputs. See the
[V5 specification and measured limits](https://github.com/flybrainlabs/docs/blob/feat/scientific-mining-20261020/docs/SCIENTIFIC_MINING_V5.md).

## Continuous V4 mining candidate

Cooperative complete-kernel calibration checkpoints preserving preregistration and scientific rules. The feature branch is `feat/continuous-mining-20261021`.

Run from the assembled workspace with the existing pinned dependencies:

```sh
python3 tests/calibration_resume_v4.py --help
```

See `docs/CONTINUOUS_MINING_V4_20261021.md` and the infrastructure
`docs/CONTINUOUS_MINING_V4_20261021_ACCEPTANCE.json` for evidence boundaries.
Source publication does not establish live acceptance or activate the service.
