"""Build backend/app/data/knowledge.json: per-subnet field, hardware tier, GPU and software needs.

Inputs: profiles.json (task / miner role / conditions summarised from each subnet's README and
miner docs) and an optional digests.json (condensed docs text) used only to detect software.
The category/tier table below was curated by reading those profiles; re-run after editing it.

    python tools/build_knowledge.py backend/app/data/profiles.json [digests.json]
"""
import json, re, sys
from pathlib import Path

# tier -> (label, monthly rent low USD, high USD, hardware summary)
TIERS = {
    "none":    ("No server",        0,    15, "Browser wallet / web account only"),
    "cpu":     ("CPU server",      10,    60, "VPS, 2-8 vCPU, 8-16 GB RAM, no GPU"),
    "api":     ("CPU + paid APIs", 40,   250, "Small VPS plus LLM/API credits"),
    "gpu1":    ("Consumer GPU",   150,   450, "1x 16-24 GB GPU (RTX 3090/4090, A5000/L4)"),
    "gpu2":    ("Pro GPU",        500,  1500, "48-80 GB GPU (A6000/L40S/A100) or 2-4 consumer GPUs"),
    "gpu3":    ("GPU cluster",   1800,  9000, "Multiple H100/H200-class GPUs, datacenter grade"),
    "infra":   ("Infrastructure", 100,   700, "Nodes with large storage, bandwidth or public IPs"),
    "capital": ("Capital / stake",  10,   100, "Small server, but needs trading capital, collateral or stake"),
    "unknown": ("Unknown",       None,  None, "Not published"),
}

