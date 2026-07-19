"""gemma._resolve_gguf self-heals when a pinned quant filename 404s."""

import lemory.providers.gemma as g


def test_resolve_gguf_direct_hit(monkeypatch):
    calls = []
    monkeypatch.setattr(g, "hf_hub_download", None, raising=False)
    import huggingface_hub

    def fake_dl(repo, file):
        calls.append(file)
        return f"/cache/{file}"

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_dl)
    p = g._resolve_gguf("ggml-org/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_0.gguf")
    assert p.endswith("gemma-4-E4B-it-Q4_0.gguf")
    assert calls == ["gemma-4-E4B-it-Q4_0.gguf"]  # no fallback needed


def test_resolve_gguf_falls_back_to_available_quant(monkeypatch):
    import huggingface_hub

    repo_files = [
        "gemma-4-E4B-it-BF16.gguf", "gemma-4-E4B-it-Q4_0.gguf",
        "gemma-4-E4B-it-Q8_0.gguf", "mmproj-gemma-4-E4B-it-Q8_0.gguf",
        "mtp-gemma-4-E4B-it-Q4_0.gguf",
    ]

    def fake_dl(repo, file):
        if file == "gemma-4-E4B-it-Q4_K_M.gguf":  # the (missing) pinned file
            raise huggingface_hub.errors.RemoteEntryNotFoundError("404")
        return f"/cache/{file}"

    class FakeApi:
        def list_repo_files(self, repo):
            return repo_files

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_dl)
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)

    p = g._resolve_gguf("ggml-org/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_K_M.gguf")
    # Q4_K_M missing → next preferred present is Q4_0; never the mmproj/mtp sidecars
    assert p.endswith("gemma-4-E4B-it-Q4_0.gguf")


def test_resolve_gguf_skips_sidecars_only_repo(monkeypatch):
    import huggingface_hub

    # a repo where the only Q4 is inside mmproj/mtp — must not pick those,
    # falls through to a real quant (Q8_0 here)
    repo_files = ["mmproj-x-Q4_0.gguf", "mtp-x-Q4_0.gguf", "x-Q8_0.gguf"]

    def fake_dl(repo, file):
        if file == "x-Q4_K_M.gguf":
            raise huggingface_hub.errors.RemoteEntryNotFoundError("404")
        return f"/cache/{file}"

    class FakeApi:
        def list_repo_files(self, repo):
            return repo_files

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_dl)
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    p = g._resolve_gguf("repo/x", "x-Q4_K_M.gguf")
    assert p.endswith("x-Q8_0.gguf")
