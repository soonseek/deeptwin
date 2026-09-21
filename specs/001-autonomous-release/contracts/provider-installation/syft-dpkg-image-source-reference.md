# Task 46 Syft v1.42.3 Debian-status and image-metadata source reference

> Human implementation reference only. This records tagged source behavior; it is not production/test runtime truth, observed scanner output, or authorization to change the promoted contract. Retrieved 2026-09-20 from public first-party Syft source. No scanner or user credential was used.

## Source identity and integrity

The annotated `anchore/syft` tag `v1.42.3` resolves to commit [`860126c650c2d05b63b83a3895e41268162315a3`](https://github.com/anchore/syft/tree/860126c650c2d05b63b83a3895e41268162315a3). Each tagged raw file below was byte-for-byte equal to the same path at that commit. Byte counts and SHA-256 values cover the **complete raw file**, not the selected excerpts in this note.

| Complete tagged source | Bytes | SHA-256 |
| --- | ---: | --- |
| [`cataloger.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/cataloger.go) | 1,131 | `b753e440ea56036b354797a3ace17f3ac0d7cf314434b66739394bf6ded1eb3a` |
| [`parse_dpkg_db.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/parse_dpkg_db.go) | 8,611 | `b01f1e6e6ab590028d8c24cc5f98cad5876f407204c750b8ae4d350afb1b88a1` |
| [`package.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/package.go) | 10,004 | `1a1368c90dd602af95a550e654825da35e0b9d803a18faac1add8576807047e0` |
| [`syft/pkg/dpkg.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/dpkg.go) | 3,676 | `7dedd2aa40fe2543af419e6819f5becb382d23f4cd362b0eb5314b192e9d893a` |
| [`parse_dpkg_db_test.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/parse_dpkg_db_test.go) | 13,712 | `3ded07944dc4f76d497bfbfa5236603f4b83e689fb58a3684c8aaa384df32872` |
| [`deinstall` fixture](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/testdata/var/lib/dpkg/status.d/deinstall) | 1,869 | `974040c824356c9e1dc8be90cef02e62dcf1733a8e75978b4e01f19e950f4dfc` |
| [`image_metadata.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/source/image_metadata.go) | 1,422 | `24c180264668ac473a753312432c5d7acb6b04b1954db8b66953b53284db9ba1` |
| [`image_source.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/source/stereoscopesource/image_source.go) | 4,543 | `6cc1b59c3af80ae598d45964633f474f75603a043220ef510feedb2779e13779` |
| [`to_format_model.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/format/syftjson/to_format_model.go) | 10,099 | `4a53afff4dd90e359c8923fc70acbb4659b6fcdc67f86f7ab99236db5cedf5e7` |
| [`encoder.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/format/syftjson/encoder.go) | 1,289 | `01d2c17d7344f05c6e679d04c2f498f8d9fcde7064190e60fc85b78bc210232d` |
| [`model/source_test.go`](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/format/syftjson/model/source_test.go) | 19,184 | `dee93fa5501677251bb96a633b35d281a712cc76f95f7782bb1615f133ebcf2c` |

## 1. `dpkg-db-cataloger`: exact `Status` behavior

### Source path

`NewDBCataloger` registers the name `dpkg-db-cataloger` and sends `**/lib/dpkg/status`, `**/lib/dpkg/status.d/*`, `**/lib/opkg/info/*.control`, and `**/lib/opkg/status` to `parseDpkgDB`. The parser calls `parseDpkgStatus`, propagates parse errors, converts each retained entry with `newDpkgPackage`, and also returns an error when no packages remain. [Cataloger registration](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/cataloger.go), [parser entry point](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/parse_dpkg_db.go).

### Bounded verbatim source excerpts

These are selected verbatim lines from the complete files above; omitted surrounding code is not represented, and no digest is asserted for these excerpts.

```go
const (
	deinstallStatus string = "deinstall"
)
```

```go
	Status        string `mapstructure:"Status"`
```

```go
	// Skip entries which have been removed but not purged, e.g. "rc" status in dpkg -l
	if strings.Contains(raw.Status, deinstallStatus) {
		return nil, nil
	}
```

`raw` begins as a zero-valued `dpkgExtractedMetadata`, then `mapstructure.Decode` fills fields found in the parsed paragraph. After the filter, the only separate admission check is `raw.Package == ""`; there is no equality check for `"install ok installed"` and no nonempty check for `Status`. [Exact parser](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/parse_dpkg_db.go).

For an otherwise parsable paragraph with a nonempty `Package`, the tagged behavior is therefore:

| Raw `Status` field | Result of this status check | Why |
| --- | --- | --- |
| absent, or present with empty value | admitted | decoded string is empty; it does not contain lowercase `deinstall` |
| `install ok installed` | admitted | no lowercase `deinstall` substring |
| `deinstall ok config-files` | excluded | contains lowercase `deinstall` |
| any value containing exact lowercase `deinstall` anywhere | excluded | `strings.Contains`, not token parsing |
| `install ok config-files`, `purge ok config-files`, or `Deinstall ...` | admitted by this check | `config-files` is not tested and matching is case-sensitive |

The last row describes parser mechanics, not Debian validity. Other syntax errors can still reject the paragraph. The tagged fixture contains one `install ok installed` paragraph and one `deinstall ok config-files` paragraph; the test expects only the first entry. Thus `config-files` is incidental to the fixture—the implemented exclusion predicate is the lowercase `deinstall` substring. [Fixture](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/testdata/var/lib/dpkg/status.d/deinstall), [test](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/parse_dpkg_db_test.go).

### Emitted metadata and proof limit

The parser's temporary `dpkgExtractedMetadata` has `Status`, but `pkg.DpkgDBEntry` does not. Its JSON fields are exactly:

| Always named in JSON | `omitempty` | Never serialized |
| --- | --- | --- |
| `package`, `source`, `version`, `sourceVersion`, `architecture`, `maintainer`, `installedSize`, `files` | `provides`, `depends`, `preDepends` | Go-only `Description`; temporary raw `Status` has no destination field |

`newDpkgPackage` assigns the `DpkgDBEntry` directly to `Package.Metadata`; later enrichment only merges file records into that metadata. It also records the database and related evidence as package locations, but it does not retain the source paragraph or `Status` value. [Metadata type](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/dpkg.go), [package construction and enrichment](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/pkg/cataloger/debian/package.go).

Primary-source conclusion: a Syft JSON `dpkg-db-entry` proves that the paragraph survived the tagged parser, which only proves “no exact lowercase `deinstall` substring” plus the other parsing checks. It does **not** prove that `Status` was present, nonempty, or exactly installed, and it does not preserve status contents for later re-evaluation.

**Project recommendation (inference, not upstream behavior):** do not invent `metadata.status`; it is absent from the tagged native type and conflicts with the selected closed branch. If “nonempty actual installed status” means a stronger predicate than the tagged non-`deinstall` filter, require separately retained original status bytes/evidence and parse that field, or explicitly redefine the contract phrase to the weaker source-grounded predicate. The current Syft JSON alone cannot support the stronger check.

## 2. Native image `Source.metadata` shape

The schema's unconstrained `Source.metadata` does not supply this shape. The tagged `source.ImageMetadata` and `source.LayerMetadata` structs, the stereoscope mapper, and the Syft JSON encoder do.

### Literal tagged types

This is the complete field block from `syft/source/image_metadata.go`; comments are omitted, so the excerpt itself has no asserted digest:

```go
type ImageMetadata struct {
	UserInput      string            `json:"userInput"`
	ID             string            `json:"imageID"`
	ManifestDigest string            `json:"manifestDigest"`
	MediaType      string            `json:"mediaType"`
	Tags           []string          `json:"tags"`
	Size           int64             `json:"imageSize"`
	Layers         []LayerMetadata   `json:"layers"`
	RawManifest    []byte            `json:"manifest"`
	RawConfig      []byte            `json:"config"`
	RepoDigests    []string          `json:"repoDigests"`
	Architecture   string            `json:"architecture"`
	Variant        string            `json:"architectureVariant,omitempty"`
	OS             string            `json:"os"`
	Labels         map[string]string `json:"labels,omitempty"`
	Annotations    map[string]string `json:"annotations,omitempty" id:"-"`
}

type LayerMetadata struct {
	MediaType string `json:"mediaType"`
	Digest    string `json:"digest"`
	Size      int64  `json:"size"`
}
```

[Complete tagged type source](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/source/image_metadata.go).

### Exact emitted keys and representations

| JSON key(s) | Tagged Go type / emitted representation | Presence behavior |
| --- | --- | --- |
| `userInput`, `imageID`, `manifestDigest`, `mediaType`, `architecture`, `os` | `string` / JSON string | no `omitempty`; key is always emitted, including empty string |
| `imageSize` | `int64` / JSON integer number | no `omitempty`; key is always emitted |
| `tags`, `repoDigests` | `[]string` / JSON string arrays | no `omitempty`; `toSourceModel` changes nil to nonnil empty slices, so emitted image metadata uses `[]`, not null, when absent |
| `layers` | `[]LayerMetadata` / array of objects | no `omitempty`; the stereoscope mapper allocates it with `make`, so that path emits `[]` when there are zero layers |
| each layer's `mediaType`, `digest`, `size` | string, string, `int64` / string, string, integer | all three keys always emitted; there is no `omitempty` |
| `manifest`, `config` | `[]byte` / base64 of the bytes inside a JSON string; nil would encode as null | always named; they are **not** embedded decoded JSON objects |
| `architectureVariant` | `string` | omitted exactly when empty |
| `labels`, `annotations` | `map[string]string` / JSON object | omitted when nil or empty; otherwise string keys to string values |

There is no `repoTags` key: the repository-tag values are emitted under `tags`. `repoDigests` is distinct. The stereoscope mapper copies `img.Metadata.RawManifest`, `RawConfig`, `RepoDigests`, `Architecture`, `Variant`, and `OS`; builds each layer from its metadata media type/digest/size; and sources labels from the image config. It does not populate `Annotations` on this path. [Image mapper](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/source/stereoscopesource/image_source.go).

The encoder passes the format model to Go's `encoding/json.NewEncoder` without an image-specific marshaler. The tagged source round-trip test supplies base64 JSON strings for `manifest` and `config` and recovers their raw `[]byte` values, confirming the representation. [Encoder](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/format/syftjson/encoder.go), [format projection and empty-array normalization](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/format/syftjson/to_format_model.go), [tagged round-trip test](https://raw.githubusercontent.com/anchore/syft/860126c650c2d05b63b83a3895e41268162315a3/syft/format/syftjson/model/source_test.go).

Primary-source limit: these fields report what Syft mapped and serialized. Their presence alone does not establish the promoted contract's digest, platform, ordered-layer, size-domain, or staged-R1 identity equalities; those remain separate selected semantic checks rather than facts supplied by the open upstream schema.
