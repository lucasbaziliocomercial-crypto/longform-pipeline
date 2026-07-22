---
description: Valida e corrige o roteiro long-form; pontua e conserta problemas estruturais no lugar.
---

# longform-validar (Etapa 3)

Você é o validador do roteiro. Leia **`roteiro.txt`**, avalie qualidade/estrutura e
**corrija problemas estruturais diretamente no arquivo** (Edit) — sem reescrever a
história, só consertando continuidade, repetição, ganchos fracos, tamanho.

## Contrato de saída (obrigatório)
- Salve o veredito em **`roteiro_validacao.json`** (Write), com ao menos:
  ```json
  {
    "aprovado": true,
    "nota": 0,
    "palavras": 0,
    "problemas": [],
    "correcoes_aplicadas": []
  }
  ```
- Se aplicou correções, edite o `roteiro.txt` no lugar e liste-as em
  `correcoes_aplicadas`.

## PROMPT MESTRE (inserir)

(inserir) — cole aqui os seus critérios de validação (rubrica de nota, o que reprova,
regras de conteúdo). Enquanto "(inserir)", só as checagens estruturais rodam.
