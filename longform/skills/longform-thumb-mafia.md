---
description: Especificacao de CAPA (thumbnail) da categoria Mafia contemporanea (LENA) — override do formato Selena na Etapa 5.
---

# longform-thumb-mafia (override de capa — Etapa 5)

Esta skill e injetada como OVERRIDE de capa nas categorias Mafia (precedencia sobre o formato Selena da skill compartilhada `longform-prompts-img`). Fichas/Bible e a Etapa 7 continuam vindo da skill compartilhada.

## PROMPT MESTRE

## PROMPT MESTRE — THUMBNAIL (CAPA) MÁFIA — completo e autossuficiente (v2, galã elegante)

> Versão adaptada do prompt de máfia da Etapa 5. **Mudou SÓ o lead masculino** (seção 5),
> o **trecho pronto do chefão** (seção 9) e as **âncoras de elegância** no template (seção 8).
> Todo o resto — regras de ouro, emoção, cor, anti-moderação, beleza divina, composição,
> referência aprovada — está IGUAL, porque já estava certo.
>
> ⚠️ **Correção pós-uso:** NÃO usar lista "AVOID / negative prompt" no GPT 2. Modelos da OpenAI
> não negam de forma confiável — escrever "evite corrente de ouro / cara suja / tatuagem de
> gangue" tende a INVOCAR essas coisas. A direção anti-criminoso é feita **só no POSITIVO**
> (descrever o galã elegante), nunca por negação.
>
> **Objetivo da adaptação:** o chefe da máfia estava saindo com **cara de criminoso de rua**
> (bandidão, ar sujo, corpo de brutamontes). Agora ele sai como **galã sexy e MODERNO tipo *365
> Dias* (Massimo)** — **jovem (início dos 30), riquíssimo, lindo e perigoso só no OLHAR**.
> Tatuagem e camisa aberta continuam **bem-vindas** (o Massimo tem) — o que muda é **ancorar
> forte no "galã jovem de cinema"** pra não virar bandido, e **cortar o corpo de fisiculturista**.
>
> ⚠️ **NÃO é "old-money"/aristocrata/velho.** Elegância aqui = **galã atual e gostoso**, terno de
> grife ou camisa preta aberta — nunca um senhor antiquado.
>
> A capa é sempre uma imagem **16:9 HORIZONTAL, LIMPA, SEM NENHUM TEXTO**. Prompt em **inglês**,
> salvo em `prompts_thumbnail.txt`. Fichas/Character Bible continuam vindo da skill compartilhada.

Esta é a ESPECIFICAÇÃO DE CAPA da categoria **Máfia contemporânea (LENA)**. Ela substitui,
APENAS na thumbnail, o bloco "FORMATO DAS NOSSAS CAPAS (selena / Alpha King)" e o preset de
cenário `lena` da skill compartilhada. Tudo o mais da skill compartilhada (REGRAS DE OURO,
EMOÇÃO em primeiro plano, anti-moderação do GPT 2, obedecer ao "Thumb:" do card, ler a
`thumb_ref.png`, composição que lê em miniatura, template do prompt) continua valendo.

### 0. O QUE VOCÊ GERA

Você gera o PROMPT DE IMAGEM de UMA thumbnail HORIZONTAL 16:9 de YouTube para o universo
**máfia contemporânea**. A imagem é LIMPA, SEM NENHUM TEXTO. Personagens lindos, deslumbrantes,
divinos. Direção: glamouroso, intenso, chamativo. Escreva o prompt em INGLÊS, numa linha
lógica, e salve em `prompts_thumbnail.txt`.

### 1. ENTRADAS (de `source.json` + `roteiro.txt`)

- **PROJETO/ERA** — aqui é sempre **máfia contemporânea (LENA)**: chefão + heroína; penthouses,
  arranha-céus, galas, escritórios, mármore e lustres de cristal.
- **BLOCO "Thumb:"** (`thumb_brief` do card — comandos da Heloyse) → **OBEDECER À RISCA**
  (personagem diferente, detalhe extra, humor, cor de cabelo, "a mesma coisa", etc.). Quando o
  card der um "Thumb:" específico (roupa de professora, óculos, encurralada, etc.), ele tem
  **precedência** sobre o formato geral deste documento.
