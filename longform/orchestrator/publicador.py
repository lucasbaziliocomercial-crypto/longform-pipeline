# -*- coding: utf-8 -*-
"""publicador.py — sobe + AGENDA os vídeos da fila no YouTube, canal por canal, via AdsPower.

É o worker à parte da Etapa 9: a Etapa 9 só enfileira (publicacao/fila/<slug>.json); aqui a
gente drena a fila. Para cada item pendente:
  1. calcula o próximo slot do canal (agenda.py: 3/dia, 18h US Pacific por padrão);
  2. Gate 3 (painel) p/ você revisar/editar título/descrição/tags e aprovar (a menos de --no-gates);
  3. abre o PERFIL do canal no AdsPower (adspower.py) e conecta o Playwright no Chromium logado;
  4. sobe o vídeo no YouTube Studio, preenche metadados, marca "not made for kids", adiciona a
     TELA FINAL ("best for viewer") + CARDS (últimos vídeos do canal), ESPERA o arquivo terminar
     de subir (ver `_esperar_upload`) e só então AGENDA no slot;
  5. reserva o slot no ledger do canal e marca o item como publicado.

Cadência do agendamento (agenda.py): por padrão 3 vídeos/dia espaçados 10 min por canal
(LONGFORM_PUB_POR_DIA / LONGFORM_PUB_ESPACO_MIN / LONGFORM_PUB_HORA). Tela final e cards ligam/
desligam por LONGFORM_ENDSCREEN / LONGFORM_CARDS / LONGFORM_CARDS_QTD.

IMPORTANTE — automação de UI é frágil: a UI do YouTube Studio muda e os seletores podem
precisar de recalibração (assume UI em INGLÊS). O fluxo do Studio está isolado em
`_subir_no_studio` justamente p/ ser fácil de ajustar. Rode primeiro `--bridge <user_id>`
(só abre o perfil + Studio, sem subir nada) e `--dry-run` (faz tudo menos confirmar o
agendamento) num canal de teste antes de ligar na produção.

Requisitos: AdsPower pago com Local API ligada; perfis logados por canal (ver categorias.py);
Playwright Python (`py -3 -m pip install playwright && py -3 -m playwright install chromium`).

Uso:
    py -3 publicador.py                 # drena a fila (com Gate 3)
    py -3 publicador.py --no-gates      # sem Gate 3 (100% automático)
    py -3 publicador.py --slug <slug>   # só um item da fila
    py -3 publicador.py --dry-run       # faz tudo menos confirmar o "Schedule"
    py -3 publicador.py --bridge <id>   # só testa a ponte AdsPower+Playwright (abre o Studio)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import config  # noqa: F401 — efeito colateral: carrega longform.env em os.environ
except Exception:  # noqa: BLE001
    pass

from common import FILA_DIR, PUBLICACAO_DIR, ErroPipeline, forcar_utf8_console
import adspower
import agenda
import categorias
import gates
import humano

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


PUBLICADOS_DIR = PUBLICACAO_DIR / "publicados"
STUDIO_URL = "https://studio.youtube.com"


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------

def _itens_fila(slug=None):
    """Lista os itens PENDENTES da fila (ordenados por data de criação). `slug` filtra um só."""
    if not FILA_DIR.is_dir():
        return []
    itens = []
    for p in sorted(FILA_DIR.glob("*.json")):
        if slug and p.stem != slug:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("status") == "pendente":
            d["_arquivo"] = str(p)
            itens.append(d)
    itens.sort(key=lambda d: d.get("criado_em", ""))
    return itens


def _marcar_publicado(item, slot, url_video, log):
    """Move o item da fila p/ publicados/ com o slot e a URL (se houver)."""
    PUBLICADOS_DIR.mkdir(parents=True, exist_ok=True)
    item = dict(item)
    item.pop("_arquivo", None)
    item["status"] = "publicado"
    item["agendado_para"] = slot.isoformat()
    item["url"] = url_video or ""
    item["publicado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (PUBLICADOS_DIR / ("%s.json" % item["slug"])).write_text(
        json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    orig = FILA_DIR / ("%s.json" % item["slug"])
    try:
        orig.unlink()
    except OSError:
        pass
    log("    ✅ %s publicado/agendado p/ %s." % (item["slug"], slot.strftime("%Y-%m-%d %H:%M %Z")))


# ---------------------------------------------------------------------------
# YouTube Studio (Playwright) — o trecho FRÁGIL, isolado p/ recalibração
# ---------------------------------------------------------------------------

# Diretório de screenshots de depuração (setado no --dry-run p/ calibrar os seletores do Studio).
_SHOTS_DIR = None
_shot_n = [0]


def _shot(page, tag):
    """Salva um screenshot rotulado em _SHOTS_DIR (no-op se não estiver em modo debug)."""
    if not _SHOTS_DIR:
        return
    try:
        _SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        _shot_n[0] += 1
        page.screenshot(path=str(_SHOTS_DIR / ("%02d_%s.png" % (_shot_n[0], tag))), full_page=False)
    except Exception:  # noqa: BLE001 — screenshot é best-effort, nunca derruba o fluxo
        pass


def _clicar_texto(page, texto, timeout=15000):
    """Clica no primeiro elemento clicável que contém `texto` (case-insensitive)."""
    page.get_by_text(texto, exact=False).first.click(timeout=timeout)


# ---------------------------------------------------------------------------
# Espera do UPLOAD — o passo que faltava (bug histórico)
# ---------------------------------------------------------------------------
#
# O Studio mostra o andamento do envio num rótulo próprio: "Uploading 45% … 3 minutes left",
# depois "Upload complete …" / "Processing …". Enquanto disser "Uploading", o arquivo AINDA
# está subindo — e fechar o perfil do AdsPower nesse momento ABORTA o envio.
#
# Antes desta função o publicador preenchia os metadados, clicava em Schedule, esperava 4s
# fixos e encerrava o perfil. Isso só funcionava por SORTE: quando o upload terminava durante
# os ~3 min de digitação. Com arquivo de ~1.5 GB em proxy residencial (10-40 min de envio) a
# corrida se perde — e piora justamente ao escalar, quando mais uploads dividem a banda.
_RE_SUBINDO = re.compile(r"\buploading\b", re.I)
_RE_SUBIU = re.compile(r"upload complete|processing|checks complete|finished", re.I)
# Seletores do rótulo de progresso (variam entre versões do Studio) — recalibre no --dry-run.
_SEL_PROGRESSO = ("ytcp-video-upload-progress .progress-label",
                  "ytcp-video-upload-progress",
                  ".progress-label")


def timeout_upload_min():
    """Teto da espera do upload, em minutos (LONGFORM_PUB_UPLOAD_TIMEOUT_MIN, default 45)."""
    try:
        return max(1, int(os.environ.get("LONGFORM_PUB_UPLOAD_TIMEOUT_MIN", "45")))
    except ValueError:
        return 45


def _rotulo_progresso(page):
    """Texto do rótulo de progresso do upload; "" se nenhum seletor casar."""
    for sel in _SEL_PROGRESSO:
        try:
            txt = (page.locator(sel).first.inner_text(timeout=2000) or "").strip()
            if txt:
                return txt
        except Exception:  # noqa: BLE001 — seletor ausente nesta versão do Studio
            continue
    return ""


def _esperar_upload(page, log):
    """BLOQUEIA até o arquivo terminar de subir. Falha ALTO se não der p/ ter certeza.

    Diferente de thumbnail/tags (best-effort, que só avisam), aqui NÃO é aceitável seguir na
    dúvida: confirmar o agendamento e fechar o perfil com o envio pela metade deixa o vídeo
    quebrado no canal. Sem o rótulo de progresso -> ErroPipeline e o item FICA na fila.
    """
    limite = timeout_upload_min() * 60
    t0 = time.time()
    ultimo_log = 0.0
    visto = ""

    while True:
        txt = _rotulo_progresso(page)
        if txt:
            visto = txt
            if _RE_SUBIU.search(txt) and not _RE_SUBINDO.search(txt):
                log("    → upload concluído (%s)." % txt)
                _shot(page, "upload_concluido")
                return
        decorrido = time.time() - t0
        # Nenhum rótulo em 60s = seletor a recalibrar, não upload lento.
        if not visto and decorrido > 60:
            _shot(page, "erro_progresso_upload")
            raise ErroPipeline(
                "não achei o rótulo de progresso do upload no Studio (seletores testados: %s). "
                "Rode `py -3 publicador.py --dry-run` e recalibre pelos screenshots — seguir sem "
                "essa confirmação aborta uploads grandes no meio." % ", ".join(_SEL_PROGRESSO))
        if decorrido > limite:
            _shot(page, "erro_timeout_upload")
            raise ErroPipeline(
                "upload não terminou em %d min (último estado: %r). Suba "
                "LONGFORM_PUB_UPLOAD_TIMEOUT_MIN ou investigue banda/proxy do perfil."
                % (timeout_upload_min(), visto or "desconhecido"))
        if decorrido - ultimo_log >= 30:
            ultimo_log = decorrido
            log("    … subindo (%s) — %ds" % (visto or "sem rótulo", int(decorrido)))
        page.wait_for_timeout(3000)


def _subir_no_studio(page, item, meta, slot, log, dry_run=False):
    """Executa o upload + agendamento no YouTube Studio. Devolve a URL do vídeo (ou "").

    Assume UI em INGLÊS. Passos: Create → Upload → escolher arquivo → título/descrição →
    SHOW MORE → tags → "Not made for kids" → Next (Video elements: TELA FINAL + CARDS) →
    Next×2 → Visibility → Schedule (data/hora) → Done.
    """
    video = item.get("video")
    if not video or not Path(video).is_file():
        raise ErroPipeline("vídeo do item não encontrado: %s" % video)

    log("    → abrindo o Studio…")
    page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
    humano.pausa(page, 2200, 4200)
    # WARM-UP + HEALTH-CHECK: se o perfil não caiu logado no Studio, quase sempre é proxy/sessão
    # fora — melhor PULAR o canal (o item fica na fila) do que forçar upload com o proxy ruim.
    if "studio.youtube.com" not in page.url:
        raise ErroPipeline("perfil não caiu logado no Studio (proxy/sessão fora?): %s" % page.url)
    humano.scroll_leve(page)          # gesto humano: rola um pouco a home antes de agir
    humano.pausa(page, 800, 2000)
    _shot(page, "studio_home")

    # CREATE → Upload videos. O botão de upload usa um <input type=file> escondido — muitas vezes
    # dá p/ setar o arquivo direto via filechooser sem navegar pelo menu.
    log("    → iniciando upload…")
    try:
        with page.expect_file_chooser(timeout=8000) as fc:
            try:
                _clicar_texto(page, "Create", 8000)
                page.wait_for_timeout(500)
                _clicar_texto(page, "Upload videos", 8000)
            except Exception:
                # fallback: botão de upload direto na home do Studio
                _clicar_texto(page, "Upload", 8000)
        fc.value.set_files(video)
    except Exception:
        # fallback: procura o input[type=file] e seta direto
        page.set_input_files("input[type=file]", video, timeout=15000)
    log("    → arquivo enviado, aguardando o processamento inicial…")
    page.wait_for_timeout(6000)
    _shot(page, "apos_upload")

    # DETAILS — título e descrição são editboxes contenteditable (ytcp). Aria-labels padrão em EN.
    titulo = (meta.get("title") or "").strip()[:100]
    desc = meta.get("description") or ""
    _preencher_editbox(page, ["Add a title", "Title"], titulo, log, "título")
    _preencher_editbox(page, ["Tell viewers about your video", "Description"], desc, log, "descrição")

    # THUMBNAIL custom — a capa da Etapa 6/7 (item["thumb"]), na mesma página de Details.
    _subir_thumbnail(page, item.get("thumb"), log)
    _shot(page, "detalhes")

    # AUDIENCE — "Not made for kids" (obrigatório antes de avançar).
    try:
        page.get_by_text("No, it's not made for kids", exact=False).first.click(timeout=10000)
        log("    → marcado 'not made for kids'.")
    except Exception:
        log("    ⚠ não achei o rádio 'not made for kids' — confira manualmente.")

    # SHOW MORE → Tags.
    tags = meta.get("tags") or []
    if tags:
        try:
            _clicar_texto(page, "Show more", 8000)
            page.wait_for_timeout(1500)
            campo = page.get_by_label("Tags", exact=False).first
            campo.click(timeout=8000)
            campo.fill(", ".join(tags))
            log("    → %d tags preenchidas." % len(tags))
        except Exception:
            log("    ⚠ não consegui preencher as tags (Show more/Tags) — siga sem elas ou ajuste o seletor.")

    _shot(page, "antes_next")

    # NEXT (Details → Video elements) → configura TELA FINAL + CARDS → NEXT×2 (→ Checks → Visibility).
    # São os mesmos 3 "Next" de antes; a diferença é parar na página "Video elements" (que antes
    # era só pulada) p/ adicionar a tela final e os cards.
    def _next():
        try:
            page.get_by_role("button", name="Next").click(timeout=10000)
            page.wait_for_timeout(1200)
            return True
        except Exception:
            return False

    if _next():                       # agora na página "Video elements"
        _shot(page, "video_elements")
        _configurar_elementos(page, log)
    for _ in range(2):                # → Checks → Visibility
        if not _next():
            break
    _shot(page, "visibility")

    # VISIBILITY → Schedule (data + hora no fuso do slot).
    log("    → agendando p/ %s…" % slot.strftime("%Y-%m-%d %H:%M %Z"))
    try:
        page.get_by_text("Schedule", exact=False).first.click(timeout=10000)
        page.wait_for_timeout(1000)
        _shot(page, "schedule_aberto")
        _definir_data_hora(page, slot, log)
    except Exception as e:  # noqa: BLE001
        _shot(page, "erro_schedule")
        raise ErroPipeline("não consegui abrir/definir o agendamento (Schedule): %s" % e)
    _shot(page, "schedule_preenchido")

    # Só bloqueia AQUI, no último momento: os metadados acima foram preenchidos EM PARALELO ao
    # envio do arquivo (esse tempo é de graça), então na prática costuma faltar pouco. O que não
    # pode é confirmar o agendamento e fechar o perfil com o envio pela metade.
    log("    → aguardando o upload terminar antes de confirmar…")
    _esperar_upload(page, log)

    if dry_run:
        log("    [dry-run] parando ANTES de confirmar o agendamento (nada foi publicado).")
        return ""

    # DONE / SCHEDULE (confirma).
    try:
        page.get_by_role("button", name="Schedule").click(timeout=8000)
    except Exception:
        try:
            page.get_by_role("button", name="Done").click(timeout=8000)
        except Exception:
            raise ErroPipeline("não achei o botão final (Schedule/Done) p/ confirmar.")
    page.wait_for_timeout(4000)

    # URL do vídeo (best-effort — o Studio mostra um link do vídeo agendado).
    try:
        link = page.get_by_role("link", name="youtu.be", exact=False).first
        return link.get_attribute("href") or ""
    except Exception:
        return ""


def _subir_thumbnail(page, thumb, log):
    """Sobe a thumbnail custom na página de Details (best-effort — nunca derruba o upload).

    O editor de thumbnail do Studio tem um <input type=file> PRÓPRIO, separado do input do
    vídeo. Tentamos primeiro pelo file chooser do botão 'Upload file' escopado no componente
    de thumbnail; se não rolar, setamos o arquivo direto no input do componente. Falha aqui só
    AVISA (o vídeo sobe com a capa automática do YouTube), no mesmo espírito das tags/legenda.

    ⚠ Requer canal VERIFICADO (thumbnail custom é recurso de conta verificada) e seletores em
    UI inglesa — recalibre no --dry-run se a UI do Studio mudar."""
    if not thumb or not Path(thumb).is_file():
        log("    ⚠ sem thumbnail p/ subir (%s) — vídeo sobe com a capa automática." % (thumb or "vazio"))
        return
    # Seletores do componente de thumbnail (variam entre versões do Studio).
    editores = ("ytcp-thumbnails-compact-editor", "ytcp-video-thumbnail-editor", "#thumbnail-uploader")
    # 1) botão 'Upload file' dentro do editor → abre um file chooser.
    try:
        editor = page.locator(", ".join(editores)).first
        with page.expect_file_chooser(timeout=6000) as fc:
            editor.get_by_text("Upload file", exact=False).first.click(timeout=6000)
        fc.value.set_files(thumb)
        page.wait_for_timeout(1500)
        log("    → thumbnail enviada (Upload file): %s" % Path(thumb).name)
        return
    except Exception:
        pass
    # 2) fallback: seta o arquivo direto no input[type=file] do componente de thumbnail.
    try:
        campo = page.locator(", ".join("%s input[type=file]" % e for e in editores)).first
        campo.set_input_files(thumb, timeout=8000)
        page.wait_for_timeout(1500)
        log("    → thumbnail enviada (input direto): %s" % Path(thumb).name)
        return
    except Exception as e:  # noqa: BLE001
        log("    ⚠ não consegui subir a thumbnail (%s) — ajuste o seletor no publicador." % e)


def _preencher_editbox(page, labels, valor, log, rotulo):
    """Preenche o 1º contenteditable/textbox achado por uma lista de aria-labels possíveis."""
    for lab in labels:
        try:
            campo = page.get_by_label(lab, exact=False).first
            campo.click(timeout=6000)
            humano.pausa(page, 250, 700)
            # contenteditable: limpa e digita (com cadência humana — ver humano.digitar)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            humano.digitar(page, campo, valor)
            log("    → %s preenchido." % rotulo)
            return
        except Exception:
            continue
    log("    ⚠ não consegui preencher %s (seletores: %s) — ajuste manualmente." % (rotulo, labels))


def _definir_data_hora(page, slot, log):
    """Preenche a data e a hora do agendamento. A UI do Studio abre um date-picker + campo de hora.

    Formato de data/hora depende do locale da conta — aqui usamos os formatos EN comuns
    (data 'Mon DD, YYYY' via digitação no input, hora 'H:MM AM/PM'). Pode precisar de ajuste."""
    data_txt = slot.strftime("%b %d, %Y")     # ex.: "Jul 10, 2026"
    hora_txt = slot.strftime("%I:%M %p").lstrip("0")  # ex.: "6:00 PM"
    # Campo de DATA
    try:
        campo_data = page.locator("#datepicker-trigger input, input[aria-label*='date' i]").first
        campo_data.click(timeout=6000)
        campo_data.fill(data_txt)
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
    except Exception:
        log("    ⚠ não consegui digitar a data (%s) — ajuste o seletor de data." % data_txt)
    # Campo de HORA
    try:
        campo_hora = page.locator("input[aria-label*='time' i], #time-of-day-trigger input").first
        campo_hora.click(timeout=6000)
        campo_hora.fill(hora_txt)
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
    except Exception:
        log("    ⚠ não consegui digitar a hora (%s) — ajuste o seletor de hora." % hora_txt)


# ---------------------------------------------------------------------------
# Video elements: TELA FINAL ("best for viewer") + CARDS (últimos vídeos do canal)
# ---------------------------------------------------------------------------
# ⚠ Este é o trecho MAIS FRÁGIL do publicador: a página "Video elements" do Studio usa
# editores com timeline/drag e não tem API pública. Os seletores abaixo são o ponto de partida
# e QUASE CERTAMENTE precisam de calibração ao vivo (rode `--dry-run` e olhe os screenshots em
# publicacao/_debug/: video_elements → endscreen_* → cards_*). Cada bloco é best-effort: se algo
# falha, só AVISA e segue (o vídeo é agendado mesmo sem tela final/cards). Liga/desliga por env.

def _flag(nome, default=True):
    v = os.environ.get(nome)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "nao", "não")


def _cards_qtd():
    try:
        return max(1, int(os.environ.get("LONGFORM_CARDS_QTD", "1")))
    except ValueError:
        return 1


def _clicar_primeiro(page, textos, timeout=4000):
    """Tenta clicar no 1º dos `textos` que existir na página. Devolve o texto que funcionou, ou None."""
    for t in textos:
        try:
            page.get_by_text(t, exact=False).first.click(timeout=timeout)
            return t
        except Exception:
            continue
    return None


def _salvar_editor(page):
    """Clica o botão de salvar/concluir do editor aberto (Save/Done)."""
    for nome in ("Save", "SAVE", "Done"):
        try:
            page.get_by_role("button", name=nome).click(timeout=4000)
            return True
        except Exception:
            continue
    return False


def _configurar_elementos(page, log):
    """Na página 'Video elements': adiciona a TELA FINAL e os CARDS conforme as envs.
    LONGFORM_ENDSCREEN (default 1), LONGFORM_CARDS (default 1), LONGFORM_CARDS_QTD (default 1)."""
    if _flag("LONGFORM_ENDSCREEN", True):
        _adicionar_tela_final(page, log)
    else:
        log("    → tela final desligada (LONGFORM_ENDSCREEN=0).")
    if _flag("LONGFORM_CARDS", True):
        _adicionar_cards(page, log, _cards_qtd())
    else:
        log("    → cards desligados (LONGFORM_CARDS=0).")


def _adicionar_tela_final(page, log):
    """Adiciona uma TELA FINAL com um elemento de vídeo 'Best for viewer' (o YouTube escolhe o
    melhor vídeo p/ cada espectador), sincronizada nos últimos segundos. Best-effort."""
    try:
        # 1) abre o editor de tela final (o rótulo varia entre versões do Studio)
        abriu = _clicar_primeiro(page, ["Add an end screen", "ADD END SCREEN", "End screen",
                                        "Add end screen", "Add element"], 6000)
        if not abriu:
            log("    ⚠ não achei o botão de tela final — ajuste o seletor (screenshot video_elements).")
            return
        page.wait_for_timeout(1500)
        _shot(page, "endscreen_editor")
        # 2) adiciona um elemento de VÍDEO no editor
        _clicar_primeiro(page, ["Video", "Add element", "ADD ELEMENT"], 4000)
        page.wait_for_timeout(800)
        # 3) escolhe "Best for viewer" (deixa o YouTube decidir o melhor vídeo)
        try:
            page.get_by_text("Best for viewer", exact=False).first.click(timeout=5000)
            log("    → tela final: elemento 'Best for viewer' adicionado.")
        except Exception:
            log("    ⚠ não achei 'Best for viewer' — a tela final pode não ter sido montada.")
        page.wait_for_timeout(800)
        _shot(page, "endscreen_montado")
        # 4) salva o editor da tela final
        _salvar_editor(page)
        page.wait_for_timeout(1200)
    except Exception as e:  # noqa: BLE001
        _shot(page, "erro_endscreen")
        log("    ⚠ não consegui configurar a tela final (%s) — segue sem ela." % e)


def _adicionar_cards(page, log, qtd):
    """Adiciona `qtd` CARD(s) de vídeo apontando pros vídeos do topo da lista do canal (mais
    recentes). Cards exigem um vídeo específico (não há 'auto-mais-recente' nativo), então
    pegamos o 1º da lista que o Studio mostra. Best-effort — pula sem erro se o canal ainda não
    tiver vídeos (1º upload de um canal do zero)."""
    try:
        abriu = _clicar_primeiro(page, ["Add cards", "ADD CARDS", "Cards", "Add card"], 5000)
        if not abriu:
            log("    ⚠ não achei o botão de cards — ajuste o seletor (screenshot video_elements).")
            return
        page.wait_for_timeout(1200)
        _shot(page, "cards_editor")
        adicionados = 0
        for _ in range(qtd):
            # escolhe o tipo "Video"
            if not _clicar_primeiro(page, ["Video"], 4000):
                break
            page.wait_for_timeout(1000)
            # seleciona o 1º vídeo da lista (o Studio ordena por mais recente)
            try:
                page.locator(
                    "ytcp-video-list-cell, ytcp-entity-card, "
                    "#video-list ytcp-ve, tp-yt-paper-dialog #contents ytcp-ve"
                ).first.click(timeout=4000)
                adicionados += 1
                page.wait_for_timeout(800)
            except Exception:
                # sem vídeos pra apontar (canal novo) — encerra sem erro
                break
        if adicionados:
            log("    → %d card(s) de vídeo (últimos do canal) adicionado(s)." % adicionados)
        else:
            log("    ⚠ nenhum card adicionado (canal sem vídeos ainda? ou seletor a calibrar).")
        _salvar_editor(page)
        page.wait_for_timeout(1000)
    except Exception as e:  # noqa: BLE001
        _shot(page, "erro_cards")
        log("    ⚠ não consegui configurar os cards (%s) — segue sem eles." % e)


# ---------------------------------------------------------------------------
# Orquestração de um item (AdsPower start → Playwright → stop)
# ---------------------------------------------------------------------------

def _publicar_item(item, log, no_gates=False, dry_run=False):
    if sync_playwright is None:
        raise ErroPipeline("Playwright não instalado: py -3 -m pip install playwright && "
                           "py -3 -m playwright install chromium")
    cat = item.get("categoria")
    user_id = categorias.adspower_user_id(cat)
    if not user_id:
        raise ErroPipeline("Canal '%s' sem perfil AdsPower configurado — preencha adspower_user_id "
                           "em categorias.py ou a env LONGFORM_ADSPOWER_%s."
                           % (item.get("canal"), categorias.resolver(cat).upper()))

    slot = agenda.proximo_slot(cat)
    slot_str = slot.strftime("%Y-%m-%d %H:%M %Z")

    # Gate 3 — aprovação/edição (grava edições de volta no publicacao.json).
    if not no_gates:
        dec = gates.gate_publicacao(item, slot_str, log)
        if not dec.get("approved"):
            return False  # pulado — fica na fila
    # (re)lê o publicacao.json já com as edições do gate
    meta = json.loads(Path(item["publicacao_json"]).read_text(encoding="utf-8"))

    log("  ▶ %s → canal %s (perfil AdsPower %s), slot %s" %
        (item["slug"], item.get("canal"), user_id, slot_str))
    info = adspower.start(user_id)
    url_video = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(info["cdp"])
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            url_video = _subir_no_studio(page, item, meta, slot, log, dry_run=dry_run)
            browser.close()  # só desconecta; não fecha o AdsPower
    finally:
        adspower.stop(user_id)

    if dry_run:
        log("    [dry-run] item mantido na fila (nada agendado).")
        return False
    agenda.reservar(cat, slot)
    _marcar_publicado(item, slot, url_video, log)
    return True


def drenar(no_gates=False, dry_run=False, slug=None, log=print, cancel=None):
    """Drena a fila de publicação: sobe+agenda cada item pendente no YouTube via AdsPower.

    É o núcleo reutilizável do worker (o `main()` só faz o parse de args e chama isto). A
    `esteira.py` chama esta função direto no fim de uma rodada em lote ("publicar a fila no
    fim"). `cancel` (threading.Event opcional) interrompe entre itens. Devolve quantos foram
    publicados/agendados. Um item que falha NÃO derruba os demais — fica na fila."""
    itens = _itens_fila(slug)
    if not itens:
        log("Fila vazia (nenhum item pendente em %s)." % FILA_DIR)
        return 0
    log("Fila: %d item(ns) pendente(s). Cadência: %s." % (len(itens), agenda.descrever_cadencia()))
    ok = 0
    for i, item in enumerate(itens):
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            log("Cancelado — interrompendo a publicação (itens restantes ficam na fila).")
            break
        if i > 0:
            humano.descanso(log, pular=dry_run)  # nunca abrir dois perfis AdsPower colados
        try:
            if _publicar_item(item, log, no_gates=no_gates, dry_run=dry_run):
                ok += 1
        except ErroPipeline as e:
            log("  ✖ %s falhou: %s" % (item.get("slug"), e))
        except Exception as e:  # noqa: BLE001
            log("  ✖ %s erro inesperado: %s" % (item.get("slug"), e))
    log("Concluído: %d publicado(s)/agendado(s)." % ok)
    return ok


def _bridge(user_id, log):
    """Teste da ponte: abre o perfil no AdsPower, conecta o Playwright e abre o Studio."""
    if sync_playwright is None:
        raise ErroPipeline("Playwright não instalado.")
    log("Abrindo perfil %s no AdsPower…" % user_id)
    info = adspower.start(user_id)
    log("CDP: %s" % info["cdp"])
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(info["cdp"])
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            log("Studio aberto. Título da página: %s" % page.title())
            logado = "studio.youtube.com" in page.url
            log("Logado no Studio? %s (URL: %s)" % ("sim" if logado else "TALVEZ NÃO", page.url))
            browser.close()
    finally:
        adspower.stop(user_id)


def main():
    forcar_utf8_console()
    ap = argparse.ArgumentParser(description="Publicador YouTube (AdsPower + Playwright).")
    ap.add_argument("--slug", help="publica só este item da fila")
    ap.add_argument("--no-gates", action="store_true", help="sem Gate 3 (100% automático)")
    ap.add_argument("--dry-run", action="store_true", help="faz tudo menos confirmar o agendamento")
    ap.add_argument("--bridge", metavar="USER_ID", help="só testa a ponte AdsPower+Playwright")
    args = ap.parse_args()

    def log(m):
        print(m, flush=True)

    if args.dry_run:
        global _SHOTS_DIR
        _SHOTS_DIR = PUBLICACAO_DIR / "_debug"
        log("[dry-run] screenshots de cada passo em: %s" % _SHOTS_DIR)

    if args.bridge:
        _bridge(args.bridge, log)
        return 0

    drenar(no_gates=args.no_gates, dry_run=args.dry_run, slug=args.slug, log=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
