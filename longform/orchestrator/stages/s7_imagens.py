# -*- coding: utf-8 -*-
"""Etapa 7 — Imagens do CORPO do vídeo (a partir da thumb confirmada).

Depende de thumb_selected.png (Gate 2). Passos:
  0) PADRÃO: a thumb confirmada (capa) é SEMPRE a 1ª imagem do vídeo. Copiamos ela para
     images/img_000.png — como o build-mapping ordena por nome, img_000 entra antes de
     img_001.., abrindo o vídeo com a capa e seguindo com o corpo na sequência.
  1) Deriva prompts_imagens.txt: N_IMAGENS prompts (na ordem da narração) que reusam os
     personagens/look da thumb (consistência) + cenários do roteiro/SRT.
  2) Gera images/img_001.png … via Magnific em modo referência (ancorado na thumb).

O CORPO são SEMPRE N_IMAGENS imagens (fixo); somadas à capa (img_000) o vídeo tem N+1
imagens na timeline. Cada uma cobre ~duração_total / (N+1) de história (Ken Burns longo na
montagem). Não escala com a duração.
"""

import os
import shutil
import threading

from common import ErroPipeline, parse_srt
from runner import rodar_claude, montar_prompt, MODELO_IMG_PROMPTS
from stages import magnific_seam

N_IMAGENS = 6   # corpo do vídeo: 6 imagens fixas (economia: 8→6 em 2026-06-18), derivadas da thumb


def _duracao(proj):
    cues = parse_srt(proj.narration_srt)
    if not cues:
        raise ErroPipeline("narration.srt vazio/ilegível — não dá para segmentar as imagens.")
    return cues[-1][2]  # end do último cue


def _clarear_capa_escolhida(proj, log, cancel):
    """Relumina SÓ a capa confirmada (thumb_selected.png), depois do Gate 2.

    O relight do Magnific cobra crédito por chamada; antes ele rodava nas 3 variações da
    Etapa 6 (2 jogadas fora no gate). Agora roda 1 vez, na capa que sobrou — economia de ~2/3.
    Idempotente (proj.relight_flag) e desligável por env LONGFORM_THUMB_RELIGHT=0."""
    if os.environ.get("LONGFORM_THUMB_RELIGHT", "1").strip() == "0":
        log("    Relight da capa desligado (LONGFORM_THUMB_RELIGHT=0) — pulando.")
        return
    if proj.existe(proj.relight_flag):
        log("    Capa já passou pelo relight antes — passo pulado.")
        return
    log("    Clareando a capa escolhida (relight, só nesta imagem)...")
    magnific_seam.gerar(
        proj, log, cancel,
        magnific_seam.instr_relight_arquivo("thumb_selected.png"),
        modelo="sonnet")
    proj.relight_flag.write_text("ok", encoding="utf-8")


def _fixar_thumb_como_primeira(proj, log):
    """PADRÃO: a capa (thumb_selected.png) é a 1ª imagem do vídeo (images/img_000.png).

    Idempotente: copia só se ainda não existir. img_000 ordena antes de img_001.., então o
    build-mapping a coloca no início da timeline sem nenhum tratamento especial de caminho
    (FFmpeg e Remotion leem todas as images/img_*.png igualmente)."""
    alvo = proj.images_dir / "img_000.png"
    if proj.existe(alvo):
        return
    shutil.copyfile(proj.thumb_selected, alvo)
    log("    Capa (thumb) fixada como 1ª imagem do vídeo: images/img_000.png.")


def _derivar_prompts(proj, log, cancel, n, seg_por_imagem):
    """Passo 1 — deriva prompts_imagens.txt (Sonnet), ancorado na thumb/fichas + roteiro/SRT.

    Idempotente: reaproveita se já existe. É INDEPENDENTE do relight da capa (ambos só leem
    thumb_selected.png), então roda em paralelo a ele no run()."""
    if proj.existe(proj.prompts_imagens):
        log("    prompts_imagens.txt já existe — reaproveitando.")
        return
    extra = (
        "MODO B (Etapa 7). ABRA a imagem `thumb_selected.png` com Read e use os PERSONAGENS e o "
        "LOOK dela como VERDADE VISUAL (rosto, cabelo, idade, roupa, paleta). Leia também "
        "style_bible.txt, prompts_referencia.txt, referencias.json (mapa dos personagens na "
        "Library), roteiro.txt e narration.srt. Gere `prompts_imagens.txt` com EXATAMENTE %d "
        "prompts de imagem 16:9 (um por linha, numerados img_001..img_%03d), na ORDEM da "
        "narração, cada um cobrindo ~%.0fs de história. CADA prompt começa com a(s) tag(s) "
        "[Character N: NAME] presentes (nome idêntico ao da bible/referencias.json) — é assim "
        "que o orquestrador injeta a ficha da Library e trava o personagem. Varie cenário/ação "
        "conforme o trecho, mantendo a aparência travada. NÃO gere imagens agora; só os prompts."
        % (n, n, seg_por_imagem)
    )
    log("    Derivando %d prompts de imagem (%s)..." % (n, MODELO_IMG_PROMPTS))
    rodar_claude(montar_prompt("longform-prompts-img", extra),
                 proj.dir, log, cancel, modelo=MODELO_IMG_PROMPTS)
    if not proj.existe(proj.prompts_imagens):
        raise ErroPipeline("Etapa 7 não gerou prompts_imagens.txt.")


