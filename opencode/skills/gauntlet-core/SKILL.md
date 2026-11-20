---
name: gauntlet-core
description: |
  Executa uma tarefa em ciclos isolados de executor e revisor, com checks determinísticos,
  gates numéricos e bloqueio fail-closed. Os critérios de qualidade vêm de um contrato JSON
  da própria tarefa.

  Acionada quando o usuário menciona:
  - "roda o gauntlet"
  - "gauntlet com contrato"
  - "loop de qualidade ate passar"
  - "executor e revisor em ciclos"
  - "quero um gate de qualidade para esta tarefa"
---

# Gauntlet Core

Você não julga a qualidade por conta própria. Você captura os critérios da tarefa num contrato,
executa o ciclo e deixa o motor decidir `approved` ou `blocked`.

## Quando usar

- Existe um artefato verificável (arquivo, página, código, documento) e um padrão de qualidade
  que pode ser descrito em critérios numéricos.
- O trabalho pode ser refeito em ciclos com feedback acionável.
- Alguém vai revisar no final e precisa de rastro de por que aquilo passou.

## Quando NÃO usar

- A tarefa não tem critério de qualidade declarado: a resposta é "não dá para rodar o gauntlet",
  não um critério inventado.
- O artefato não é verificável (uma conversa, uma decisão, um e-mail enviado).
- A aprovação final é humana e irrevogável e ninguém quer ciclo automático antes.

## Camada 1 — Capturar os critérios no contrato

Pergunte, uma por vez, e registre a resposta literal:

1. Qual arquivo é o artefato e onde ele fica (caminho relativo ao workspace)?
2. O que reprova sem discussão? (vira critério bloqueante com `gate` 9 ou 10)
3. O que é "bom" mas não impede entrega? (vira `blocking: false`)
4. Qual o piso numérico de cada critério, de 0 a 10?
5. Existe comando que precisa passar antes do revisor? (testes, build, lint, grep)
6. Quantos ciclos no máximo, de 1 a 5?

Regra dura: nunca invente critério que a tarefa não declarou. Se faltar resposta, pare e pergunte.

Escreva o contrato em JSON e valide com `load_contract`. Exemplo mínimo:

```json
{
  "name": "correcao-post",
  "goal": "Reescrever o draft corrigindo as falhas apontadas.",
  "artifact": "content/drafts/post.md",
  "criteria": [
    {"name": "clareza", "description": "Cada paragrafo tem uma ideia principal.", "gate": 9}
  ],
  "max_cycles": 5,
  "persistence_dir": "runs/correcao-post",
  "run_id": "correcao-post-01"
}
```

Dois exemplos completos para copiar: `contracts/contrato-editorial.json` e
`contracts/contrato-codigo.json`.

Erros comuns: critério vago ("qualidade"), gate frouxo para compensar revisor ruim, artefato
absoluto, feedback sem `fix`, contrato sem nenhum critério bloqueante.

## Camada 2 — Executar o ciclo

Com Python disponível, use o motor:

    from gauntlet_core import load_contract, run_gauntlet

    def executor(feedback):
        # task nova e isolada; escreve o artefato no caminho do contrato
        ...

    def revisor(artifact, feedback):
        # task nova e isolada, diferente do executor; devolve o review JSON
        ...

    contrato = load_contract("caminho/contrato.json")
    resultado = run_gauntlet(executor, revisor, contrato, workspace_root=".")

No motor, os checks determinísticos rodam antes do revisor. O callback `revisor` recebe apenas
`artifact` e `feedback`; o contrato chega por closure ou por caminho declarado.

Sem Python, conduza os ciclos manualmente com as mesmas regras e marque o resultado com
`"verified_by": "agent"` em vez de `"motor"`.

Protocolo obrigatório em cada ciclo:

1. Registre o início do ciclo e o número.
2. Chame o executor numa `task` nova, com contexto novo e apenas o `feedback` do ciclo anterior.
3. Rode os checks determinísticos antes de chamar o revisor. Falha de check bloqueia na hora.
4. Chame o revisor em outra `task` nova, diferente do executor, entregando artefato, contrato e
   feedback. Ele devolve JSON com `decision`, `coverage`, `criteria`, `hard_failures`, `feedback`,
   `artifact` e, quando houver lacuna de cobertura, `coverage_gaps`.

   ```text
   decision:       "approved" | "feedback"
   coverage:       número de 0 a 1
   criteria:       objeto com exatamente as chaves dos critérios do contrato; inteiros de 0 a 10
   hard_failures:  lista
   feedback:       lista de {"criterion", "kind": "required_fix" | "optional_suggestion", "fix"}
   artifact:       string igual ao artifact do contrato
   coverage_gaps:  lista de critérios do contrato (só quando houver lacuna de cobertura)
   ```

   `coverage_gate` vale 0.99 por padrão; ficar abaixo dele exige um `required_fix` ligado a um
   critério declarado em `coverage_gaps`.
5. Aceite só JSON válido e completo. Texto livre ou aprovação verbal não contam. JSON inválido,
   truncado ou fora do schema é `blocked` terminal — nunca se repete o revisor para "tentar de
   novo" a mesma saída.
6. Se o gate reprovar com feedback completo, inicie o próximo ciclo com esse feedback.
7. Pare em `approved` ou `blocked`. Nunca abra sexto ciclo.

## Encerramento

- `approved` sempre traz `"human_signoff": "pending"`. Entregue o artefato e diga:
  "pronto para seu QA". Nunca declare a tarefa aprovada.
- `blocked` entrega `failure_reasons`, `failed_criteria`, `last_review` e `feedback`.
  Não mascare, não "quase aprove", não continue a fila por conta própria.

## Anti-padrões

- Revisor igual ao executor, ou com o mesmo contexto.
- Feedback genérico ("melhorar") sem `criterion` e `fix`.
- Aprovar porque o ciclo acabou.
- Reexecutar um `run_id` já aprovado; revisão de trabalho aprovado exige `run_id` novo.
- Escrever artefato fora do caminho declarado.