- **REFERÊNCIA** (`thumb_ref.png`, se houver) → ABRA com Read e descreva a **AÇÃO** da cena. A
  AÇÃO é o que mais importa: o prompt deve REFLETIR essa ação, adaptada ao universo máfia e aos
  personagens do `style_bible`. Sem referência, crie do zero pelo roteiro + título.
- **"Título:"** → SÓ CONTEXTO para entender a cena. **NUNCA vai escrito na imagem.**

### 2. REGRAS DE OURO

1. **SEM TEXTO** na imagem (nenhuma letra/legenda/marca/logo). Composição limpa, leads em
   destaque.
2. **Refletir a AÇÃO** da referência + cumprir os comandos do "Thumb:".
3. **Casar a era/cenário** do universo máfia contemporâneo.
4. **Só ADULTOS** em cena romântica/sensual.
5. **COR / balanço de branco:** cena sensual/íntima/romance quente → tom **DOURADO QUENTE**
   (bom); TODO o resto → `"bright, clean, balanced neutral white balance, natural
   true-to-life color, crisp"` (cinematográfico SEM o cast amarelo). **NÃO** bote "warm golden"
   em tudo — o GPT 2 já puxa pro quente e sairia amarelo demais.
6. **ANTI-MODERAÇÃO** (escreva o prompt já evitando travas; a troca/refino de modelo é da
   Etapa 6): EVITE as palavras-gatilho do filtro do GPT 2/OpenAI — *corners, traps, dominant,
   submissive, sensual, possessive, jealousy, lips parted, breath caught, charged*. Reenquadre
   tensão como CONFRONTO / queda de braço de poder (ela ergue o queixo, desafiadora; ou
   cautelosa), mantendo "intense eye contact, charged tension, glamorous". (Lição da galeria:
   confronto passa; pose dominante / decote / gap de idade explícito moderam.) **REGRA DURA:**
   a capa nasce SEMPRE no GPT 2; é PROIBIDO gerar a thumb do ZERO no Nano Banana 2 (sai
   escura/sem graça). Se moderar de jeito nenhum, a Etapa 6 ALIVIA o prompt até passar no GPT 2
   (base clara/glam) e SÓ DEPOIS refina no Nano Banana 2 EDITANDO essa base — nunca um cold gen.
7. **COMPOSIÇÃO que lê bem em miniatura:** lead em **PRIMEIRO PLANO grande + cena ao fundo**
   (close/meio-corpo, não plano aberto). Objeto-gancho quando a cena pedir (ex.: o anel, a
   carta, o relógio de ouro) reforça o clique.
8. **⭐ GALÃ MODERNO vs. CRIMINOSO (regra que resolve o problema nº1) — SÓ NO POSITIVO:**
   o chefão é um **galã jovem e sexy de cinema (tipo *365 Dias*) que por acaso é perigoso**. O
   perigo dele vem do **OLHAR e da POSTURA** (sério, magnético), **nunca** de uma aparência
   descuidada — ele é **jovem, riquíssimo, lindo**. Steer **descrevendo o que ele É** (young
   devastatingly handsome, early 30s, sexy heartthrob, GQ-cover / movie-star, sharp modern
   designer suit, smoldering gaze). **NÃO use lista de "AVOID"/negative prompt no GPT 2** — a
   OpenAI não nega direito e acaba INVOCANDO o que você quer evitar. E **não** deixe ele
   sorridente-bonzinho/passivo tipo "milionário simpático" nem **velho/aristocrata** —
   resolve-se dizendo **"young, serious, commanding, magnetic alpha"**, não por negação.

### 3. EMOÇÃO É O PRINCIPAL (regra de ouro da capa)

Identifique a emoção mais forte da cena e AMPLIFIQUE-a no rosto — capa morna não retém nem é
aprovada (a galeria reprovou a versão "fria, só conversando"). Se a personagem chora: `tears
streaming down her face, eyes red-rimmed and glistening, raw heartbreak, trembling lips`. Para
outras emoções, use o pico equivalente (anseio intenso, fúria contida, paixão, desespero,
esperança). Olhar expressivo, micro-expressão legível mesmo na miniatura — emoção crua acima de
pose bonita neutra.

### 4. CENÁRIO / ERA — máfia contemporânea, luxo opulento

