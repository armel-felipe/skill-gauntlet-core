# Gauntlet Core — Design

Data: 2026-11-20
Status: aprovado para implementação

## Problema

O motor atual (`conteudo_linkedin/gauntlet_loop.py`, 679 linhas) prova que o padrão funciona:
executor isolado, checks determinísticos, revisor separado, gates numéricos, teto de ciclos,
persistência auditável e `blocked` fail-closed. Mas ele só serve ao pipeline editorial:
os 14 critérios são constantes no código, `review_scope` é editorial, `validate_editorial_evidence`
conhece o domínio, e os caminhos são `runs/<run_id>/topics/<topic>/`.

A skill pública `robonuggets/gauntlet-loop` resolve outro problema: gera um prompt com um "bar"
(referência real para comparação cega A/B) e não executa nada. Não há gate, não há persistência,
não há auditoria.

Falta o meio: um motor genérico que receba os critérios de aprovação da tarefa como contrato e
execute o ciclo com os mesmos garantimos de determinismo e fail-closed.

## Objetivo

`gauntlet-core`: skill global + motor Python que roda o ciclo gauntlet para qualquer contrato de
produção, capturando os critérios de qualidade da própria tarefa em vez de fixá-los no código.

## Não-objetivos

- Não gera o "bar" da skill pública. Comparação com referência externa pode ser descrita dentro
  da descrição de um critério; não é um tipo de critério nesta versão.
- Não aprova trabalho no lugar do humano. O QA humano continua sendo ação separada.
- Não substitui `qa-draft` nem publica nada.
- Não oferece CLI. Quem chama é o agente ou um script do projeto.
- Não suporta YAML no contrato nem no diário.
- Não executa sexto ciclo, em nenhuma configuração.

## Decisões

| # | Decisão | Escolha |
|---|---|---|
| 1 | Origem dos critérios | Vem do contrato da tarefa; o motor não infere nem inventa |
| 2 | Formato do contrato | JSON apenas (stdlib, sem dependência) |
| 3 | Formato do diário | JSON de verdade: `cycle-NN.json`, `events.json`, `state.json` |
| 4 | Gate por critério | Nota 0–10 com gate mínimo por critério |
| 5 | Critérios não bloqueantes | `blocking: false` — aparecem no review, nunca geram retry |
| 6 | Régua | Configurável com faixas duras: gate 1–10, coverage 0.5–1.0, ciclos 1–5 |
| 7 | Checks determinísticos | Estruturais embutidos + `checks` opcionais (comando, exit 0 obrigatório) |
| 8 | Entrega | `SKILL.md` + `gauntlet_core.py` (sem CLI) |
| 9 | Instalação | Global em `~/.agents/skills/gauntlet-core` e repo GitHub publicável |
| 10 | Nome | `gauntlet-core`; repositório `skill-gauntlet-core` |
| 11 | Licença | MIT |
| 12 | Local de desenvolvimento | `~/llm server/projetos/skill-gauntlet-core` |

## Contrato

Arquivo JSON, versionado junto da tarefa, validado antes de qualquer ciclo.

```json
{
  "name": "correcao-post",
  "goal": "Reescrever o draft corrigindo as falhas apontadas, preservando a voz do autor.",
  "artifact": "content/drafts/post-2026-11-20.md",
  "criteria": [
    {"name": "clareza", "description": "Cada parágrafo tem uma ideia principal identificável.", "gate": 9},
    {"name": "voz_do_autor", "description": "Comparado a memory/writing_style.md, não soa genérico.", "gate": 9},
    {"name": "ritmo", "description": "Observações de cadência, sem bloquear.", "gate": 7, "blocking": false}
  ],
  "coverage_gate": 0.99,
  "max_cycles": 5,
  "checks": [
    {"name": "sem-placeholder", "run": "! grep -n 'TODO\\|TBD' content/drafts/post-2026-11-20.md", "timeout_s": 15}
  ],
  "persistence_dir": "runs/2026-11-20-correcao",
  "run_id": "2026-11-20-correcao"
}
```

### Regras de validação do contrato

Campos obrigatórios: `name`, `goal`, `artifact`, `criteria`. Opcionais: `coverage_gate`,
`max_cycles`, `checks`, `persistence_dir`, `run_id`.

- `artifact` precisa ser caminho relativo ao workspace; absoluto, vazio, `..` para fora do
  workspace ou symlink são erro de contrato.
