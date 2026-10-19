"""
Bank Branch Discrete-Event Simulation (SimPy)
Modeling & Simulation mini-project -- validation model for the AnyLogic version.

System: a bank branch open 6 hours. Customers arrive (Poisson), take a ticket,
wait in ONE queue for the next free teller. If the queue is too long they leave
(balking). Scenario 2 adds an ATM that cash-withdrawal customers use instead.

Run:  pip install simpy numpy matplotlib  &&  python bank_sim.py
"""
import random
import statistics as st
import csv

import simpy
import numpy as np

# ---------------- Parameters (same values go into AnyLogic) ----------------
OPEN_MIN = 6 * 60            # doors open 6 h; customers inside are still served
ARRIVAL_RATE_PER_HR = 40     # Poisson arrivals -> exponential inter-arrival, mean 1.5 min
TELLER_SVC = (2, 3.5, 7)     # triangular(min, mode, max) minutes, mean = 4.17
ATM_SVC = (1, 1.5, 3)        # triangular minutes, mean = 1.83
P_WITHDRAWAL = 0.35          # share of customers who only need cash withdrawal
BALK_LIMIT = 12              # customer leaves if teller queue already has >= 12 people
REPS = 30                    # independent replications per scenario
SEED = 2026

SCENARIOS = {
    "Baseline: 3 tellers":       dict(tellers=3, atm=False),
    "S1: 4 tellers":             dict(tellers=4, atm=False),
    "S2: 3 tellers + 1 ATM":     dict(tellers=3, atm=True),
    "S3: 2 tellers + 1 ATM":     dict(tellers=2, atm=True),
}


def tri(p):
    return random.triangular(p[0], p[2], p[1])  # python order: low, high, mode


def run_once(tellers, atm, seed):
    random.seed(seed)
    env = simpy.Environment()
    teller_res = simpy.Resource(env, capacity=tellers)
    atm_res = simpy.Resource(env, capacity=1) if atm else None

    waits_teller, waits_atm = [], []
    stats = dict(arrived=0, served=0, balked=0, busy_teller=0.0, busy_atm=0.0)
    q_samples = []

    def customer(env):
        stats["arrived"] += 1
        use_atm = atm and random.random() < P_WITHDRAWAL
        if use_atm:
            t0 = env.now
            with atm_res.request() as req:
                yield req
                waits_atm.append(env.now - t0)
                s = tri(ATM_SVC)
                stats["busy_atm"] += s
                yield env.timeout(s)
            stats["served"] += 1
            return
        if len(teller_res.queue) >= BALK_LIMIT:
            stats["balked"] += 1
            return
        t0 = env.now
        with teller_res.request() as req:
            yield req
            waits_teller.append(env.now - t0)
            s = tri(TELLER_SVC)
            stats["busy_teller"] += s
            yield env.timeout(s)
        stats["served"] += 1

    def source(env):
        while env.now < OPEN_MIN:
            yield env.timeout(random.expovariate(ARRIVAL_RATE_PER_HR / 60))
            if env.now < OPEN_MIN:
                env.process(customer(env))

    def monitor(env):
        while env.now < OPEN_MIN:
            q_samples.append(len(teller_res.queue))
            yield env.timeout(1)

    env.process(source(env))
    env.process(monitor(env))
    env.run()  # runs until everyone inside has been served
    end = max(env.now, OPEN_MIN)

    all_waits = waits_teller + waits_atm
    return dict(
        avg_wait=st.mean(all_waits) if all_waits else 0,
        avg_wait_teller=st.mean(waits_teller) if waits_teller else 0,
        p_wait_over_10=sum(w > 10 for w in all_waits) / max(len(all_waits), 1),
        max_wait=max(all_waits) if all_waits else 0,
        avg_queue=st.mean(q_samples),
        max_queue=max(q_samples),
        balk_pct=100 * stats["balked"] / stats["arrived"],
        teller_util=100 * stats["busy_teller"] / (tellers * end),
        atm_util=(100 * stats["busy_atm"] / end) if atm else None,
        served=stats["served"],
        overtime=max(0, env.now - OPEN_MIN),
    )


def ci95(xs):
    m = st.mean(xs)
    h = 2.045 * st.stdev(xs) / len(xs) ** 0.5  # t(0.975, 29)
    return m, h


def main():
    rows = []
    summary = {}
    for name, cfg in SCENARIOS.items():
        res = [run_once(cfg["tellers"], cfg["atm"], SEED + r) for r in range(REPS)]
        summary[name] = res
        print(f"\n=== {name} ({REPS} replications, 95% CI) ===")
        for k in ["avg_wait", "avg_wait_teller", "p_wait_over_10", "max_wait", "avg_queue",
                  "max_queue", "balk_pct", "teller_util", "atm_util", "served", "overtime"]:
            vals = [r[k] for r in res if r[k] is not None]
            if not vals:
                continue
            if k == "p_wait_over_10":
                vals = [100 * v for v in vals]
            m, h = ci95(vals)
            print(f"  {k:16s} {m:8.2f} ± {h:.2f}")
            rows.append([name, k, round(m, 2), round(h, 2)])

    with open("results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "metric", "mean", "ci95_halfwidth"])
        w.writerows(rows)

    # Theory check for baseline: offered load
    lam = ARRIVAL_RATE_PER_HR / 60
    mean_s = sum(TELLER_SVC) / 3
    print(f"\nTheory: baseline rho = lam*E[S]/c = {lam*mean_s/3:.3f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        names = list(SCENARIOS)
        short = ["Baseline\n3 tellers", "4 tellers", "3 tellers\n+ ATM", "2 tellers\n+ ATM"]
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        for ax, key, title in zip(axes, ["avg_wait", "teller_util", "balk_pct"],
                                  ["Avg wait (min)", "Teller utilization (%)", "Customers lost (%)"]):
            ms, hs = zip(*[ci95([r[key] for r in summary[n]]) for n in names])
            ax.bar(short, ms, yerr=hs, capsize=4, color=["#c0504d", "#4f81bd", "#9bbb59", "#f79646"])
            ax.set_title(title)
        fig.suptitle("Bank branch: scenario comparison (30 replications, 95% CI)")
        fig.tight_layout()
        fig.savefig("scenario_comparison.png", dpi=150)
        print("Saved scenario_comparison.png")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
