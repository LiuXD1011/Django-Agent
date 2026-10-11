globalThis.fetch = async () => { throw new Error('unmocked network is forbidden in this isolated test run') }