# netuid: (field, tier, gpu/hardware note)
T = {
 1: ("LLM & Agents", "api", ""), 2: ("Unknown", "unknown", ""),
 3: ("Model Training", "gpu2", "GPU to train and submit a model"),
 4: ("Compute", "gpu3", "TargonOS-verified H100/H200 nodes"),
 5: ("LLM & Agents", "api", "LLM backend + Docker sandbox"),
 6: ("Forecasting", "api", "Paid LLM gateway keys"),
 7: ("Finance & DeFi", "capital", "SOL/TAO collateral bond + chain RPCs"),
 8: ("Finance & DeFi", "capital", "Trading collateral"),
 9: ("Model Training", "gpu1", "CUDA GPU 16 GB+ VRAM (RTX 4090)"),
 10: ("Inference Optimisation", "gpu2", "GPU matching the benchmark target"),
 11: ("LLM & Agents", "api", "No GPU; model-cost capped scenarios"),
 12: ("Compute", "gpu2", "GPU executors on Ubuntu, collateral for organic jobs"),
 13: ("Data & Scraping", "api", "Storage + scraping credentials"),
 14: ("Inference Optimisation", "gpu2", "GPU for kernel/engine benchmarking"),
 15: ("LLM & Agents", "api", "Docker for local benchmark"),
 16: ("Robotics", "unknown", ""),
 17: ("Vision & Media", "gpu2", "GPU for 3D generation (24-48 GB)"),
 18: ("Science", "gpu1", "Own forecasting model + GPU"),
 19: ("Infrastructure", "infra", "Archive nodes: multi-TB NVMe + bandwidth"),
 20: ("Vision & Media", "gpu1", "GPU to train video model"),
 21: ("Forecasting", "cpu", "Containerised model"),
 22: ("Data & Scraping", "gpu1", "GPU for embeddings + proxies"),
 23: ("Security & Alignment", "cpu", "Docker, Node 18, Python 3.12"),
 24: ("Model Training", "gpu3", "Multi-GPU long-context training"),
 25: ("Infrastructure", "infra", "VPN/relay nodes with routable IPs"),
 26: ("Security & Alignment", "gpu1", "8 vCPU/32 GB + 8 GB+ VRAM GPU"),
 27: ("Data & Scraping", "gpu1", "GPU to run Quasar locally"),
 28: ("Inference", "api", "Provider API keys + Phala Cloud TEE"),
 29: ("Inference Optimisation", "gpu2", "GPU for serving benchmarks"),
 30: ("Finance & DeFi", "cpu", ""),
 31: ("LLM & Agents", "unknown", ""), 32: ("Security & Alignment", "gpu1", "GPU for detection models"),
 33: ("Data & Scraping", "api", "CPU 8 GB RAM + OpenAI key"),
 34: ("Vision & Media", "gpu1", "GPU for generative track"),
 35: ("Unknown", "unknown", ""),
 36: ("Model Training", "gpu1", "Single consumer GPU to fine-tune"),
 37: ("Security & Alignment", "gpu1", "GPU for SAE training + alpha holding"),
 38: ("Model Training", "gpu1", "GPU to train <=2.2B models"),
 39: ("Unknown", "unknown", ""),
 40: ("Inference Optimisation", "gpu2", "GPU to quantise frontier models"),
 41: ("Forecasting", "capital", "Trading capital or portal credits"),
 42: ("Unknown", "unknown", ""),
 43: ("Optimisation", "cpu", "CPU solver"),
 44: ("Vision & Media", "gpu1", "GPU for sports CV model"),
 45: ("Finance & DeFi", "gpu1", "8-24 GB VRAM, 16-32 GB RAM + OpenRouter"),
 46: ("Inference", "unknown", ""),
 47: ("Model Training", "gpu3", "NVIDIA H100"),
 48: ("Compute", "capital", "5,000 alpha staked on hotkey"),
 49: ("Robotics", "gpu1", "24 GB+ VRAM, Isaac Sim/Lab"),
 50: ("Forecasting", "cpu", "Own forecasting models"),
 51: ("Compute", "gpu2", "Rentable NVIDIA GPUs, 100 Mbps public IP"),
 52: ("Data & Scraping", "none", "Browser wallet"),
 53: ("Inference", "gpu3", "4x RTX 4090 or larger for frontier models"),
 54: ("Security & Alignment", "gpu1", "8 GB+ VRAM, 16-32 GB RAM"),
 55: ("Science", "gpu1", "16 vCPU, 16 GB RAM + GPU"),
 56: ("Model Training", "cpu", "No training compute needed"),
 57: ("Unknown", "unknown", ""),
 58: ("Robotics", "gpu2", "GPU for robot foundation models"),
 59: ("Unknown", "unknown", ""),
 60: ("Security & Alignment", "api", "Chutes/OpenRouter inference key"),
 61: ("Security & Alignment", "cpu", "Docker Hub account"),
 62: ("LLM & Agents", "api", "Inference provider for testing"),
 63: ("Science", "cpu", "1 CPU core, 8 GB RAM"),
 64: ("Compute", "gpu3", "Datacenter GPU servers"),
 65: ("Inference Optimisation", "gpu1", "GPU + HuggingFace write access"),
 66: ("Science", "cpu", "Lean 4 toolchain"),
 67: ("LLM & Agents", "api", "LLM inference budget"),
 68: ("Science", "gpu1", "Own molecule search compute"),
 69: ("Media & Marketing", "none", "Google account + wallet extension"),
 70: ("Unknown", "unknown", ""),
 71: ("LLM & Agents", "api", ""),
 72: ("Vision & Media", "gpu1", "GPU to train CV model"),
 73: ("Unknown", "unknown", ""),
 74: ("Software Dev", "none", "GitHub account + PAT"),
 75: ("Infrastructure", "infra", "Storage capacity (IPFS)"),
 76: ("LLM & Agents", "api", "Confidential VM for protected tier"),
 77: ("Finance & DeFi", "capital", "EVM wallet + liquidity capital"),
 78: ("Vision & Media", "gpu1", "Public IP + valid TLS cert"),
 79: ("Finance & DeFi", "capital", "Trading activity + S3 bucket"),
 80: ("Robotics", "gpu2", "GPU for VLA training"),
 81: ("Model Training", "gpu2", "GPU for GRPO (Qwen3-4B lineage)"),
 82: ("Staking", "capital", "Non-withdrawable stake contribution"),
 83: ("Optimisation", "cpu", "CPU solver"),
 84: ("Unknown", "unknown", ""),
 85: ("Vision & Media", "gpu1", "RTX 4090+ (16 GB+ VRAM)"),
 86: ("Unknown", "unknown", ""),
 87: ("LLM & Agents", "unknown", ""),
 88: ("Finance & DeFi", "cpu", ""),
 89: ("Finance & DeFi", "cpu", ""),
 90: ("Compute", "gpu3", "TEE hardware (Intel TDX, confidential GPUs)"),
 91: ("Model Training", "cpu", "Pays ~4-6 GPU-hours on Lium"),
 92: ("Inference", "gpu1", "GPU to run committed model"),
 93: ("Media & Marketing", "none", "YouTube channel with real engagement"),
 94: ("Compute", "infra", "Attestable TDX CPU hosts"),
 95: ("Inference", "unknown", ""),
 96: ("Inference", "gpu2", "GPU + proof environment"),
 97: ("Inference Optimisation", "gpu1", ""),
 98: ("LLM & Agents", "api", "Minecraft agent + LLM key"),
 99: ("Unknown", "unknown", ""),
 100: ("Science", "cpu", ""),
 101: ("Data & Scraping", "api", "LLM tagger of your choice"),
 102: ("Model Training", "gpu2", "GPU for expert-module training"),
 103: ("Unknown", "unknown", ""),
 104: ("LLM & Agents", "api", "Paid LLM API key"),
 105: ("Infrastructure", "infra", "Bandwidth nodes"),
 106: ("Compute", "gpu2", "Rentable NVIDIA GPU, 4+ cores, 16 GB+ RAM"),
 107: ("Science", "cpu", "4+ cores, 16 GB RAM, 60 GB disk"),
 108: ("Science", "cpu", "Docker or Python 3.12"),
 109: ("Finance & DeFi", "unknown", ""),
 110: ("Inference", "unknown", ""),
 111: ("Science", "api", "8 cores/32 GB + LLM agent backend"),
 112: ("Robotics", "unknown", ""),
 113: ("Unknown", "unknown", ""),
 114: ("LLM & Agents", "api", ""),
 115: ("Vision & Media", "unknown", ""),
 116: ("Science", "unknown", ""),
 117: ("Vision & Media", "api", "Generation-provider credentials"),
 118: ("LLM & Agents", "unknown", ""),
 119: ("Data & Scraping", "cpu", ""),
 120: ("Model Training", "gpu2", "GPU for RL on reasoning"),
 121: ("LLM & Agents", "api", ""),
 122: ("Unknown", "unknown", ""),
 123: ("Finance & DeFi", "cpu", "Own models and data"),
 124: ("Robotics", "gpu1", "Own training compute"),
 125: ("Model Training", "gpu1", "Local experiment compute + eval credits"),
 126: ("Vision & Media", "unknown", ""),
 127: ("Finance & DeFi", "cpu", ""),
 128: ("Compute", "gpu1", "Worker machines (GPU)"),
}

