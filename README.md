# Commander Doctor

Commander Doctor helps you build and improve *Magic: The Gathering* Commander decks with an AI assistant that checks its own work against real card data and real rules — instead of just guessing.

## What it actually does

When you ask your AI assistant to review a deck with Commander Doctor, it:

- Checks the deck is actually legal — right size, right colors, no banned or miscounted cards.
- Looks for real gaps: not enough answers to a particular kind of threat, a mana base that's thinner than it looks, missing removal for the specific things your deck struggles against.
- Suggests real replacement cards, backed by their actual printed rules text — not a vague "this feels weak."
- Can prefer an available nonland spare when it does the same job nearly as well; lands are excluded from the spare preference and chosen only for mana-base quality.
- Tells you plainly when it doesn't know something, instead of making something up to sound confident.

It's a very well-informed second pair of eyes on your deck — one that never gets tired of re-reading rules text before it says something. It won't quietly rebuild your whole deck on its own; changes are things it proposes and explains, for you to say yes or no to.

## Using it

Open this folder in **Codex or Claude Code**, and just ask something like:

> "Can you review my deck at decks/mydeck.txt?"

or

> "Why does my deck keep losing before it gets going?"

The assistant uses the built-in deck-doctor skill automatically — you don't need to name it.

To invoke it explicitly in **Codex**, type:

```text
$deck-doctor Review my deck at decks/mydeck.txt
```

Codex loads the repository skill from `.agents/skills/deck-doctor/`. If it doesn't appear in the skill picker, restart Codex with this folder open. No global skill installation is needed.

For a dedicated Codex subagent, ask:

> Use the deck-doctor agent to review my deck at decks/mydeck.txt.

The project agent is defined in `.codex/agents/deck-doctor.toml` and uses the same skill and shared workflow. This option requires a Codex version with custom agent support; the skill can also run directly in the main conversation.

In **Claude Code**, explicitly invoke `/deck-doctor Review my deck at decks/mydeck.txt`. Its entry point remains `.claude/skills/deck-doctor/`.

These entry points follow the [Codex skill](https://learn.chatgpt.com/docs/build-skills) and [custom agent](https://learn.chatgpt.com/docs/agent-configuration/subagents) conventions.

## First time opening this project?

If nothing has been set up yet (no local card database, dependencies not installed), just tell your assistant:

> "Set this project up — see SETUP.md"

and it will handle the rest. [SETUP.md](SETUP.md) is written for the assistant to follow, not for you to read.

## Curious how it works under the hood?

The technical documentation — the exact commands, the review process the assistant follows, the internal design — lives in [docs/](docs/) and [SPEC.md](SPEC.md). It's written for developers and AI agents; nothing in there is required reading just to use the tool.
