---
title: Find a subnet to mine
section: start
order: 3
icon: target
summary: From a first look at the Explorer to a shortlisted subnet with a budget and a plan.
---
This walk-through takes you from "where should I mine?" to a subnet in your workspace with a budget, a plan and the commands to register.

## 1. Survey the field

Open the [Explorer](#explore). Every subnet is one row with live chain data: miners registered and earning, what the top and second miners earn per day, registration cost, emission, hardware tier, 7-day price trend, UID availability and risk.

- **Filter** by field, hardware and risk, and tick **UID available** to see only subnets you can register on now.
- **Sort** by any column; **Columns** chooses what shows; **CSV** downloads the filtered table.
- **Click a row** for the subnet's details: its task, what miners do, payouts (when the last epoch paid, a countdown to the next), the top-paid miners and interactive 7-day charts.

## 2. Get a ranking for you

Open [Recommendations](#recommend) and describe your situation, or start from a preset (*Beginner, low budget*, *Have a gaming GPU*, *Max profit, datacenter*, *Developer, no GPU*).

- **Your setup:** the hardware you have or will rent (and whether you already own it), a monthly budget, TAO available for registration, your fields and your risk tolerance.
- **What matters to you:** weights for the six factors below.
- **Constraints:** only subnets with a UID available, hide avoid and scam-signal subnets, hide winner-take-all subnets, a minimum age.

The list re-ranks as you change anything and always shows at least five subnets.

| Factor | What it measures |
|---|---|
| **Profit** | Expected net USD a month: the median earner's pay × the share of miners who earn, minus rent and registration |
| **Accessibility** | Fit with your hardware, budget and TAO, plus an open UID |
| **Fair competition** | How widely rewards are spread across miners |
| **Stability** | Age, emission share, owner take and public code |
| **Momentum** | The 7-day price change and net TAO flow |
| **Skill fit** | How well the subnet matches the fields you picked |

Factors are ranked against every other subnet, combined with your weights, then reduced by penalties for risk flags (scaled by your risk tolerance), hardware you can't afford and negative expected profit.

## 3. Check the risks

- [Avoid & Caution](#caution): *avoid* means you can't profitably get in right now (registration closed, no UID, no emission, dust rewards, slow payback, a price crash). *Caution* means workable but with a specific trap, such as winner-take-all, a high owner take, few earners or very new rules.
- [Scam Signals](#scam): subnets that draw emission while anonymous, abandoned or for sale, or where the owner or one closed-source hotkey captures almost all miner rewards. These are automated red flags, not verdicts: read the evidence.

## 4. Shortlist it and read the brief

Add the subnet to **My workspace** (the button on its details or its recommendation card). Its **mining brief** covers:

- the task and what you'd do as a miner
- a budget: hardware rent, inference or API spend, registration, running cost, first-month total, realistic newcomer earnings, net a month and break-even, adjustable for hardware you own
- how to keep costs low, and how to become a top miner, with score targets from the current leaderboard
- the competition: earners, reward concentration, operators and newcomers in the top 15, registration pressure

The brief's **News** tab shows the subnet's GitHub releases and on-chain changes. See [Workspace and the project team](#help/workspace).

## 5. Get the commands

Open **Wallets** and its **Subnet runbook** (or **Wallet** on the subnet's details). It builds the `btcli` commands to create, fund, register, stake and check, with your wallet, hotkey and amounts filled in and a `--dry-run` preview before anything that spends. See [Wallets](#help/wallets).

> [!TIP]
> Ask an agent. **Ask an agent** on a subnet's details opens a chat about that subnet in your workspace, and the project team can plan and run the work with you.
