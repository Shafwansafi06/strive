"""Run in the separate Python 3.10 Fairseq export environment (see MODELS.md).

Recreates NII's published architecture and loads only the downloaded safetensors.
Output is a frozen 2-second TorchScript encoder and classifier, no training.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=["mms-300m", "xls-r-2b"], default="mms-300m")
    p.add_argument("--weights", required=True, help="Local model.safetensors from the exact NII model")
    p.add_argument("--output", default="models/cm.pt")
    args = p.parse_args()
    import torch
    from fairseq.models.wav2vec import Wav2Vec2Model, Wav2Vec2Config
    from safetensors.torch import load_file
    def sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    small = args.variant == "mms-300m"
    dim = 1024 if small else 1920
    config = Wav2Vec2Config(quantize_targets=True, extractor_mode="layer_norm", layer_norm_first=True,
        final_dim=768 if small else 1024, latent_temp=(2.0, .1, .999995), encoder_layerdrop=0.,
        dropout_input=0., dropout_features=0., dropout=0., attention_dropout=0., conv_bias=True,
        encoder_layers=24 if small else 48, encoder_embed_dim=dim,
        encoder_ffn_embed_dim=4096 if small else 7680, encoder_attention_heads=16, feature_grad_mult=1.)

    class FrozenNII(torch.nn.Module):
        def __init__(self):
            super().__init__()
            # Preserve the state dict hierarchy published by NII.
            self.m_ssl = torch.nn.Module()
            self.m_ssl.model = Wav2Vec2Model(config)
            self.proj_fc = torch.nn.Linear(dim, 2)

        def forward(self, waveform: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            x = torch.nn.functional.layer_norm(waveform, waveform.shape[1:])
            frames = self.m_ssl.model(x, mask=False, features_only=True)["x"]
            embedding = frames.mean(1)
            spoof = self.proj_fc(embedding).softmax(-1)[:, 0]
            return embedding, spoof

    model = FrozenNII().eval().requires_grad_(False)
    model.load_state_dict(load_file(args.weights), strict=True)
    torch.manual_seed(26104)
    probe = torch.randn(1, 32000)
    with torch.inference_mode():
        compiled = torch.jit.trace(model, probe, strict=True)
        for scale in (.01, .1, 1.):
            test = torch.randn(1, 32000) * scale
            expected, got = model(test), compiled(test)
            for a, b in zip(expected, got):
                torch.testing.assert_close(a, b, rtol=1e-4, atol=1e-5)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.jit.save(compiled, str(output))
    metadata = {"cm_model_id": f"nii-yamagishilab/{args.variant}-anti-deepfake", "cm_dimension": dim,
                "input_samples": 32000, "source_sha256": sha256(args.weights),
                "sha256": {output.name: sha256(output)}, "license": "CC-BY-NC-SA-4.0",
                "export_parity_checked": True}
    (output.parent / "cm-export.json").write_text(json.dumps(metadata, indent=2))
    print("Exported", output)


if __name__ == "__main__":
    main()
