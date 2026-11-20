# Gauntlet Core

Motor genérico de ciclos executor → checks → revisor → gate. Os critérios de qualidade vêm de um
contrato JSON da própria tarefa, então o mesmo motor serve para texto, código, documento ou deck.

Diferente da skill pública `gauntlet-loop`, que só escreve um prompt, esta executa o ciclo com
gates determinísticos, diário idempotente e veredito `approved`/`blocked`.

## Como funciona

1. A tarefa declara seus critérios num contrato JSON (`gate` 1–10 por critério, `blocking`
   opcional, `checks` opcionais).
2. O executor escreve o artefato numa chamada isolada.
3. O motor roda os checks determinísticos.
4. Um revisor diferente, com contexto novo, devolve JSON estruturado.
5. O gate aprova, pede novo ciclo com feedback, ou bloqueia. No máximo 5 ciclos.
6. `approved` sai com `human_signoff: "pending"`: o QA humano continua sendo seu.

## Instalação

### Via `npx skills`

    npx skills add <owner>/skill-gauntlet-core@gauntlet-core -g -y

Troque `<owner>` pelo dono do repositório. Sem `-g`, instala no projeto atual.

### Manual, global

| Harness | Destino |
|---|---|
| agents | `~/.agents/skills/gauntlet-core` |
| Claude Code | `~/.claude/skills/gauntlet-core` |
| Codex | `~/.codex/skills/gauntlet-core` |
| OpenCode | `~/.config/opencode/skills/gauntlet-core` |
| Hermes | `~/.hermes/skills/gauntlet-core` |
| OpenClaw | `~/.openclaw/skills/gauntlet-core` |

### Manual, por projeto

| Harness | Destino |
|---|---|
| agents | `<projeto>/.agents/skills/gauntlet-core` |
| Claude Code | `<projeto>/.claude/skills/gauntlet-core` |
| Codex | `<projeto>/.codex/skills/gauntlet-core` |
| OpenCode | `<projeto>/.opencode/skills/gauntlet-core` |
| Hermes | `<projeto>/.hermes/skills/gauntlet-core` |
| OpenClaw | `<projeto>/.openclaw/skills/gauntlet-core` |

Copie o diretório inteiro: `SKILL.md`, `gauntlet_core.py`, `contracts/` e `examples/`. Cópia por
symlink não funciona com `npx skills add`.

Para Claude Code a partir de `~/.agents`, a skill `migrate-agent-skills` sincroniza via symlink:

    migrate-skills sync-to-claude --source agents

## Uso

    from gauntlet_core import load_contract, run_gauntlet
    contrato = load_contract("contracts/contrato-codigo.json")
    resultado = run_gauntlet(executor, revisor, contrato, workspace_root=".")

Ou conduza ciclo a ciclo com `record_cycle`, quando o agente faz as chamadas `task`.

## Desenvolvimento

    pytest -q
    bash scripts/build-harness-copies.sh
    pytest tests/test_harness_copies.py -q

As cópias em `agents/`, `.claude/` e `opencode/` são geradas; teste garante que não divergem.

## Licença

MIT.