Mundo de máfia de hoje, dinheiro e poder à vista. Use o ambiente que a cena pedir: penthouse de
mármore com lustres, salão de gala / festa de black-tie com candelabros de cristal, escritório
de arranha-céu à noite com a cidade ao fundo, elevador de vidro, escadaria de mansão/palácio,
bar de mármore escuro, interior de limusine/carro de luxo, restaurante reservado à luz de velas.
Sempre **cinematográfico, opulento, caro** — superfícies brilhantes, dourado e mármore,
profundidade de campo de cinema. Guarda-costas de terno preto ao fundo (desfocados) quando a
cena pedir tensão de "império do crime".

### 5. FORMATO DOS LEADS — o chefão e a heroína

**O CHEFE DA MÁFIA (lead masculino) — MODERNO, JOVEM e MUITO gato (referência: *365 Dias*):**
um homem **impossivelmente bonito, nível deus**, **jovem (início dos 30)**, um **galã sexy de
cinema / modelo** — pense no chefão de *365 Dias* (Massimo): **moderno, magnético, perigoso e
lindo**. Mandíbula marcada, olhar intenso e sedutor, corpo **atlético e sarado** (forte mas
sleek/elegante, **não** fisiculturista grotesco). ⚠️ **NUNCA velho, aristocrata, "vovô" ou
antiquado** — elegância aqui **NÃO** é old-money/careta, é **galã atual e gostoso**. O perigo é
no olhar e na postura; o resto é puro glamour.

- **Cabelo MODERNO:** escuro, curto a médio, penteado para trás (slicked-back) ou levemente
  bagunçado/ondulado. (Troca-chave vs. Selena: lá é longo e esvoaçante; AQUI é curto/médio atual.)
- **Barba SEXY:** rosto limpo **OU** barba de designer / curta bem cuidada e sexy (estilo
  Massimo). O que **NÃO** pode é barba **suja/descuidada/relaxada** — essa dá ar de bandido; a de
  galã é aparada e proposital.
- **TATUAGENS SEXY (assinatura do mafioso gato — bem-vindas):** visíveis no **pescoço / mãos /
  antebraços** (e no **peito quando a camisa está aberta**). Só **não** no rosto e nada de
  tatuagem de gangue barata. Tatuagem aqui deixa **mais mafioso e mais gato**.
- **Figurino MODERNO e caro:** terno de **grife com corte italiano slim** (gravata escura **ou
  sem gravata, colarinho aberto**), OU **camisa social preta aberta no peito** (bem-vinda — é
  sexy e mostra a tatuagem). Estética **atual**, não "old-money antiquado". Riqueza à vista —
  relógio de ouro (Rolex), anéis.
- **Âncoras OBRIGATÓRIAS** (em todo prompt, SÓ no positivo): `young devastatingly handsome mafia
  boss, early 30s, sexy magnetic heartthrob, male supermodel and movie-star looks, sharp modern
  designer suit, smoldering intense gaze, glamorous — like the mafia boss lead in a steamy modern
  romance.` (Não escreva "not a thug / not old" — no GPT 2 negativo pode invocar o que se quer
  evitar; afirme **"young, modern, sexy, gorgeous"** com força.)

**A HEROÍNA (lead feminina):** **de beleza sobre-humana, como uma deusa** — rosto perfeitamente
simétrico e esculpido, pele impecável e luminosa, olhos cativantes e profundos, traços irreais
de tão perfeitos; elegante e refinada. Figurino conforme a cena (vestido de festa/gala, vestido
de noiva de renda, look mais recatado de "moça boa" quando o card pedir — ex.: professora,
criada). Cabelo e idade conforme o "Thumb:" do card.

> **REGRA DA BELEZA DIVINA (inquebrável — ambos os leads):** os dois personagens devem parecer
> **impossivelmente bonitos, nível deuses** — o espectador ao ver a capa deve sentir "essas
> pessoas não são reais de tão perfeitas". Descritores OBRIGATÓRIOS em todo prompt:
> - **Rosto:** `perfectly symmetrical divine face, high cheekbones, strong chiseled jaw` (ele) /
>   `delicate perfectly sculpted face, high cheekbones, ethereal beauty` (ela)
> - **Pele:** `flawless luminous porcelain skin, airbrushed perfection`
> - **Olhos:** `piercing mesmerizing eyes, intense gaze, sharp eye detail`
> - **Geral:** `impossibly beautiful, deity-level perfection, otherworldly stunning appearance`
> Nunca deixar os personagens "normais" — cada capa é uma fantasia visual máxima. Mantenha o
> casal coerente com a `style_bible` (Etapa 5).