- `criteria` é lista não vazia; `name` único, não vazio, sem espaços nas pontas.
- `gate` é inteiro de 1 a 10; ausente = 9. Booleano, float ou fora da faixa = erro.
- `blocking` é booleano; ausente = `true`. É obrigatório ao menos um critério bloqueante.
- `coverage_gate` é número finito de 0.5 a 1.0; ausente = 0.99.
- `max_cycles` é inteiro de 1 a 5; ausente = 5.
- `checks` é lista; cada item tem `name` e `run` (string não vazia), com `timeout_s` opcional
  inteiro de 1 a 600 (ausente = 60).
- `persistence_dir` é relativo ao workspace; ausente = nenhuma escrita em disco.
- `run_id` é string não vazia, um único componente de caminho seguro (não `..`, sem `/` ou `\`,
  sem drive); ausente = `run`.
- `artifact` e `persistence_dir` não podem ser drive-relative nem rooted (ex.: `D:artifact.md`,
  `\artifact.md`).
- Qualquer campo desconhecido no contrato ou nos critérios é erro estrutural. Nada é ignorado.

## Review

O revisor devolve JSON estrito:

```json
{
  "decision": "feedback",
  "coverage": 0.93,
  "criteria": {"clareza": 9, "voz_do_autor": 8, "ritmo": 7},
  "hard_failures": [],
  "feedback": [
    {"criterion": "voz_do_autor", "kind": "required_fix", "fix": "Reescrever o 3º parágrafo."}
  ],
  "coverage_gaps": ["voz_do_autor"],
  "artifact": "content/drafts/post-2026-11-20.md"
}
```

### Regras de validação do review

- Raiz precisa ser objeto JSON. Array, string, número, `null` ou texto extra = falha terminal.
- Campos obrigatórios: `decision`, `coverage`, `criteria`, `hard_failures`, `feedback`, `artifact`.
  `coverage_gaps` é opcional. Campo desconhecido = falha estrutural.
- `decision` ∈ {`approved`, `feedback`}.
- `coverage` é número finito entre 0 e 1 inclusive; `NaN`, `Infinity`, string e booleano são erro.
- `criteria` precisa conter exatamente os nomes do contrato, com inteiros 0–10. Omitido, extra,
  renomeado, float ou booleano = falha estrutural.
- `hard_failures` e `feedback` são listas, mesmo vazias.
- Cada item de `feedback` tem `criterion` (existente entre os critérios do contrato), `kind`
  ∈ {`required_fix`, `optional_suggestion`} (ausente = `required_fix`) e `fix` (string não vazia).
- `coverage_gaps` é lista de nomes de critérios do contrato.
- `artifact` é string não vazia e igual ao `artifact` do contrato.

## Gates

Avaliados nesta ordem; o primeiro que dispara decide.

| Condição | Resultado |
|---|---|
| Contrato inválido | `blocked` antes do ciclo 1 |
| Review estruturalmente inválido, truncado ou divergente | `blocked` |
| `hard_failures` não vazio | `blocked` |
| Artefato ausente, vazio, symlink, fora do caminho ou não verificável | `blocked` |
| `checks` com exit ≠ 0, timeout ou comando inexistente | `blocked` |
| Critério bloqueante abaixo do gate sem `required_fix` correspondente | `blocked` |
| `coverage < coverage_gate` sem `required_fix` ligado a um item de `coverage_gaps` | `blocked` |
| Erro de persistência do review | `blocked` |
| Falha de qualidade com feedback completo | `retry` |
| `decision: feedback` com feedback acionável | `retry` |
| Ciclo igual a `max_cycles` sem passar | `blocked` |
| Tudo passou | `approved` |

Critério `blocking: false` nunca bloqueia nem gera retry; entra no review e no feedback como
diagnóstico.

O agente deve validar o contrato antes do ciclo 1; contrato inválido é reportado como
`blocked` (ciclo 0), nunca como execução.

## Máquina de estados

```
validate contract
      │ inválido → blocked
      ▼
cycle N (N = 1..max_cycles)
  cycle-start
  → executor(feedback)            # task isolada, contexto novo
  → deterministic-checks          # estruturais + checks do contrato
  → reviewer(artifact, feedback)  # task isolada, diferente do executor
  → validate review
  → gate                          # approved | retry | blocked
      │
      ├─ retry  → cycle N+1 com o feedback completo
      └─ blocked/approved → state.json terminal
```

O executor não recebe o review anterior; recebe apenas a lista `feedback` do ciclo anterior.
O revisor não recebe o histórico do executor. As duas chamadas são `task` novas.

## Saídas terminais

```json
{
  "status": "approved",
  "cycle_count": 2,
  "last_artifact": "content/drafts/post-2026-11-20.md",
  "artifact_fingerprint": "sha256:...",
  "human_signoff": "pending",
  "last_review": {"...": "..."}
}
```

```json
{
  "status": "blocked",
  "cycle_count": 5,
  "failure_reasons": ["quality gates not met"],
  "failed_criteria": ["voz_do_autor"],
  "last_artifact": "content/drafts/post-2026-11-20.md",
  "last_review": {"...": "..."},
  "feedback": []
}
```

`approved` sempre sai com `human_signoff: "pending"`. O motor nunca declara a tarefa aprovada
para o humano; declara pronta para QA.

## Persistência

Quando `persistence_dir` existe no contrato, o diário é namespaceado por `run_id`:

```
<root>/<persistence_dir>/<run_id>/
├── cycle-01.json … cycle-05.json
├── events.json
└── state.json
```

Um `run_id` novo grava um diário novo sob o mesmo `persistence_dir`; aprovado nunca é
re-executado no mesmo `run_id`.

- Escrita atômica (tmp no mesmo diretório + `os.replace`).
- Chave de idempotência: `(run_id, artifact, cycle)`. Repetir o mesmo ciclo com o mesmo conteúdo
  é no-op; com conteúdo diferente é erro.
- `events.json` registra, por ciclo, `cycle-start`, `deterministic-checks` e `review`, nessa ordem.
- `state.json` só é escrito no terminal, e uma vez. Diário já terminal rejeita novo ciclo.
- Bloqueio de preflight (artefato ausente ou check falhando antes do revisor) é terminal e não tem
  revisor: o último ciclo registra só dois eventos (`cycle-start`, `deterministic-checks`), sem
  `cycle-NN.json`, e um `state.json` `blocked`.
- Retomada só é permitida com journal íntegro de `cycle-01` até `cycle-(N-1)`: exatamente
  `N-1` reviews e `3 × (N-1)` eventos. Qualquer lacuna, review inválido ou symlink no diretório
  é erro, nunca reconstrução.
- `approved` nunca é re-executado. Revisão de trabalho aprovado exige `run_id` novo.

## API

`gauntlet_core.py`, apenas stdlib (Python 3.9+):

```python
load_contract(path) -> dict
validate_contract(contract) -> dict
validate_review(review, contract) -> dict
run_checks(contract, workspace_root) -> list
evaluate_cycle(review, *, contract, cycle, workspace_root) -> dict
record_cycle(review, *, contract, cycle, workspace_root) -> dict
run_gauntlet(executor, reviewer, contract, workspace_root=None) -> dict
```

- `validate_*` retornam `{"valid": bool, "errors": [...], ...}` sem levantar exceção para entrada
  do usuário.
- `evaluate_cycle` é puro: não escreve nada.
- `record_cycle` valida, roda os checks e persiste o ciclo; é o ponto de entrada quando o agente
  conduz os ciclos com `task`.
- `run_gauntlet` conduz os ciclos chamando os callbacks `executor(feedback) -> None` (escreve o
  artefato no caminho do contrato) e `reviewer(artifact, feedback) -> dict` (devolve o review).
  Cada callback recebe cópia profunda do contexto e nenhum estado atravessa ciclos.
- `run_checks` retorna `[{"name", "status": "pass"|"fail"|"error", "exit_code", "output"}]`.
- Erro de uso (ciclo fora de faixa, diário inconsistente) levanta `ValueError`; erro de qualidade
  é resultado, não exceção.

## SKILL.md

Duas camadas, em português:

1. **Contrato** — como capturar os critérios de qualidade da tarefa: perguntas objetivas
   (o que reprova sem discussão? o que é "bom" aqui? qual o piso numérico? o que é diagnóstico?),
   como escrever o JSON, exemplos editorial e código, erros comuns (critério vago, gate frouxo,
   artefato absoluto, feedback sem `fix`). Regra dura: nunca inventar critério que a tarefa não
   declarou; se a tarefa não tem critério, a resposta é "não dá para rodar o gauntlet", não um
   default.
2. **Protocolo** — quando usar e quando não usar; chamadas `task` isoladas para executor e
   revisor; uso do motor quando houver Python; modo sem Python (checklist manual com o mesmo
   veredito, marcado `verified_by: "agent"` em vez de `"motor"`); encerramento obrigatório em
   `human_signoff: "pending"` com a frase "pronto para seu QA".

## Repositório

```
skill-gauntlet-core/
├── SKILL.md
├── README.md
├── LICENSE
├── gauntlet_core.py
├── contracts/
│   ├── contrato-editorial.json
│   └── contrato-codigo.json
├── examples/
│   └── diario-exemplo/{cycle-01.json,events.json,state.json}
├── tests/
│   └── test_gauntlet_core.py
├── scripts/
│   └── build-harness-copies.sh
├── agents/skills/gauntlet-core/     {SKILL.md, gauntlet_core.py, contracts/, examples/}
├── .claude/skills/gauntlet-core/    {…}
└── opencode/skills/gauntlet-core/   {…}
```

Cada diretório de harness é auto-contido: `npx skills add` copia apenas o diretório da skill,
então cópia por symlink ou caminho `../../` não funciona. `build-harness-copies.sh` gera as
cópias a partir do canônico; um teste falha se alguma cópia divergir byte a byte.

## Distribuição

`README.md` cobre instalação global e por projeto:

| Harness | Global | Projeto |
|---|---|---|
| agents | `~/.agents/skills/gauntlet-core` | `.agents/skills/gauntlet-core` |
| Claude Code | `~/.claude/skills/gauntlet-core` | `.claude/skills/gauntlet-core` |
| Codex | `~/.codex/skills/gauntlet-core` | `.codex/skills/gauntlet-core` |
| OpenCode | `~/.config/opencode/skills/gauntlet-core` | `.opencode/skills/gauntlet-core` |
| Hermes | `~/.hermes/skills/gauntlet-core` | `.hermes/skills/gauntlet-core` |
| OpenClaw | `~/.openclaw/skills/gauntlet-core` | `.openclaw/skills/gauntlet-core` |

E `npx skills add <owner>/skill-gauntlet-core@gauntlet-core -g -y`.

Repositório `skill-gauntlet-core`, público, com prefixo exigido pela skill de publicação.

## Testes

`pytest`, com estes casos mínimos:

1. Contrato válido com defaults aplicados.
2. Contrato inválido: artefato absoluto, critério sem `name`, gate 0/11/`true`/`9.5`, nenhum
   critério bloqueante, campo desconhecido, `max_cycles` 6.
3. Review inválido: raiz não-objeto, campo faltando, campo extra, `decision` fora do enum,
   `coverage` `NaN`/fora de 0–1, `criteria` faltando nome, critério extra, nota float,
   `feedback` sem `fix`, `artifact` divergente.
4. Gates: `hard_failures` → blocked; artefato ausente → blocked; check com exit 1 → blocked;
   critério abaixo do gate com `required_fix` → retry; sem `required_fix` → blocked;
   coverage abaixo do gate com gap correspondente → retry; sem gap → blocked.
5. Critério `blocking: false` abaixo do gate não gera retry nem bloqueia.
6. `approved` quando todos os gates passam, com `human_signoff: pending` e fingerprint estável.
7. Cinco ciclos sem passar → `blocked` com `failed_criteria`, `last_review` e `feedback`;
   sexto ciclo rejeitado.
8. Idempotência: repetir o mesmo ciclo é no-op; conteúdo diferente no mesmo ciclo é erro.
9. Retomada: journal completo retoma; lacuna de evento, review inválido ou symlink no diretório
   levantam erro.
10. `approved` não é re-executado; novo `run_id` permite rodar de novo.
11. Cópias de harness byte-idênticas ao canônico.

## Critérios de aceite

- `pytest` verde no repo.
- Rodar o contrato `contrato-editorial.json` num artefato real de teste: 1 retry e depois
  `approved` com `human_signoff: pending`.
- Rodar `contrato-codigo.json` com um `check` de `pytest`: check falhando produz `blocked`
  imediato, sem chamar o revisor.
- Skill instalada globalmente em `~/.agents/skills/gauntlet-core` e visível como skill nesta
  sessão.
- README com todos os harnesses e comando `npx` validado.