SW = [  # (regex, display name)
    (r"docker", "Docker"), (r"pm2", "PM2"), (r"cuda|nvidia-container", "CUDA"),
    (r"python ?3\.(\d+)", "Python 3.{}"), (r"node(?:\.js)? ?(\d+)", "Node.js {}"),
    (r"ubuntu ?(\d\d\.\d\d)", "Ubuntu {}"), (r"vllm", "vLLM"), (r"sglang", "SGLang"),
    (r"lean ?4", "Lean 4"), (r"isaac (?:sim|lab)", "Isaac Sim/Lab"), (r"kubernetes|rke2", "Kubernetes"),
    (r"hugging ?face|\bhf\b", "HuggingFace"), (r"openrouter", "OpenRouter"), (r"openai", "OpenAI API"),
    (r"chutes", "Chutes API"), (r"pytorch", "PyTorch"), (r"\buv\b", "uv"), (r"sysbox", "Sysbox"), (r"ipfs", "IPFS"),
]

def software(text):
    out = []
    for rx, name in SW:
        ms = re.findall(rx, text, re.I)
        if not ms: continue
        if "{}" in name:
            v = max(ms, key=lambda s: tuple(int(x) for x in s.split(".")))
            name = name.format(v)
        if name not in out: out.append(name)
    return out

def main(profiles, digests=None):
    prof = json.load(open(profiles))
    dig = json.load(open(digests)) if digests else {}
    out = {"tiers": {k: {"label": l, "rent_low": lo, "rent_high": hi, "hardware": h}
                     for k, (l, lo, hi, h) in TIERS.items()}, "subnets": {}}
    for u, (field, tier, gpu) in T.items():
        p = prof.get(str(u), {})
        text = " ".join([p.get("conditions", ""), p.get("miners", ""), dig.get(str(u), "")])
        out["subnets"][str(u)] = {
            "field": field, "tier": tier, "hardware": gpu or TIERS[tier][3],
            "software": ["Bittensor btcli"] + software(text),
            "task": p.get("task", ""), "miner_role": p.get("miners", ""), "conditions": p.get("conditions", ""),
        }
    dst = Path(__file__).resolve().parent.parent / "backend/app/data/knowledge.json"
    json.dump(out, open(dst, "w"), indent=1)
    print("wrote", dst, len(out["subnets"]))

if __name__ == "__main__":
    main(*sys.argv[1:3])
