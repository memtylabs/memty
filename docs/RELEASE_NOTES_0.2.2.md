# Memty 0.2.2

This release improves privacy protections, browser usability, and documentation.

## Privacy and security

- Limit unclassified namespace summaries to local providers and respect active facts' provider restrictions when including them.
- Remove a namespace summary when a fact is forgotten, and compact the summary search index.
- Require MCP Python SDK 1.30 or newer in the 1.x series, incorporating upstream fixes.

Credential detection is heuristic and may miss secrets, including some credentials identified by a fact's title. Explicitly mark sensitive facts, and avoid storing credentials when possible. A later change on the repository's main branch improves title-based detection; it is not part of the published 0.2.2 package.

## Browser extension

- Delete all facts in a selected namespace after confirmation, including private and search-hidden facts.
- Fix typing in the review panel being redirected to the chat prompt.

## Guides and examples

- Add user guides for installation, browser and MCP setup, memory commands, privacy, Python usage, troubleshooting, and maintenance.
- Add runnable Python examples using temporary vaults, and include the guides and examples in the source distribution.

## License

Memty 0.2.2 is distributed under Apache-2.0. Versions 0.2.1 and earlier were published under MIT.

## Upgrade

```sh
python -m pip install --upgrade memty
memtyd stop
memty extension
```

Restart the browser bridge and reload the extension in your browser's extensions page. See the [user guides](https://github.com/memtylabs/memty/tree/main/docs) for setup and troubleshooting.
