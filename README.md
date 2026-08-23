# Novin

Local terminal for Novin. It runs **on your machine**. It is not a website.

## Install

In your own terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/oherbert346-create/novin-cli/main/install.sh | sh
```

That puts `novin` on this computer only (`~/.local/bin/novin`). It does not start a server.

If `novin` is not found, add this to your shell profile and open a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Run

```bash
novin
```

- First time: paste the **master key** Novin gave you.
- After that: paste the **API key** for your brand.

A new install always gets the current terminal. If you already have it, it stays as-is until you update.

## Update

```bash
novin update
```

API changes on Novin do not require this. Use it when we ship a new terminal.

## What this is

The terminal lets you manage **sites**, **delivery** (where alerts go), and **incidents**. It talks to the Novin API over HTTPS. Vision and storage stay on Novin.

This repository is the terminal only.

## Uninstall

```bash
rm -f "$HOME/.local/bin/novin"
rm -rf "$HOME/.novin"
```
