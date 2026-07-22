# -*- coding: utf-8 -*-
"""gerar-longform.py — app one-click da esteira long-form (YouTube 16:9).

Visual moderno (tema escuro), sem terminal anexo. Você informa o card do ClickUp
("Alpha King") ou um projeto existente (--slug), marca as etapas e clica "Gerar".
Os 2 gates (aprovar roteiro / escolher thumb) abrem no navegador. As etapas criativas
rodam via Claude Code headless (seu login, sem API paga).

Uso:
    pyw -3 gerar-longform.py                -> abre a GUI (sem terminal)
    pyw -3 gerar-longform.py "Alpha King"   -> GUI já com o card preenchido
    (CLI puro: use pipeline.py)
"""

import os
import sys
import threading
from pathlib import Path

import config  # noqa: F401  (efeito colateral: liga TTS/Magnific via os.environ)
import categorias
import pipeline as pl
import esteira
from common import (PROJECTS_DIR, projeto_por_slug, projeto_mais_recente, slugify,
                    achar_pasta_projeto)
from stages import magnific_seam


# ──────────────────────────── paleta + tipografia ────────────────────────────
BG        = "#0f1115"   # fundo da janela
SURFACE   = "#171a21"   # cards/inputs
SURFACE_2 = "#1e222b"   # hover/log
BORDER    = "#262b36"
TEXT      = "#e6e9ef"
TEXT_DIM  = "#8b93a7"
TEXT_MUTE = "#5b6273"
ACCENT    = "#ff5c8a"   # rosa romance — combina com o tema
ACCENT_2  = "#b35bff"   # roxo
OK        = "#36d399"
WARN      = "#f59e0b"
ERR       = "#ef4444"

FONT_UI    = ("Segoe UI", 10)
FONT_UI_B  = ("Segoe UI Semibold", 10)
FONT_TITLE = ("Segoe UI Semibold", 16)
FONT_SUB   = ("Segoe UI", 9)
FONT_MONO  = ("Consolas", 9)


