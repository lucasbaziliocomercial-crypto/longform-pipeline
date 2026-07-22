---
description: Normaliza pontuação/cadência do roteiro para o TTS ler natural (não muda palavras).
---

# longform-humanizar-narracao (Etapa 4, pré-TTS)

Normalize o **`roteiro.txt`** para a narradora TTS ler de forma natural e salve o
resultado em **`roteiro_tts.txt`** (Write). É trabalho MECÂNICO: **não altere palavras,
não corte nem adicione conteúdo, não reordene frases.**

## Regras
- Corrija apenas pontuação e cadência: vírgulas para respiração, pontos finais claros,
  reticências viram ponto quando forem só ênfase visual, travessões viram vírgula.
- Expanda abreviações/números para a forma FALADA (ex.: "35 min" → "thirty-five minutes",
  "Mr." → "Mister", "%" → "percent") no idioma do roteiro.
- Remova marcações que não se leem (cabeçalhos, colchetes de cena, emojis, markdown).
- Mantenha os parágrafos separados por linha em branco (o TTS quebra em blocos por parágrafo).
- Texto puro, sem comentários seus. Se nada precisar mudar, copie o roteiro como está.

## Ajuste fino (opcional)

Nenhum ajuste extra por ora — as regras acima já produzem uma leitura natural.