def run(proj, log, cancel=None, n_imagens=N_IMAGENS, **_):
    if not proj.existe(proj.thumb_selected):
        raise ErroPipeline(
            "Falta thumb_selected.png (Gate 2). Valide a thumb no painel antes da Etapa 7."
        )
    if not proj.existe(proj.narration_srt):
        raise ErroPipeline("Falta narration.srt (Etapa 4) para segmentar as imagens.")

    n = n_imagens
    dur = _duracao(proj)
    # +1 imagem na timeline: a capa (img_000) abre o vídeo; o corpo são as N seguintes.
    seg_por_imagem = dur / (n + 1)
    log("▶ Etapa 7/8 — Corpo do vídeo: %d imagens fixas + capa na abertura "
        "(narração %.0fs, ~%.0fs cada)." % (n, dur, seg_por_imagem))

    # Passos 0a e 1 em PARALELO: relight da capa (Magnific) ∥ derivação dos prompts (Sonnet).
    # São INDEPENDENTES — ambos só LEEM thumb_selected.png e nenhum usa a saída do outro; em
    # série era fila à toa. A geração (Passo 2) é que precisa dos DOIS prontos. Os logs dos dois
    # claude -p são serializados por um lock (a UI/Tk não é thread-safe p/ escrita concorrente).
    log_lock = threading.Lock()
    def _log_seguro(msg):
        with log_lock:
            log(msg)

    erros = {}
    def _tarefa_relight():
        try:
            _clarear_capa_escolhida(proj, _log_seguro, cancel)
        except BaseException as e:   # captura p/ re-raise na thread principal
            erros["relight"] = e

    t_relight = threading.Thread(target=_tarefa_relight, name="relight-capa", daemon=True)
    t_relight.start()
    try:
        # derivação dos prompts roda na thread atual, em paralelo ao relight acima
        _derivar_prompts(proj, _log_seguro, cancel, n, seg_por_imagem)
    finally:
        t_relight.join()   # nunca deixa o relight orfão, mesmo se a derivação falhar
    # se a derivação falhou, a exceção dela já propagou no finally acima; aqui só o relight
    if "relight" in erros:
        raise erros["relight"]

    # Passo 0b — a capa confirmada (e JÁ clareada pelo relight) é SEMPRE a 1ª imagem do vídeo.
    _fixar_thumb_como_primeira(proj, log)

    # Passo 2 — gerar as imagens via Magnific (referência = thumb_selected.png)
    # Conta só o CORPO (img_001..); a capa img_000 não entra na cota de geração.
    existentes = [p for p in sorted(proj.images_dir.glob("img_*.png"))
                  if p.name != "img_000.png"]
    if len(existentes) >= n:
        log("    %d imagens do corpo já existem em images/ — geração pulada." % len(existentes))
        return
    # Trava de crédito: o corpo usa LONGFORM_MAGNIFIC_MODE (modelo que COBRA crédito).
    # Só gera se liberado explicitamente (LONGFORM_MAGNIFIC_CORPO_OK=1).
    magnific_seam.garantir_corpo_liberado()
    lock = (magnific_seam.instr_char_lock("thumb_selected.png")
            if proj.existe(proj.referencias_json) else "")
    instr = (
        "Você é a Etapa 7 (imagens do vídeo). Leia `prompts_imagens.txt` (%d prompts numerados). "
        "Para CADA prompt, gere a imagem mantendo os MESMOS personagens/características das fichas. "
        "Salve como images/img_001.png … images/img_%03d.png.\n\n%s\n\n%s"
        % (n, n, lock,
           magnific_seam.receita(n, "images/img_NNN.png (NNN = número do prompt, 001..%03d)" % n))
    )
    log("    Gerando %d imagens via Magnific (%s%s)..."
        % (n, magnific_seam.modo_body_atual(),
           ", lock de personagem (Library)" if lock else ", consistência por prompt"))
    magnific_seam.gerar(proj, log, cancel, instr, modelo="sonnet")
    geradas = sorted(proj.images_dir.glob("img_*.png"))
    if not geradas:
        raise ErroPipeline("Etapa 7 não gerou nenhuma imagem em images/.")
    log("    ✓ %d imagem(ns) gerada(s)." % len(geradas))