def _aplicar_tema(root, ttk):
    """Tema escuro custom no ttk + defaults do Tk."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # único tema do ttk que aceita override pleno de cores
    except Exception:
        pass

    root.configure(bg=BG)
    root.option_add("*Font", FONT_UI)

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, borderwidth=0)
    style.configure("Surface.TFrame", background=SURFACE)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
    style.configure("Sub.TLabel", background=BG, foreground=TEXT_DIM, font=FONT_SUB)
    style.configure("CardLbl.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("CardSub.TLabel", background=SURFACE, foreground=TEXT_DIM, font=FONT_SUB)
    style.configure("Mute.TLabel", background=BG, foreground=TEXT_MUTE, font=FONT_SUB)

    style.configure(
        "TEntry",
        fieldbackground=SURFACE_2,
        background=SURFACE_2,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=TEXT,
        padding=6,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )

    style.configure(
        "TCheckbutton",
        background=SURFACE,
        foreground=TEXT,
        focuscolor=SURFACE,
        indicatorbackground=SURFACE_2,
        indicatorforeground=ACCENT,
        padding=4,
    )
    style.map(
        "TCheckbutton",
        background=[("active", SURFACE)],
        foreground=[("disabled", TEXT_MUTE)],
        indicatorbackground=[("selected", ACCENT), ("active", SURFACE_2)],
        indicatorforeground=[("selected", "#ffffff")],
    )

    style.configure(
        "Primary.TButton",
        background=ACCENT,
        foreground="#ffffff",
        font=FONT_UI_B,
        padding=(18, 9),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "Primary.TButton",
        background=[("active", "#ff7aa1"), ("disabled", "#4a2935")],
        foreground=[("disabled", TEXT_MUTE)],
    )

    style.configure(
        "Secondary.TButton",
        background=SURFACE_2,
        foreground=TEXT,
        font=FONT_UI_B,
        padding=(14, 9),
        borderwidth=1,
        focusthickness=0,
    )
    style.map(
        "Secondary.TButton",
        background=[("active", "#2a2f3c"), ("disabled", SURFACE)],
        foreground=[("disabled", TEXT_MUTE)],
        bordercolor=[("!active", BORDER), ("active", ACCENT)],
    )

    style.configure(
        "Danger.TButton",
        background=SURFACE_2,
        foreground=ERR,
        font=FONT_UI_B,
        padding=(14, 9),
        borderwidth=1,
        focusthickness=0,
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#2a1c1c"), ("disabled", SURFACE)],
        foreground=[("disabled", TEXT_MUTE)],
        bordercolor=[("!active", BORDER), ("active", ERR)],
    )

    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_2,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=TEXT_DIM,
        gripcount=0,
    )
    style.map("Vertical.TScrollbar", background=[("active", "#2a2f3c")])

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE_2,
        background=SURFACE_2,
        foreground=TEXT,
        arrowcolor=TEXT_DIM,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=TEXT,
        padding=6,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE_2), ("disabled", SURFACE)],
        foreground=[("disabled", TEXT_MUTE)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
        arrowcolor=[("active", TEXT)],
    )
    # O popup do Combobox é uma Listbox Tk pura — cor só via option_add.
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT_SUB)


def _card(parent, ttk, **pack):
    """Cria um 'card' (frame com fundo SURFACE) e devolve o frame interno com padding."""
    import tkinter as tk
    outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
    outer.pack(**pack)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=14)
    inner.pack(fill="both", expand=True)
    return inner


def rodar_gui(card_inicial=""):
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title("Long-form — Automação de Vídeo")
    root.geometry("980x820")
    root.minsize(860, 560)

    _aplicar_tema(root, ttk)

    var_card = tk.StringVar(value=card_inicial or "Alpha King")
    var_slug = tk.StringVar(value="")
    var_hint = tk.StringVar(value="")
    # Categoria (= franquia/board do ClickUp). Filtra a lista de cards à List da categoria
    # e é passada ao pipeline (que anexa a capa de volta no card escolhido).
    cat_key_por_label = {label: key for key, label in categorias.labels()}
    cat_labels = [label for _, label in categorias.labels()]
    var_categoria = tk.StringVar(value=categorias.label_de(categorias.PADRAO))
    categorias.aplicar(categorias.PADRAO)  # fixa a List padrão antes de listar os vídeos
    vars_etapas = {i: tk.BooleanVar(value=True) for i in pl.TODAS}
    # Modo automático (sem gates) LIGADO por padrão (2026-07-10): a operação normal é gerar
    # em lote sem parar pra aprovar — o roteiro é aprovado sozinho (Gate 1) e a thumb é
    # auto-escolhida (Gate 2). Desmarque só quando quiser revisar roteiro/thumb à mão.
    var_nogates = tk.BooleanVar(value=True)
    # Caixa "Vídeo em português": MODO TESTE — gera roteiro/narração/legenda em pt-BR pra
    # equipe avaliar a história. Desmarcada = conversão original (inglês). As imagens não mudam.
    var_pt = tk.BooleanVar(value=False)
    # Caixa "Roteiro pronto no card": pula a geração (Etapa 2) e usa o roteiro do Doc (Google
    # Doc / ClickUp Doc) linkado no card — pra adiantar demandas com o roteiro já escrito.
    var_roteiro_pronto = tk.BooleanVar(value=False)
    # Caixa "Publicar no YouTube ao terminar a esteira": após gerar TODOS os vídeos da
    # categoria, drena a fila no YouTube via AdsPower. Default DESMARCADA — publicar abre os
    # perfis do AdsPower (ao vivo/compartilhados), então é um opt-in explícito por rodada.
    var_publicar_fim = tk.BooleanVar(value=False)
    parar = threading.Event()
    estado = {"slug": None}
    # Dropdown de vídeos do ClickUp: título exibido -> {"id", "name", "url", ...}.
    # Populado em background por clickup_api.listar_videos_disponiveis() (só os NÃO-concluídos).
    videos_por_titulo = {}

    # Modelos ILIMITADOS p/ as imagens do CORPO do vídeo (Etapa 7) — vêm da whitelist
    # curada em magnific_seam.MODOS_BODY (todos com trava de personagem + 16:9). O rótulo
    # exibido mapeia para o identifier REAL passado ao Magnific via LONGFORM_MAGNIFIC_MODE.
    modelo_por_label = {}
    modelo_labels = []
    for alias, ident, lat, nota in magnific_seam.listar_modos_body():
        rotulo = "%s  ·  %s  ·  %s" % (alias, lat, nota)
        modelo_por_label[rotulo] = ident
        modelo_labels.append(rotulo)
    _modo_atual = magnific_seam.modo()
    _label_atual = next((r for r, i in modelo_por_label.items() if i == _modo_atual), None)
    if _label_atual is None:
        # configurado fora da whitelist (env/longform.env) — mostra como opção "custom".
        _label_atual = "%s  ·  (atual, fora da whitelist)" % _modo_atual
        modelo_por_label[_label_atual] = _modo_atual
        modelo_labels.insert(0, _label_atual)
    var_modelo = tk.StringVar(value=_label_atual)

    raiz = ttk.Frame(root, padding=20)
    raiz.pack(fill="both", expand=True)

    # ── Rodapé fixo (LOG) + topo rolável (conteúdo) ───────────────────────────
    # O LOG fica SEMPRE visível, ancorado no rodapé com altura garantida; tudo
    # acima (entrada/etapas/ações) vai para uma área que ROLA quando não cabe na
    # janela — antes o log era empurrado para fora da tela em janelas baixas.
    log_host = ttk.Frame(raiz, style="TFrame")
    log_host.pack(side="bottom", fill="x", pady=(12, 0))

    _scroll = ttk.Frame(raiz, style="TFrame")
    _scroll.pack(side="top", fill="both", expand=True)
    _canvas = tk.Canvas(_scroll, bg=BG, highlightthickness=0)
    _vbar = ttk.Scrollbar(
        _scroll, orient="vertical", command=_canvas.yview, style="Vertical.TScrollbar"
    )
    _canvas.configure(yscrollcommand=_vbar.set)
    _vbar.pack(side="right", fill="y")
    _canvas.pack(side="left", fill="both", expand=True)
    conteudo = ttk.Frame(_canvas, style="TFrame")
    _win = _canvas.create_window((0, 0), window=conteudo, anchor="nw")
    conteudo.bind(
        "<Configure>", lambda e: _canvas.configure(scrollregion=_canvas.bbox("all"))
    )
    _canvas.bind("<Configure>", lambda e: _canvas.itemconfigure(_win, width=e.width))

    def _rolar(e):
        # Não sequestrar a roda quando o ponteiro está sobre o LOG (ele rola sozinho).
        w = root.winfo_containing(e.x_root, e.y_root)
        while w is not None:
            if w == log_host:
                return
            w = getattr(w, "master", None)
        _canvas.yview_scroll(int(-e.delta / 120), "units")

    _canvas.bind_all("<MouseWheel>", _rolar)

    # ─────────────────────────────── Cabeçalho ───────────────────────────────
    hdr = ttk.Frame(conteudo)
    hdr.pack(fill="x", pady=(0, 14))
    hdr.columnconfigure(0, weight=1)

    ttk.Label(hdr, text="Long-form Studio", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        hdr,
        text="ClickUp  →  Roteiro  →  Narração  →  Thumb  →  Imagens  →  Montagem",
        style="Sub.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    status_canvas = tk.Canvas(hdr, width=130, height=28, bg=BG, highlightthickness=0)
    status_canvas.grid(row=0, column=1, rowspan=2, sticky="e")

    def _set_status(texto, cor):
        status_canvas.delete("all")
        w, h = 130, 24
        r = 12
        status_canvas.create_oval(0, 2, 2 * r, 2 + 2 * r, fill=SURFACE, outline=BORDER)
        status_canvas.create_oval(w - 2 * r, 2, w, 2 + 2 * r, fill=SURFACE, outline=BORDER)
        status_canvas.create_rectangle(r, 2, w - r, 2 + 2 * r, fill=SURFACE, outline="")
        status_canvas.create_line(r, 2, w - r, 2, fill=BORDER)
        status_canvas.create_line(r, 2 + 2 * r, w - r, 2 + 2 * r, fill=BORDER)
        status_canvas.create_oval(12, 9, 22, 19, fill=cor, outline="")
        status_canvas.create_text(75, 14, text=texto, fill=TEXT, font=FONT_SUB)

    _set_status("pronto", TEXT_DIM)

    # ────────────────────────── Card 1 — Entrada ─────────────────────────────
    inputs = _card(conteudo, ttk, fill="x", pady=(0, 12))
    inputs.columnconfigure(1, weight=1)

    ttk.Label(inputs, text="ENTRADA", style="CardSub.TLabel").grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
    )

    # Único campo de entrada: o dropdown do ClickUp. `var_slug`/`var_hint` continuam
    # existindo (default vazio) para o "Continuar" e a busca por nome via CLI, mas saíram
    # da tela — no fluxo do dropdown o card_id exato torna a "Dica da List" desnecessária,
    # e o "Continuar" já cai sozinho no último projeto quando o slug está vazio.
    # Linha 1 — categoria (filtra a lista de cards à List da categoria).
    ttk.Label(inputs, text="Categoria", style="CardLbl.TLabel").grid(
        row=1, column=0, sticky="w", padx=(0, 12), pady=4
    )
    combo_categoria = ttk.Combobox(
        inputs, textvariable=var_categoria, values=cat_labels, state="readonly"
    )
    combo_categoria.grid(row=1, column=1, sticky="ew", pady=4)
    # Linha 2 — dropdown de vídeos disponíveis do ClickUp (não-concluídos) + atualizar.
    ttk.Label(inputs, text="Vídeo do ClickUp", style="CardLbl.TLabel").grid(
        row=2, column=0, sticky="w", padx=(0, 12), pady=4
    )
    combo_card = ttk.Combobox(inputs, textvariable=var_card, values=[], state="normal")
    combo_card.grid(row=2, column=1, sticky="ew", pady=4)
    btn_refresh = ttk.Button(inputs, text="↻", style="Secondary.TButton", width=3)
    btn_refresh.grid(row=2, column=2, sticky="w", padx=(10, 0))

    # ────────────────────────── Card 2 — Etapas ──────────────────────────────
    etapas_card = _card(conteudo, ttk, fill="x", pady=(0, 12))

    ttk.Label(etapas_card, text="ETAPAS DO PIPELINE", style="CardSub.TLabel").pack(
        anchor="w", pady=(0, 10)
    )

    grid = ttk.Frame(etapas_card, style="Card.TFrame")
    grid.pack(fill="x")
    for c in range(4):
        grid.columnconfigure(c, weight=1, uniform="et")

    nomes = {
        1: "1 · ClickUp",
        2: "2 · Roteiro",
        3: "3 · Validar",
        4: "4 · Narração + SRT",
        5: "5 · Style / Thumb prompts",
        6: "6 · Thumbs",
        7: "7 · Imagens",
        8: "8 · Montagem (FFmpeg + Remotion)",
        9: "9 · Publicação (metadados + fila)",
    }
    for idx, i in enumerate(pl.TODAS):
        r, c = divmod(idx, 4)
        ttk.Checkbutton(grid, text=nomes[i], variable=vars_etapas[i], style="TCheckbutton").grid(
            row=r, column=c, sticky="w", padx=(0, 6), pady=4
        )

    ttk.Separator(etapas_card, orient="horizontal").pack(fill="x", pady=10)

    ttk.Checkbutton(
        etapas_card,
        text="Modo automático (sem gates — aprova roteiro e escolhe a thumb sozinho)",
        variable=var_nogates,
        style="TCheckbutton",
    ).pack(anchor="w")

    ttk.Checkbutton(
        etapas_card,
        text="Vídeo em português (teste — pra equipe avaliar a história)",
        variable=var_pt,
        style="TCheckbutton",
    ).pack(anchor="w", pady=(2, 0))
    ttk.Label(
        etapas_card,
        text=(
            "Marcado = roteiro, narração e legenda em pt-BR (as imagens não mudam — direção "
            "visual é sempre em inglês). Desmarque pra voltar à conversão original (inglês)."
        ),
        style="CardSub.TLabel",
        justify="left",
    ).pack(anchor="w", pady=(2, 0))

    ttk.Checkbutton(
        etapas_card,
        text="Roteiro pronto no card (puxa o Doc linkado — pula a geração)",
        variable=var_roteiro_pronto,
        style="TCheckbutton",
    ).pack(anchor="w", pady=(8, 0))
    ttk.Label(
        etapas_card,
        text=(
            "Marcado = a Etapa 2 NÃO gera roteiro; em vez disso usa o roteiro do Google Doc / "
            "ClickUp Doc linkado no card (deixe o Google Doc como 'qualquer pessoa com o link "
            "pode ver'). Bom pra adiantar demandas com o roteiro já escrito."
        ),
        style="CardSub.TLabel",
        justify="left",
    ).pack(anchor="w", pady=(2, 0))

    ttk.Checkbutton(
        etapas_card,
        text="Publicar no YouTube ao terminar a esteira (via AdsPower)",
        variable=var_publicar_fim,
        style="TCheckbutton",
    ).pack(anchor="w", pady=(8, 0))
    ttk.Label(
        etapas_card,
        text=(
            "Só vale para o botão '▶▶ Rodar esteira'. Marcado = depois de gerar TODOS os vídeos "
            "da categoria, sobe/agenda a fila no YouTube (abre os perfis do AdsPower). "
            "Desmarcado = só gera; você publica depois no botão 'Publicar fila'."
        ),
        style="CardSub.TLabel",
        justify="left",
    ).pack(anchor="w", pady=(2, 0))

    # ── Modelo das imagens do CORPO do vídeo (Etapa 7) — dropdown ──────────────
    modelo_box = ttk.Frame(etapas_card, style="Card.TFrame")
    modelo_box.pack(fill="x", pady=(12, 0))
    ttk.Label(
        modelo_box, text="Modelo das imagens do vídeo (Etapa 7)", style="CardLbl.TLabel"
    ).pack(anchor="w")
    ttk.Combobox(
        modelo_box, textvariable=var_modelo, values=modelo_labels, state="readonly"
    ).pack(fill="x", pady=(4, 0))
    ttk.Label(
        modelo_box,
        text=(
            "Todos ILIMITADOS (Premium+), com trava de personagem (Library) + 16:9.\n"
            "A thumb/capa (Etapa 6) usa modelo próprio (GPT 2) — este só vale para as imagens do corpo."
        ),
        style="CardSub.TLabel",
        justify="left",
    ).pack(anchor="w", pady=(4, 0))

    ttk.Label(
        etapas_card,
        text=(
            "Modo automático LIGADO (padrão): roteiro e thumb são aprovados sozinhos — nada abre.\n"
            "Desmarque 'Modo automático' se quiser revisar o roteiro (após 3) e a thumb (após 6) no navegador.\n"
            "Modelos: roteiro/validar = Opus · resto = Sonnet · Magnific (6,7) e TTS (4) precisam estar conectados."
        ),
        style="CardSub.TLabel",
        justify="left",
    ).pack(anchor="w", pady=(8, 0))

    # ────────────────────────── Card 3 — Ações ───────────────────────────────
    acoes_card = _card(conteudo, ttk, fill="x", pady=(0, 12))

    linha = ttk.Frame(acoes_card, style="Card.TFrame")
    linha.pack(fill="x")

    btn = ttk.Button(linha, text="▶  Gerar", style="Primary.TButton")
    btn.pack(side="left")
    btn_esteira = ttk.Button(linha, text="▶▶  Rodar esteira", style="Primary.TButton")
    btn_esteira.pack(side="left", padx=(8, 0))
    btn_todas = ttk.Button(linha, text="▶▶▶  Gerar TUDO", style="Primary.TButton")
    btn_todas.pack(side="left", padx=(8, 0))
    btn_continuar = ttk.Button(linha, text="⏭  Continuar", style="Secondary.TButton")
    btn_continuar.pack(side="left", padx=(8, 0))
    btn_refazer = ttk.Button(linha, text="♻  Refazer tudo", style="Danger.TButton")
    btn_refazer.pack(side="left", padx=(8, 0))
    btn_cancel = ttk.Button(linha, text="■  Cancelar", style="Danger.TButton", state="disabled")
    btn_cancel.pack(side="left", padx=(8, 0))
    btn_pasta = ttk.Button(linha, text="📂  Abrir pasta", style="Secondary.TButton")
    btn_pasta.pack(side="left", padx=(8, 0))
    btn_sync = ttk.Button(linha, text="🔄  Sincronizar fila", style="Secondary.TButton")
    btn_sync.pack(side="left", padx=(8, 0))
    btn_publicar = ttk.Button(linha, text="⬆  Publicar fila", style="Secondary.TButton")
    btn_publicar.pack(side="left", padx=(8, 0))

    ttk.Label(
        acoes_card,
        text=(
            "Gerar = faz só o vídeo selecionado no dropdown.\n"
            "Rodar esteira = faz TODOS os cards não-concluídos da CATEGORIA escolhida, um por vez, "
            "automático (sem gates).\n"
            "Gerar TUDO = percorre TODAS as categorias (todos os canais) e gera tudo que está "
            "pendente, um por vez, automático — o clique único pra deixar rodando. Marque 'Publicar "
            "no YouTube ao terminar' para subir a fila no fim (senão só gera; você posta depois).\n"
            "Continuar = retoma o projeto de onde parou (pula o que já ficou pronto).\n"
            "Refazer tudo = APAGA o que já foi gerado (roteiro, narração, thumb, imagens, vídeo) "
            "e gera de novo do zero (o card do ClickUp é mantido).\n"
            "Abrir pasta = abre a entrega (ENTREGAS/<Categoria>/<Card>/) do projeto no Explorer."
        ),
        style="CardSub.TLabel",
        justify="left",
    ).pack(anchor="w", pady=(10, 0))

    # ──────────────── Card 4 — Log (rodapé FIXO, sempre visível) ──────────────
    log_card = _card(log_host, ttk, fill="both")

    cabec_log = ttk.Frame(log_card, style="Card.TFrame")
    cabec_log.pack(fill="x", pady=(0, 6))
    ttk.Label(cabec_log, text="LOG", style="CardSub.TLabel").pack(side="left")

    def _limpar_log():
        log_txt.config(state="normal")
        log_txt.delete("1.0", "end")
        log_txt.config(state="disabled")

    btn_clear = ttk.Button(cabec_log, text="limpar", style="Secondary.TButton", command=_limpar_log)
    btn_clear.pack(side="right")

    log_wrap = tk.Frame(log_card, bg=BORDER, padx=1, pady=1)
    log_wrap.pack(fill="both", expand=True)
    log_inner = tk.Frame(log_wrap, bg=SURFACE_2)
    log_inner.pack(fill="both", expand=True)

    log_txt = tk.Text(
        log_inner,
        height=14,
        wrap="word",
        state="disabled",
        font=FONT_MONO,
        bg=SURFACE_2,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        borderwidth=0,
        padx=12,
        pady=10,
        selectbackground=ACCENT_2,
        selectforeground="#ffffff",
    )
    log_txt.pack(side="left", fill="both", expand=True)
    sc = ttk.Scrollbar(log_inner, command=log_txt.yview, style="Vertical.TScrollbar")
    sc.pack(side="right", fill="y")
    log_txt.config(yscrollcommand=sc.set)

    log_txt.tag_configure("ok", foreground=OK)
    log_txt.tag_configure("warn", foreground=WARN)
    log_txt.tag_configure("err", foreground=ERR)
    log_txt.tag_configure("dim", foreground=TEXT_DIM)

    def log(msg=""):
        s = str(msg)
        tag = None
        low = s.lstrip().lower()
        if low.startswith(("✓", "✔", "ok", "pronto")) or "concluíd" in low:
            tag = "ok"
        elif low.startswith(("⚠", "aviso", "warning")):
            tag = "warn"
        elif low.startswith(("❌", "erro", "error")) or low.startswith("[erro"):
            tag = "err"
        elif low.startswith(("→", "·", "—", "   ", "info")):
            tag = "dim"

        def _a():
            log_txt.config(state="normal")
            if tag:
                log_txt.insert("end", s + "\n", tag)
            else:
                log_txt.insert("end", s + "\n")
            log_txt.see("end")
            log_txt.config(state="disabled")

        root.after(0, _a)

    def fim(ok, err):
        def _u():
            btn.config(state="normal")
            btn_esteira.config(state="normal")
            btn_todas.config(state="normal")
            btn_refazer.config(state="normal")
            btn_continuar.config(state="normal")
            btn_cancel.config(state="disabled")
            if ok:
                _set_status("concluído", OK)
                onde = ""
                try:
                    from entrega import ENTREGAS_DIR
                    p = _pasta_entrega_atual()
                    if p and ENTREGAS_DIR in Path(p).parents:
                        partes = Path(p).relative_to(ENTREGAS_DIR).parts
                        onde = "\n\n📂 " + " › ".join(partes)
                except Exception:  # noqa: BLE001
                    pass
                if messagebox.askyesno(
                    "Pronto",
                    "Vídeo concluído! Abrir a pasta da entrega — organizada por "
                    "categoria › card — agora?" + onde,
                ):
                    abrir_pasta()
            elif err:
                _set_status("erro", ERR)
                messagebox.showerror("Erro", str(err))
            else:
                _set_status("cancelado", WARN)

        root.after(0, _u)

    # ── Dropdown do ClickUp: cache instantâneo + atualização em 2º plano ──────────
    def _preencher_combo(vids):
        videos_por_titulo.clear()
        titulos = []
        for v in vids:
            videos_por_titulo[v["name"]] = v
            titulos.append(v["name"])
        combo_card["values"] = titulos
        if titulos and var_card.get().strip() not in videos_por_titulo:
            var_card.set(titulos[0])
        return len(titulos)

    def _aplicar_videos(vids, err, tinha_cache=False):
        if err:
            log("⚠ Não consegui atualizar a lista do ClickUp: %s" % err)
            if tinha_cache:
                log("   (mantendo a última lista; clique ↻ para tentar de novo)")
            else:
                log("   (configure LONGFORM_CLICKUP_TOKEN no longform.env p/ ficar instantâneo, "
                    "ou clique ↻; dá p/ digitar o nome do card à mão também)")
            btn_refresh.config(state="normal")
            return
        n = _preencher_combo(vids)
        log("✓ %d vídeo(s) disponível(is) no ClickUp (concluídos ocultos)." % n)
        btn_refresh.config(state="normal")

    def carregar_videos(force=False):
        import clickup_api
        # 1) Mostra o cache NA HORA (sem esperar nada).
        cached, idade = clickup_api.cache_ler()
        tem_cache = bool(cached)
        if tem_cache:
            _preencher_combo(cached)
        # 2) Se o cache é recente e não foi forçado, nem atualiza (instantâneo, sem custo).
        if not force and tem_cache and idade is not None and idade < clickup_api.cache_ttl():
            log("✓ %d vídeo(s) na lista (cache de %d min). Clique ↻ para atualizar agora."
                % (len(cached), int(idade // 60)))
            btn_refresh.config(state="normal")
            return
        # 3) Atualiza em segundo plano (o cache, se houver, já está visível).
        btn_refresh.config(state="disabled")
        log("⟳ Atualizando a lista do ClickUp em segundo plano…" if tem_cache
            else "⟳ Carregando vídeos do ClickUp (pode levar ~1 min na 1ª vez)…")

        def _bg():
            try:
                vids = clickup_api.listar_videos(log=log, cancel=parar)
            except Exception as e:  # noqa: BLE001
                root.after(0, lambda e=e: _aplicar_videos(None, str(e), tinha_cache=tem_cache))
                return
            root.after(0, lambda: _aplicar_videos(vids, None))

        threading.Thread(target=_bg, daemon=True).start()

    def worker(continuar, refazer=False):
        ok, err = False, None
        try:
            etapas = [i for i in pl.TODAS if vars_etapas[i].get()]
            slug = var_slug.get().strip() or None
            # Categoria escolhida -> fixa a List do ClickUp (fonte dos cards + anexo da capa).
            cat_key = cat_key_por_label.get(var_categoria.get(), categorias.PADRAO)
            categorias.aplicar(cat_key)
            # Resolve o card escolhido no dropdown -> id exato (busca determinística na Etapa 1).
            titulo_sel = var_card.get().strip()
            sel = videos_por_titulo.get(titulo_sel)
            card_id = sel["id"] if sel else None
            card_nome = sel["name"] if sel else titulo_sel

            # Aplica o modelo escolhido no dropdown (imagens do corpo, Etapa 7 + fichas da E6).
            os.environ["LONGFORM_MAGNIFIC_MODE"] = modelo_por_label.get(
                var_modelo.get(), _modo_atual
            )
            log("   Modelo das imagens (Etapa 7): %s" % os.environ["LONGFORM_MAGNIFIC_MODE"])

            # Idioma do conteúdo (roteiro/narração/legenda). Caixa "Vídeo em português".
            os.environ["LONGFORM_IDIOMA"] = "pt" if var_pt.get() else "en"
            if var_pt.get():
                log("   🇧🇷 MODO PORTUGUÊS ligado (teste): roteiro, narração e legenda em pt-BR. "
                    "As imagens seguem em inglês (direção visual).")

            if continuar:
                # Qual projeto retomar (prioridade, maior vence):
                #   1) --slug explícito (CLI/campo), se houver;
                #   2) o VÍDEO escolhido no dropdown — DESDE QUE já exista a pasta
                #      projects/<slug>/. Assim "escolher o vídeo 2 + Continuar" retoma o
                #      vídeo 2, e não o "modificado mais recentemente" (que podia ser outro
                #      card incompleto). É o que a usuária espera ao olhar o dropdown.
                #   2b) card escolhido MAS sem pasta ainda NESTE canal -> RECUSA (card novo: use
                #       'Gerar'). A checagem é ESTRITA ao canal da categoria escolhida (canal_sel):
                #       como slugs colidem entre canais (Máfia 1/2/3/4 reusam os mesmos cards), sem
                #       isso o "Continuar" acharia o projeto de OUTRO canal e retomaria o vídeo
                #       errado. Passar `canal=` força a busca só em projects/<canal>/<slug>.
                #   3) sem card escolhido: o último projeto desta sessão da GUI (estado);
                #   4) sem card e sem estado: o projeto modificado mais recentemente (histórico).
                canal_sel = categorias.pasta_canal(cat_key)
                slug_card = slugify(card_nome) if card_nome else None
                if not slug and slug_card and achar_pasta_projeto(slug_card, canal=canal_sel) is not None:
                    slug = slug_card
                    log("   ▶ Retomando o vídeo escolhido no dropdown: %s" % slug)
                elif not slug and slug_card:
                    # Card escolhido no dropdown mas ainda não existe projeto pra ele.
                    raise RuntimeError(
                        "O vídeo '%s' ainda não foi gerado (não existe a pasta 'projects/%s'). "
                        "'Continuar' só retoma projetos que já começaram — para criar este do "
                        "zero, use o botão 'Gerar'." % (card_nome, slug_card)
                    )
                elif not slug:
                    slug = estado.get("slug") or projeto_mais_recente()
                if not slug:
                    raise RuntimeError(
                        "Nenhum projeto para continuar. Rode 'Gerar' antes "
                        "ou informe o slug do projeto existente."
                    )
                proj = projeto_por_slug(slug)
                estado["slug"] = slug
                pendentes = proj.etapas_pendentes(etapas)
                log("⏭ Continuando o projeto: %s" % slug)
                prontas = [i for i in etapas if i not in pendentes]
                if prontas:
                    log("   Já prontas (puladas): %s" % ", ".join(map(str, prontas)))
                if not pendentes:
                    log("   Nada pendente nas etapas marcadas — projeto já está completo. ✓")
                    ok = True
                    return
                log("   A executar: %s" % ", ".join(map(str, pendentes)))
                pl.pipeline(
                    slug, pendentes, log, parar,
                    slug=slug, card_query=card_nome, card_id=card_id,
                    list_hint=var_hint.get().strip() or None, categoria=cat_key,
                    pular_gates=var_nogates.get(), roteiro_pronto=var_roteiro_pronto.get(),
                    on_proj=lambda p: estado.update(slug=p.dir.name),
                )
            else:
                if refazer:
                    log("♻ Refazer tudo: vou apagar os artefatos e regenerar do zero.")
                pl.pipeline(
                    card_nome, etapas, log, parar,
                    slug=slug, card_query=card_nome, card_id=card_id,
                    list_hint=var_hint.get().strip() or None, categoria=cat_key,
                    pular_gates=var_nogates.get(), roteiro_pronto=var_roteiro_pronto.get(),
                    on_proj=lambda p: estado.update(slug=p.dir.name),
                    refazer=refazer,
                )
            ok = True
        except Exception as e:  # noqa: BLE001
            err = e
            log("")
            log("❌ %s" % e)
        finally:
            fim(ok, err)

    def worker_esteira():
        """Roda a esteira INTEIRA da categoria escolhida (todos os cards não-concluídos),
        automático (sem gates). Opcionalmente publica a fila no fim."""
        ok, err = False, None
        try:
            cat_key = cat_key_por_label.get(var_categoria.get(), categorias.PADRAO)

            # Mesma configuração de ambiente do worker de 1 card: modelo das imagens + idioma.
            os.environ["LONGFORM_MAGNIFIC_MODE"] = modelo_por_label.get(
                var_modelo.get(), _modo_atual)
            log("   Modelo das imagens (Etapa 7): %s" % os.environ["LONGFORM_MAGNIFIC_MODE"])
            os.environ["LONGFORM_IDIOMA"] = "pt" if var_pt.get() else "en"
            if var_pt.get():
                log("   🇧🇷 MODO PORTUGUÊS ligado (teste): roteiro, narração e legenda em pt-BR.")

            esteira.rodar_esteira(
                cat_key, log=log, cancel=parar,
                pular_gates=True,  # esteira em lote = sempre automático
                publicar_no_fim=var_publicar_fim.get(),
                roteiro_pronto=var_roteiro_pronto.get(),
                on_proj=lambda p: estado.update(slug=p.dir.name),
            )
            ok = True
        except Exception as e:  # noqa: BLE001
            err = e
            log("")
            log("❌ %s" % e)
        finally:
            fim(ok, err)

    def worker_todas():
        """META-ESTEIRA: gera TUDO de TODAS as categorias, uma após a outra (o clique único).
        Sempre automático (sem gates). Publica no fim só se a checkbox estiver marcada."""
        ok, err = False, None
        try:
            # Mesma configuração de ambiente das outras esteiras: modelo das imagens + idioma.
            os.environ["LONGFORM_MAGNIFIC_MODE"] = modelo_por_label.get(
                var_modelo.get(), _modo_atual)
            log("   Modelo das imagens (Etapa 7): %s" % os.environ["LONGFORM_MAGNIFIC_MODE"])
            os.environ["LONGFORM_IDIOMA"] = "pt" if var_pt.get() else "en"
            if var_pt.get():
                log("   🇧🇷 MODO PORTUGUÊS ligado (teste): roteiro, narração e legenda em pt-BR.")

            esteira.rodar_todas(
                log=log, cancel=parar,
                pular_gates=True,  # gerar tudo em lote = sempre automático
                publicar_no_fim=var_publicar_fim.get(),
                roteiro_pronto=var_roteiro_pronto.get(),
                on_proj=lambda p: estado.update(slug=p.dir.name),
            )
            ok = True
        except Exception as e:  # noqa: BLE001
            err = e
            log("")
            log("❌ %s" % e)
        finally:
            fim(ok, err)

    def iniciar_todas():
        publicar = var_publicar_fim.get()
        cats = ", ".join(lbl for _, lbl in categorias.labels())
        msg = (
            "GERAR TUDO — todas as categorias?\n\n"
            "Vou percorrer TODAS as categorias (%s), uma após a outra, e gerar TODOS os cards "
            "não-concluídos de cada uma, em modo automático (sem gates: roteiro e thumb aprovados "
            "sozinhos).\n\n" % cats
        )
        if publicar:
            msg += ("Ao terminar TUDO, vou PUBLICAR a fila no YouTube via AdsPower (abre os perfis "
                    "dos canais). Confirme que o AdsPower está aberto com a Local API ligada.\n\n")
        else:
            msg += ("Sem publicar (só gera — você posta depois no botão 'Publicar fila').\n\n")
        msg += "Isso pode levar HORAS (muitos vídeos). Pode deixar rodando. Continuar?"
        if not messagebox.askyesno("Gerar TUDO", msg):
            return
        _limpar_log()
        parar.clear()
        btn.config(state="disabled")
        btn_esteira.config(state="disabled")
        btn_todas.config(state="disabled")
        btn_refazer.config(state="disabled")
        btn_continuar.config(state="disabled")
        btn_cancel.config(state="normal")
        _set_status("gerar tudo…", ACCENT)
        threading.Thread(target=worker_todas, daemon=True).start()

    def iniciar_esteira():
        cat_label = var_categoria.get()
        publicar = var_publicar_fim.get()
        msg = (
            "Rodar a esteira INTEIRA da categoria «%s»?\n\n"
            "Vou gerar TODOS os cards não-concluídos dessa lista, um por vez, em modo "
            "automático (sem gates: roteiro e thumb aprovados sozinhos).\n\n" % cat_label
        )
        if publicar:
            msg += ("Ao terminar, vou PUBLICAR a fila no YouTube via AdsPower (abre os perfis "
                    "dos canais). Confirme que o AdsPower está aberto com a Local API ligada.\n\n")
        else:
            msg += ("Sem publicar (só gera). Para subir depois, use 'Publicar fila'.\n\n")
        msg += "Pode demorar bastante (vários vídeos). Continuar?"
        if not messagebox.askyesno("Rodar esteira", msg):
            return
        _limpar_log()
        parar.clear()
        btn.config(state="disabled")
        btn_esteira.config(state="disabled")
        btn_todas.config(state="disabled")
        btn_refazer.config(state="disabled")
        btn_continuar.config(state="disabled")
        btn_cancel.config(state="normal")
        _set_status("esteira…", ACCENT)
        threading.Thread(target=worker_esteira, daemon=True).start()

    def iniciar(continuar=False, refazer=False):
        if not any(v.get() for v in vars_etapas.values()):
            messagebox.showwarning("Nada marcado", "Marque pelo menos uma etapa.")
            return
        if refazer:
            # Confirma antes de apagar — é destrutivo (perde roteiro, narração, thumb,
            # imagens e o vídeo já gerados). O card do ClickUp (source.json) é mantido.
            alvo = (var_slug.get().strip() or estado.get("slug")
                    or projeto_mais_recente() or var_card.get().strip() or "este projeto")
            if not messagebox.askyesno(
                "Refazer tudo",
                "Isto APAGA o roteiro, narração, thumb, imagens e o vídeo já gerados de\n"
                "«%s» e refaz TUDO do zero (o card do ClickUp é mantido).\n\n"
                "As etapas marcadas é que serão refeitas. Continuar?" % alvo,
            ):
                return
        _limpar_log()
        parar.clear()
        btn.config(state="disabled")
        btn_esteira.config(state="disabled")
        btn_todas.config(state="disabled")
        btn_refazer.config(state="disabled")
        btn_continuar.config(state="disabled")
        btn_cancel.config(state="normal")
        _set_status("rodando", ACCENT)
        threading.Thread(target=worker, args=(continuar, refazer), daemon=True).start()

    def _pasta_entrega_atual():
        """Path da entrega (ENTREGAS/<Categoria>/<Card>/) do slug atual, ou None.
        Cai na entrega antiga plana (ENTREGAS/<slug>/) e, sem bundle ainda, no próprio project."""
        from entrega import pasta_entrega, ENTREGAS_DIR

        slug = var_slug.get().strip() or estado.get("slug") or projeto_mais_recente()
        if not slug:
            return None
        proj = projeto_por_slug(slug)
        nova = pasta_entrega(proj)
        if nova.is_dir():
            return nova
        legado = ENTREGAS_DIR / slug          # entregas antigas (layout plano)
        if legado.is_dir():
            return legado
        if proj.dir.is_dir():
            return proj.dir                   # ainda sem entrega: abre o project
        return None

    def abrir_pasta():
        """Abre a pasta de entrega (ENTREGAS/<Categoria>/<Card>/) do projeto atual no Explorer.
        Cai pra VIDEOS-PRONTOS/ se ainda não houver bundle do projeto."""
        from entrega import VIDEOS_PRONTOS_DIR

        alvo = _pasta_entrega_atual()
        if not alvo and VIDEOS_PRONTOS_DIR.is_dir():
            alvo = VIDEOS_PRONTOS_DIR

        if not alvo or not Path(alvo).is_dir():
            messagebox.showinfo(
                "Sem pasta ainda",
                "Nenhuma entrega encontrada. Gere um vídeo primeiro (a pasta é "
                "criada no fim da Etapa 8).",
            )
            return
        try:
            import subprocess
            if sys.platform.startswith("win"):
                os.startfile(str(alvo))  # noqa: S606  (Explorer do Windows)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(alvo)], check=True)  # Finder do macOS
            else:
                subprocess.run(["xdg-open", str(alvo)], check=True)  # Linux
            log("📂 Abrindo: %s" % alvo)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Erro", "Não consegui abrir a pasta:\n%s" % e)

    def _trocar_categoria(_evt=None):
        chave = cat_key_por_label.get(var_categoria.get(), categorias.PADRAO)
        categorias.aplicar(chave)
        log("📂 Categoria: %s — atualizando a lista de cards do ClickUp…"
            % categorias.label_de(chave))
        carregar_videos(force=True)

    def publicar_fila():
        """Dispara o publicador (sobe + agenda a fila no YouTube via AdsPower) num console próprio.

        Abre numa janela separada porque o worker é interativo (Gate 3 no navegador + progresso
        do upload) e roda longo — não trava a GUI. A fila vem da Etapa 9 de cada vídeo."""
        from common import achar_python, ORCH_DIR, FILA_DIR
        import subprocess

        pendentes = len(list(FILA_DIR.glob("*.json"))) if FILA_DIR.is_dir() else 0
        if not pendentes:
            messagebox.showinfo(
                "Fila vazia",
                "Não há vídeos na fila de publicação.\n\nRode a Etapa 9 (Publicação) num vídeo "
                "primeiro — ela gera os metadados e enfileira o vídeo aqui.",
            )
            return
        if not messagebox.askyesno(
            "Publicar fila",
            "Abrir o publicador para subir + agendar %d vídeo(s) no YouTube?\n\n"
            "Ele vai, por vídeo: mostrar o Gate 3 (revisar título/descrição/tags), abrir o "
            "perfil do canal no AdsPower e agendar 1/dia às 18h (US Pacific).\n\n"
            "Requer o AdsPower aberto (Local API ligada) e os perfis configurados." % pendentes,
        ):
            return
        cmd = achar_python() + [str(ORCH_DIR / "publicador.py")]
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            subprocess.Popen(cmd, cwd=str(ORCH_DIR), creationflags=flags, env=env)
            log("⬆ Publicador aberto (%d na fila) — siga no console/navegador (Gate 3)." % pendentes)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Erro", "Não consegui abrir o publicador:\n%s" % e)

    def sincronizar_fila():
        """Roda o watcher (ClickUp → fila) UMA vez num console próprio: enfileira os vídeos
        prontos cujos cards estão no status 'publicar' no ClickUp. NÃO abre o AdsPower nem publica
        — é só a ponte semi-automática. Depois use 'Publicar fila' pra subir/agendar de fato."""
        from common import achar_python, ORCH_DIR
        import subprocess

        cmd = achar_python() + [str(ORCH_DIR / "watcher.py")]
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            subprocess.Popen(cmd, cwd=str(ORCH_DIR), creationflags=flags, env=env)
            log("🔄 Watcher aberto — varrendo o ClickUp e enfileirando os vídeos prontos.")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Erro", "Não consegui abrir o watcher:\n%s" % e)

    combo_categoria.bind("<<ComboboxSelected>>", _trocar_categoria)
    btn_pasta.config(command=abrir_pasta)
    btn_sync.config(command=sincronizar_fila)
    btn_publicar.config(command=publicar_fila)
    btn_refresh.config(command=lambda: carregar_videos(force=True))
    btn.config(command=lambda: iniciar(continuar=False))
    btn_esteira.config(command=iniciar_esteira)
    btn_todas.config(command=iniciar_todas)
    btn_continuar.config(command=lambda: iniciar(continuar=True))
    btn_refazer.config(command=lambda: iniciar(continuar=False, refazer=True))
    btn_cancel.config(
        command=lambda: (parar.set(), _set_status("cancelando…", WARN), log("Cancelando…"))
    )

    # Carrega a lista de vídeos do ClickUp assim que a janela abre (em background).
    root.after(200, carregar_videos)

    try:
        ico = Path(__file__).resolve().parent / "longform.ico"
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:
        pass

    # macOS/Tk 8.5: a janela às vezes abre "cinza" (widgets não pintam) até receber um
    # evento de redraw. Forçamos: trazer pra frente + micro-resize (1px e volta) que dispara
    # a repintura — assim o usuário não precisa arrastar o canto da janela. Best-effort.
    def _forcar_redraw_macos():
        try:
            root.update_idletasks()
            root.lift()
            root.focus_force()
            w, h = root.winfo_width(), root.winfo_height()
            if w > 1 and h > 1:
                root.geometry("%dx%d" % (w + 1, h + 1))
                root.after(60, lambda: root.geometry("%dx%d" % (w, h)))
            root.update()
        except Exception:
            pass
    if sys.platform == "darwin":
        root.after(150, _forcar_redraw_macos)

    root.mainloop()


def main():
    card = sys.argv[1] if len(sys.argv) > 1 else ""
    rodar_gui(card)


if __name__ == "__main__":
    main()
