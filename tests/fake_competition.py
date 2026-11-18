"""A scripted subnet competition for testing My subnets offline: MINING_CHAIN_FACTORY=fake_competition:factory.

Every metagraph read advances that subnet by one tick (150 blocks, about 30 minutes), so each snapshot differs:
- 64 UIDs: the owner (UID 0), five validators (UIDs 1-5) and 58 miners whose skill drifts with seeded noise.
- An operator coldkey ("swarm") runs six UIDs that share one commitment.
- The leader changes at tick 4: UID 17 overtakes UID 9 with a new commitment.
- YOU_1 (UID 23) climbs a rank or two every tick; YOU_2 (UID 61) registered recently, is immune, earns nothing, and is
  deregistered (replaced by a newcomer) at tick 5 so the Sentinel's alerts fire. Both are under YOU_COLD.
- From tick 2 one or two new registrations replace the lowest non-immune miners each tick.
- SN8 runs two competitions (mechanisms), 35% and 65% of the miners' rewards, each ranking miners by its own skill: YOU_1
  is mid-table in the first and near the top of the second. The metagraph's incentive is the first competition's, its
  emission both together; `read("mechanism_count")`, `read("mechanism_emission_split")` and `query(Incentive, [mech * 4096 +
  netuid])` answer like the SDK's, at the last metagraph's tick.
"""
import hashlib, random, threading
from types import SimpleNamespace as NS

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
RAO = 10**9
U16 = 65535

def ss58(pub, prefix=42):
    raw = bytes([prefix]) + pub
    raw += hashlib.blake2b(b"SS58PRE" + raw, digest_size=64).digest()[:2]
    n, out = int.from_bytes(raw, "big"), ""
    while n: n, r = divmod(n, 58); out = B58[r] + out
    return out

def key(seed): return ss58(hashlib.sha256(seed.encode()).digest())

YOU_1, YOU_2, YOU_COLD = key("you-miner-1"), key("you-miner-2"), key("you-cold")
SWARM = key("swarm-cold")
NAMES = {62: "Ridges", 64: "Chutes", 19: "Inference", 8: "Proprietary Trading"}
BASE_BLOCK, TICK, IMMUNITY, TEMPO = 6_100_000, 150, 5000, 360
STATE, LOCK = {}, threading.Lock()
MECHS = {8: (0.35, 0.65)}  # netuid: each competition's share of the miners' rewards

class Bal:
    def __init__(self, rao): self.rao = int(rao)
    @property
    def tao(self): return self.rao / RAO

def _start(netuid):
    rnd = random.Random(netuid)
    miners = {}
    for uid in range(6, 64):
        cold = SWARM if uid in (30, 31, 32, 33, 34, 35) else key(f"cold-{netuid}-{uid // 2}")
        miners[uid] = {"hk": key(f"hk-{netuid}-{uid}"), "ck": cold, "skill": rnd.uniform(0.05, 1.0), "skill2": rnd.uniform(0.05, 1.0),
                       "reg": BASE_BLOCK - rnd.randint(8000, 300000),
                       "cm": "hf:swarm/agent-v2@9f1c" if cold == SWARM else f"hf:miner{uid}/agent-v{rnd.randint(1, 4)}@{rnd.randrange(16**4):04x}",
                       "cb": BASE_BLOCK - rnd.randint(2000, 60000), "ax": rnd.random() > 0.08}
    miners[9].update(skill=1.6, cm="hf:northstar/agent-v7@a11e", cb=BASE_BLOCK - 61000)
    miners[17].update(skill=1.3, cm="hf:quill/agent-v3@77b0")
    miners[23].update(hk=YOU_1, ck=YOU_COLD, skill=0.55, skill2=1.25, cm="hf:you/miner-v1@c0de", ax=True)
    miners[61].update(hk=YOU_2, ck=YOU_COLD, skill=0.0, reg=BASE_BLOCK - 400, cm="", ax=False)
    return {"tick": 0, "miners": miners, "rnd": random.Random(netuid * 7 + 1), "next_new": 0}

def _advance(s):
    s["tick"] += 1
    t, rnd, m, block = s["tick"], s["rnd"], s["miners"], BASE_BLOCK + s["tick"] * TICK
    for uid, x in m.items():
        if x["hk"] not in (YOU_1, YOU_2): x["skill"] = max(0.02, x["skill"] + rnd.uniform(-0.06, 0.06))
        x.setdefault("skill2", rnd.uniform(0.05, 1.0))
    m[23]["skill"] = 0.55 + 0.09 * t
    if t == 4: m[17].update(skill=1.9, cm="hf:quill/agent-v4@be11", cb=block - 20)
    if t >= 2:
        open_ = sorted((x["skill"], uid) for uid, x in m.items() if block - x["reg"] >= IMMUNITY and x["hk"] != YOU_1)
        out = [61] if t == 5 else [uid for _, uid in open_[:rnd.choice((1, 2))]]
        for uid in out:
            s["next_new"] += 1
            n = s["next_new"]
            m[uid] = {"hk": key(f"new-{n}"), "ck": key(f"newcold-{n}"), "skill": rnd.uniform(0.2, 0.9), "skill2": rnd.uniform(0.2, 0.9), "reg": block - rnd.randint(10, 140),
                      "cm": f"hf:fresh{n}/agent-v1@{n:04x}", "cb": block - 5, "ax": True}
    return block

