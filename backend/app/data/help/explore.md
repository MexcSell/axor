---
title: Explorer, Recommendations and risk
section: guide
order: 2
icon: grid
summary: Reading the subnet table and a subnet's details, how the numbers are worked out, and the risk pages.
---
## The Explorer

[Explorer](#explore) lists every subnet, refreshed from the chain every few minutes; open pages update on their own.

**Columns** include the subnet number and name, task, what miners do, miners (registered / max), earning miners, top and second miner earnings a day, registration cost, what you need (hardware tier and software), emission (τ a day and share), the emission cycle, immunity period, field, links, conditions, rent budget, a 7-day price trend, the created date, UID availability and risk. Choose which show with **Columns**.

**Search and filters:** search name, task, hardware or software (press [[/]] from anywhere), and filter by field, hardware, risk, **UID available** and **Has earners**. **CSV** downloads exactly what's filtered. The filters you've set show as chips under the toolbar: click one to remove it, or **Clear all**.

**Compare:** open a subnet and click **Compare** (or **Compare** on the cards on New, Avoid & Caution and Scam Signals), up to four subnets. A tray at the bottom collects them; **Compare** there puts them side by side, with the best value in each row highlighted: emission, top and median pay, earning miners, top miner's and owner's share, registration cost, UID, hardware, price trend, TAO flow, age, a 7-day emission chart and every flag. The tray remembers your picks in this browser.

## A subnet's details

Click a row (or open `#sn<number>`) for the drawer:

- the task, what miners do, hardware and software, and links
- **payouts:** when the last epoch paid out, a live countdown to the next, alpha and τ paid per epoch and per day, and what has built up for the next payout
- the **top-paid miners** of the last epoch: UID, hotkey and coldkey, alpha and τ per epoch, τ per day, incentive, registration date and immunity
- interactive **7-day charts** of price, registration cost and emission
- **Add to workspace**, **Ask an agent** and **Wallet** (its runbook)

## How the numbers are worked out

- **Miner earnings per day:** each UID's last-epoch emission is split into its miner part (incentive) and validator part (dividends), scaled to epochs per day and converted to TAO at the subnet's alpha price, without the owner's hotkey. Values are averaged over the last 24 hours.
- **UID available:** registration is on, the interval's rate limit isn't hit, and there's an open slot or a UID past its immunity that can be pruned.
- **Trends:** 7 days of price, registration cost, emission and volume, backfilled from an archive node at first start, then sampled on every refresh. History from an earlier subnet on a recycled netuid is ignored.
- **Hardware, software and rent budgets** come from a curated table built from each subnet's README and miner docs. Rent budgets are typical cloud prices for the hardware tier, not quotes.

## Recommendations

[Recommendations](#recommend) ranks subnets for you. Its factors, weights and constraints are explained in [Find a subnet to mine](#help/first-subnet). Each result shows the task, why it's recommended, what miners do, what you need, a **budget** (rent, registration, expected gross and net a month, payback) and **how to become a top miner**, with anything to watch out for.

> [!TIP]
> *Expected gross* is the median earner's pay times the share of miners who earn, not the top miner's pay. It's a realistic figure for a newcomer, not a best case.

## Avoid & Caution and Scam Signals

- [Avoid & Caution](#caution) splits risky subnets into **avoid** (you can't profitably get in now: registration closed, no UID, no emission, dust rewards, slow payback, a price crash) and **caution** (workable, with a specific trap: winner-take-all, a high owner take, few earners, early-stage rules, capital at risk, outflows, very new).
- [Scam Signals](#scam) lists subnets that draw emission while anonymous, abandoned or for sale, or where the owner or a single closed-source hotkey captures almost all miner rewards.

Both pages have a search, a sort (emission, registration cost, top miner pay, most flags or newest) and a chip for each kind of flag with how many subnets carry it: click one to see only those. **What these flags mean** explains each flag's rule, with an example measurement from the current data.

Every flag states the measurement behind it. They're automated signals from chain data and published identity, not a verdict: do your own research.

## New Subnets

[New](#new) shows subnets registered in the last four months, newest first. Early subnets can pay well before competition arrives, but carry more rule-change and deregistration risk.
