---
title: Wallets
section: guide
order: 6
icon: wallet
summary: Tracking wallets by public address, staking and sending with your browser wallet, the btcli terminal and subnet runbooks.
---
## AXoR never holds your keys

[Wallets](#wallet) tracks your Bittensor wallets by their **public SS58 address only**. The server checks every address's checksum and refuses anything that looks like a seed phrase or a private key. Transactions are built from the public address and **only your browser wallet extension signs them**.

> [!WARNING]
> Never paste a seed phrase or private key into AXoR, or into any website. AXoR will refuse it, but other sites won't.

## Adding wallets

- **Connect wallet** enables a browser wallet extension (Talisman, SubWallet, Polkadot.js or Bittensor Wallet) and lists its accounts; track one with a click.
- Or add a coldkey address by hand, with optional hotkeys and a note. A coldkey your browser wallet doesn't hold is **watch-only**: you get the `btcli` command instead of a Sign button.

## Balances and actions

The selected account shows its **total** (free and staked, at live τ and USD prices) and the actions **Send**, **Receive** (address and QR code), **Stake**, **Unstake**, **Move** and **Unstake all**.

Each action is a sheet:

1. Pick the subnet and validator (top validators by stake, with take and nominators, or any hotkey), the position, and the amount (25, 50, 75% or Max). A live quote shows what you receive and the price impact.
2. Set the **max slippage** (0.5 to 5%): the swap fails rather than filling worse.
3. **Review** checks it on the server against the chain (free balance, the position, the minimum stake), quotes it and estimates the fee. It also shows the matching `btcli` command.
4. **Confirm** has your browser wallet show and sign the transaction. AXoR submits the signature and waits for the block.

A review is good for 3 minutes before it's quoted again, and a signature for about 25 minutes; each submits once.

## Tabs

| Tab | What it shows |
|---|---|
| **Assets** | TAO and each subnet's alpha, with its share of the wallet |
| **Staking** | Every position, with stake more, unstake and move on the row |
| **Activity** | Transactions signed here, with block, fee and an explorer link |
| **Hotkeys** | Registrations, UIDs and top-paid earnings |
| **Terminal** | The real `btcli`, read-only (below) |
| **Subnet runbook** | The `btcli` commands for any subnet (below) |

## The btcli terminal

The **Terminal** tab runs the real `btcli` on the server in a sandbox that holds your tracked wallets as **public keys only**, so reads work as on your own machine and there's no key to sign with.

- Reads work: `btcli wallet balance -w main`, `btcli stake list`, `btcli wallet overview`, `btcli subnets list`, `btcli subnets show 19`, any `btcli query …` and `--help`.
- `btcli stake add / remove / move / unstake-all` and `btcli wallet transfer` open the wallet's sheet filled in from the command, and your browser wallet signs.
- Other commands that sign or write files are refused with a copy button for your own terminal, as are shell syntax, paths and URLs.

## Subnet runbooks

The **Subnet runbook** (also **Wallet** on a subnet's details) builds the `btcli` commands to create, fund, register, stake and check for a subnet. Pick the hotkey, network (finney or test) and amount, choose the steps, and add your own with `{wallet}`, `{hotkey}`, `{netuid}`, `{network}`, `{amount}`, `{coldkey}` and `{hotkey_ss58}` filled in. Each step shows live status, and register and stake come with a `--dry-run` preview first. Copy it, download it as a `.sh` script, or save it to your notes.

> [!TIP]
> The **eye** button hides your balances on screen, and terminal output stays blurred until you show it.