def _metagraph(netuid):
    with LOCK:
        s = STATE.setdefault(netuid, _start(netuid))
        block = _advance(s)
        m = s["miners"]
        owner, vals = key(f"owner-{netuid}"), [key(f"val-{netuid}-{i}") for i in range(1, 6)]
        hot = {uid: (x["skill"] ** 3 if block - x["reg"] > 300 else 0.0) for uid, x in m.items()}  # newcomers earn after a while
        total = sum(hot.values()) or 1
        shares = MECHS.get(netuid, (1.0,))
        hot2 = {uid: (x["skill2"] ** 3 if block - x["reg"] > 300 else 0.0) for uid, x in m.items()}
        total2 = sum(hot2.values()) or 1
        s["incs"] = [[0] * 6 + [int(hot[u] / total * U16) for u in sorted(m)], [0] * 6 + [int(hot2[u] / total2 * U16) for u in sorted(m)]][:len(shares)]
        pool = 4.5e11  # miner alpha (rao) per epoch, before the owner's burn
        price = 0.041
        neurons, raw = [], {k: [] for k in ("emission", "incentives", "dividends", "hotkeys", "coldkeys", "block_at_registration")}
        def add(uid, hk, ck, inc, div, em, vp, reg, stake, ax, cm=None, cb=0, trust=0.0, cons=0.0, prune=0.0):
            neurons.append(NS(uid=uid, hotkey=hk, coldkey=ck, active=True, validator_permit=vp, last_update=block - (5 if vp else 900),
                              block_at_registration=reg, rank=inc, trust=trust, consensus=cons, incentive=inc, dividends=div,
                              pruning_score=prune, emission=Bal(em), alpha_stake=Bal(stake * RAO), tao_stake=Bal(0), total_stake=Bal(stake * RAO),
                              axon=f"203.0.113.{uid}:8091" if ax else None, identity=None,
                              commitment=NS(value=cm, is_revealed=True, block=cb) if cm else None))
            raw["emission"].append(int(em)); raw["incentives"].append(int(inc * U16)); raw["dividends"].append(int(div * U16))
            raw["hotkeys"].append(hk); raw["coldkeys"].append(ck); raw["block_at_registration"].append(reg)
        add(0, owner, key(f"ownercold-{netuid}"), 0.0, 0.0, pool * 0.12, False, BASE_BLOCK - 900000, 1000, False)
        for i, hk in enumerate(vals, 1):
            add(i, hk, key(f"valcold-{netuid}-{i}"), 0.0, 0.2, 9e10, True, BASE_BLOCK - 800000, 250000 - i * 30000, True, trust=1.0, cons=1.0)
        for uid in sorted(m):
            x = m[uid]
            inc = hot[uid] / total
            em = pool * 0.88 * (inc if len(shares) == 1 else shares[0] * inc + shares[1] * hot2[uid] / total2)
            add(uid, x["hk"], x["ck"], inc, 0.0, em, False, x["reg"], 50 + inc * 4000, x["ax"], x["cm"], x["cb"],
                trust=min(1.0, 0.6 + inc * 6) if inc else 0.0, cons=min(1.0, inc * 9), prune=inc)
        raw.update(tempo=TEMPO, immunity_period=IMMUNITY, burn=int(0.42 * RAO * (0.7 if s["tick"] >= 6 else 1)), max_uids=64, num_uids=64,
                   registration_allowed=True, owner_hotkey=owner, alpha_in=int(1e15), tao_in=int(price * 1e15), network_registered_at=BASE_BLOCK - 900000,
                   target_regs_per_interval=1, blocks_since_last_step=40, last_step=block - 40)
        return NS(netuid=netuid, name=NAMES.get(netuid, f"SN{netuid}"), block=block, tempo=TEMPO, owner_hotkey=owner, num_uids=64, max_uids=64,
                  price=price, neurons=neurons, raw=raw)

class Subnets:
    def metagraph(self, netuid, block=None, commitments=True):
        return _metagraph(netuid)

class FakeChain:
    def __init__(self, network):
        self.network, self.subnets = network, Subnets()

    def at(self, block=None):
        return self

    def read(self, name, netuid=None, **_):
        if name == "mechanism_count": return len(MECHS.get(netuid, (1.0,)))
        if name == "mechanism_emission_split": return [int(x * U16) for x in MECHS[netuid]] if netuid in MECHS else []
        raise KeyError(name)

    def query(self, item, params=None):
        """Only the Incentive vector per mechanism (storage index mech * 4096 + netuid), at the last metagraph's tick."""
        idx = int(params[0])
        netuid, mech = idx % 4096, idx // 4096
        with LOCK:
            s = STATE.get(netuid)
            return list(s["incs"][mech]) if s and mech < len(s.get("incs", [])) else []

    @property
    def block(self):
        with LOCK: return BASE_BLOCK + max([s["tick"] for s in STATE.values()] or [0]) * TICK

def factory(network):
    return FakeChain(network)