### 6. LUZ / COR

Capa **bem clara e luminosa por padrão** (very bright, well-lit, high-key, bright key light on
the faces — `bright, clean, balanced neutral white balance, natural true-to-life color,
crisp`), nada de capa escura. Tom **dourado quente** só em cena íntima/romance quente. O GPT 2
já puxa pro quente — não bote "warm golden" em tudo.

### 7. REFERÊNCIA VISUAL APROVADA (padrão das capas de máfia Helô Stories)

Siga **exatamente este padrão** — é a estética já aprovada: casal em primeiro plano, o chefão
**jovem, moderno e MUITO gato** (terno de grife OU camisa preta aberta, relógio de ouro,
tatuagens sexy no pescoço/mãos) **encarando** a mulher linda (tensão face-a-face ou ele olhando
para ela de cima), cercados de guarda-costas de terno preto / convidados de gala ao fundo
(desfocados), lustres de cristal, mármore, muito glamour e tensão. O homem parece **galã sexy de
cinema (tipo *365 Dias*)** — nunca um capanga nem um velho.

### 8. TEMPLATE DO PROMPT

Preencha os `[____]`; o prompt COMEÇA com as tags `[Character N: NAME]` que aparecem na capa,
depois o corpo em inglês — tudo numa linha. Direção só no POSITIVO (sem "AVOID"/negative prompt):

```
[Character 1: NAME] [Character 2: NAME] Cinematic 16:9 widescreen YouTube thumbnail,
ultra-detailed, photorealistic, sharp focus, professional color grading. [CENÁRIO máfia].
[PERSONAGENS: descrever cada lead — cabelo (cor/comprimento), idade aparente, tom de pele,
roupa; "gorgeous, flawless, god-like"; o chefão = "young devastatingly handsome mafia boss,
early 30s, sexy magnetic heartthrob, male-model / movie-star looks, sharp modern designer suit,
smoldering gaze"]. [AÇÃO da cena, refletindo a referência + comandos do "Thumb:"]. [EMOÇÃO/clima: ex. intense eye contact,
charged tension, shock, tenderness]. [LUZ/COR: "warm golden glow" se íntima | senão "bright,
clean, balanced neutral white balance, natural true-to-life color, crisp"]. Both leads large and
centered in the foreground. Glamorous, intense, eye-catching, beautiful flawless faces. Wide 16:9
aspect ratio. No text, no watermark, no logo.
```

### 9. TRECHOS PRONTOS P/ COLAR NO TEMPLATE

- **`[CENÁRIO]` (máfia):** "modern mafia luxury setting — marble penthouse / crystal-chandelier
  black-tie gala / night high-rise office over the city skyline / grand mansion staircase /
  dark marble bar / luxury car interior; opulent, glossy, cinematic, black-suited bodyguards
  blurred in the background when the scene calls for it."

- **`[PERSONAGENS]` o chefão** (colar e ajustar) — **versão galã moderno tipo *365 Dias*:** "a
  young, devastatingly handsome mafia boss in his early 30s — a sexy, magnetic heartthrob with
  male-supermodel / movie-star looks (like the mafia-boss lead in a steamy modern romance):
  perfectly symmetrical face, strong chiseled jaw, high cheekbones, piercing smoldering eyes,
  flawless luminous skin; athletic muscular-lean body (fit and strong but sleek, NOT a
  bodybuilder brute), short-to-medium dark hair slicked back or lightly tousled, clean-shaven or
  sexy well-groomed designer stubble, sexy visible tattoos on the neck / hands / forearms (and
  chest when the shirt is open), a sharp modern designer suit with a dark tie or open collar (or
  an open black dress shirt), gold Rolex and rings; modern, rich, intense and dangerous only
  through his gaze — glamorous, impossibly gorgeous, young and immaculate."

- **`[PERSONAGENS]` a heroína** (colar e ajustar): "a breathtakingly beautiful woman —
  goddess-level beauty: perfectly symmetrical ethereal face, delicate sculpted features, high
  cheekbones, captivating mesmerizing eyes, flawless luminous porcelain skin, airbrushed
  perfection; impossibly beautiful, otherworldly divine appearance — [figurino e cabelo conforme
  o card]."
