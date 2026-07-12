# -*- coding: utf-8 -*-
"""common.py — helpers compartilhados da esteira long-form (YouTube 16:9).

Porta enxuta de novela_common.py / novela_orquestra.py do projeto TINAGO, adaptada
para o pipeline long-form: layout de projeto (projects/<slug>/), descoberta de
executáveis, slug, e parse de SRT -> cues. SEM dependência de tkinter.
"""

import os
import re
import sys
import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

# Flags p/ ESCONDER a janela preta de console que cada subprocesso (claude -p, py,
# ffmpeg, powershell…) abriria no Windows. A GUI roda sem console, então o SO aloca
# um console novo por subprocesso — CREATE_NO_WINDOW suprime isso. Espalhe via
# `**SUBPROCESS_FLAGS` em TODO subprocess.Popen/run de programa de console.
# (Fora do Windows vira {} e não tem efeito.)
if os.name == "nt":
    SUBPROCESS_FLAGS = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
else:
    SUBPROCESS_FLAGS = {}

# Raiz do orquestrador (…/longform/orchestrator) e da esteira (…/longform).
ORCH_DIR = Path(__file__).resolve().parent
LONGFORM_DIR = ORCH_DIR.parent
PROJECTS_DIR = LONGFORM_DIR / "projects"
REMOTION_DIR = LONGFORM_DIR / "remotion"
PANEL_DIR = LONGFORM_DIR / "panel"
ASSETS_DIR = LONGFORM_DIR / "assets"

# Publicação no YouTube (Etapa 9 + publicador): a FILA de vídeos a subir e os ledgers de
# agenda (último slot por canal) vivem aqui. A Etapa 9 enfileira `fila/<slug>.json`; o
# publicador drena a fila, sobe via AdsPower e agenda no próximo slot.
PUBLICACAO_DIR = LONGFORM_DIR / "publicacao"
FILA_DIR = PUBLICACAO_DIR / "fila"

# Thumbs de referência do CANAL — a BASE DE ESTILO de QUALQUER thumb (Etapa 6).
# A usuária dropa aqui as capas que servem de padrão visual (composição, luz, estética);
# a Etapa 6 anexa todas como reference no Magnific. Sobrescrevível por env.
THUMB_REF_ESTILO_DIR = Path(os.environ.get(
    "LONGFORM_THUMB_REF_DIR", str(ASSETS_DIR / "thumb_ref_estilo")))

# Skills (slash commands) ficam no perfil do usuário, junto com as novela-en.
COMMANDS_DIR = Path.home() / ".claude" / "commands"


def garantir_gpu_preferencia(log=None):
    """Força o Windows a rodar o Chromium do Remotion na GPU DEDICADA (NVIDIA), não na integrada.

    PROBLEMA: nesta máquina há 2 GPUs (NVIDIA RTX 2060 + AMD Radeon integrada). Sem dizer nada,
    o Windows roda o `chrome-headless-shell.exe` (que o Remotion usa pra desenhar cada frame) na
    GPU integrada fraca ou em SOFTWARE — ~3x mais lento. A correção é gravar a preferência de GPU
    do Windows (HKCU\\...\\DirectX\\UserGpuPreferences) com GpuPreference=2 ("alto desempenho" =
    a dedicada) para os .exe do Remotion. É o MESMO ajuste que aparece em
    Configurações > Sistema > Tela > Gráficos.

    Por que no código (e não só uma vez na mão): quando o Remotion ATUALIZA, o caminho do
    chrome-headless-shell.exe muda (vai pra outra pasta em node_modules/.remotion/...) e a
    preferência se perde. Rodar isto antes de cada render deixa a otimização AUTO-CURÁVEL.

    Best-effort: NUNCA derruba o render — só loga. No-op fora do Windows ou se não achar os .exe.
    GpuPreference: 0=Windows decide, 1=economia (integrada), 2=alto desempenho (dedicada).
    """
    if os.name != "nt":
        return
    def _log(msg):
        if log:
            log(msg)
    try:
        import winreg
    except Exception:
        return
    # Acha o chrome-headless-shell.exe que o Remotion baixou (caminho varia por versão) + o node.
    alvos = []
    cache = REMOTION_DIR / "node_modules" / ".remotion"
    if cache.is_dir():
        alvos += [str(p) for p in cache.rglob("chrome-headless-shell.exe")]
    node = shutil.which("node") or shutil.which("node.exe")
    if node:
        alvos.append(str(Path(node).resolve()))
    if not alvos:
        return
    chave = r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences"
    valor = "GpuPreference=2;"
    aplicados = 0
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, chave, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
            for exe in alvos:
                try:
                    atual, _ = winreg.QueryValueEx(k, exe)
                except FileNotFoundError:
                    atual = None
                if atual != valor:
                    winreg.SetValueEx(k, exe, 0, winreg.REG_SZ, valor)
                    aplicados += 1
    except Exception as e:
        _log("    [gpu] aviso: não consegui gravar a preferência de GPU (%s)." % e)
        return
    if aplicados:
        _log("    [gpu] preferência 'alto desempenho' (NVIDIA) aplicada a %d executável(is) do Remotion." % aplicados)
    else:
        _log("    [gpu] preferência de GPU já estava correta (NVIDIA).")

# Reuso de scripts mecânicos que JÁ existem no projeto TINAGO (Whisper etc.).
# Sobrescrevível por env var caso o usuário mova a pasta.
TINAGO_DIR = Path(os.environ.get("TINAGO_DIR", str(Path.home() / "TINAGO AUTOMAÇÃO")))
WHISPER_SCRIPT = TINAGO_DIR / "gerar-srt-en.py"

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
IMG_EXTS = {".jpeg", ".jpg", ".png", ".webp", ".bmp"}

# Idiomas suportados do CONTEÚDO narrado.
_PT_ALIASES = {"pt", "pt-br", "ptbr", "pt_br", "br", "portugues", "português"}


def idioma():
    """Idioma do CONTEÚDO narrado (roteiro + narração + legendas).

    'en' (default — conversão original do canal) | 'pt' (MODO TESTE: vídeo em
    português, pra equipe avaliar a HISTÓRIA antes de produzir a versão final EN).
    Ligado pela caixa "Vídeo em português" da GUI -> env `LONGFORM_IDIOMA`.

    ATENÇÃO: os prompts de imagem (Etapas 5/7) ficam SEMPRE em inglês — é direção
    visual pro Magnific, não muda com o idioma da narração. Só roteiro/narração/legenda
    trocam de língua."""
    v = os.environ.get("LONGFORM_IDIOMA", "en").strip().lower()
    return "pt" if v in _PT_ALIASES else "en"


def nome_idioma(cod=None):
    """Rótulo legível do idioma ('português' / 'inglês') p/ logs e prompts."""
    return "português" if (cod or idioma()) == "pt" else "inglês"


class ErroPipeline(Exception):
    """Erro de etapa do pipeline (mensagem amigável para a GUI/CLI)."""
    pass


def thumbs_ref_estilo():
    """Imagens de referência de ESTILO do canal (base de qualquer thumb da Etapa 6).

    Lê THUMB_REF_ESTILO_DIR (longform/assets/thumb_ref_estilo/ por padrão). Devolve os
    caminhos ABSOLUTOS ordenados das imagens encontradas, ou [] se a pasta não existir/vazia
    (nesse caso a thumb sai só pelo prompt + direção de arte, sem quebrar nada)."""
    d = THUMB_REF_ESTILO_DIR
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() in IMG_EXTS)


# ---------------------------------------------------------------------------
# Descoberta de executáveis (porta de novela_orquestra.achar_claude/achar_python)
# ---------------------------------------------------------------------------

def forcar_utf8_console():
    """Reconfigura stdout/stderr p/ UTF-8 (errors=replace). Os scripts standalone
    (publicador, compressor…) podem abrir num console cp1252 do Windows, onde imprimir
    →/≤/✅ quebraria com UnicodeEncodeError. Chame no início de cada main()."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — best-effort (stream sem reconfigure)
            pass


def achar_claude():
    """Acha o executável do Claude Code. Retorna a lista-prefixo do comando."""
    for nome in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(nome)
        if p:
            if p.lower().endswith((".cmd", ".bat")):
                return ["cmd", "/c", p]
            return [p]
    raise ErroPipeline(
        "Executável 'claude' não encontrado no PATH. Instale/configure o Claude Code "
        "(o mesmo que você usa no terminal)."
    )


def achar_python():
    """Prefere o launcher 'py -3'; senão, o python atual."""
    if shutil.which("py"):
        return ["py", "-3"]
    return [sys.executable]


def achar_ffmpeg():
    """Acha o executável do ffmpeg. Retorna o caminho (string)."""
    for nome in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(nome)
        if p:
            return p
    raise ErroPipeline(
        "ffmpeg não encontrado no PATH. Instale o FFmpeg (https://ffmpeg.org/download.html) "
        "e adicione a pasta bin/ ao PATH — a montagem híbrida (Etapa 8) depende dele."
    )


# ---------------------------------------------------------------------------
# Slug + layout de projeto
# ---------------------------------------------------------------------------

def slugify(texto, maxlen=60):
    """'Alpha King: His Secret Heir' -> 'alpha-king-his-secret-heir'."""
    if not texto:
        return "sem-titulo"
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if len(t) > maxlen:
        t = t[:maxlen].rstrip("-")
    return t or "sem-titulo"


class Projeto:
    """Aponta para projects/<slug>/ e centraliza os nomes dos artefatos por etapa."""

    def __init__(self, base):
        self.dir = Path(base).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "thumbs").mkdir(exist_ok=True)
        (self.dir / "images").mkdir(exist_ok=True)
        (self.dir / "referencias").mkdir(exist_ok=True)
        (self.dir / "out").mkdir(exist_ok=True)

    # --- artefatos (a ordem é a ordem do pipeline) ---
    @property
    def source(self):           return self.dir / "source.json"            # Etapa 1
    @property
    def thumb_ref(self):        return self.dir / "thumb_ref.png"          # Etapa 1 (anexo do card)
    @property
    def roteiro(self):          return self.dir / "roteiro.txt"            # Etapa 2
    @property
    def roteiro_tts(self):      return self.dir / "roteiro_tts.txt"        # Etapa 4 (roteiro humanizado p/ TTS)
    @property
    def roteiro_docx(self):     return self.dir / "roteiro.docx"           # Etapa 2 (entrega p/ equipe)
    @property
    def roteiro_pdf(self):      return self.dir / "roteiro.pdf"            # Etapa 2 (entrega p/ equipe)
    @property
    def validacao(self):        return self.dir / "roteiro_validacao.json" # Etapa 3
    @property
    def narration_mp3(self):    return self.dir / "narration.mp3"          # Etapa 4
    @property
    def narration_raw(self):    return self.dir / "narration_raw.mp3"      # Etapa 4 (TTS cru, pré-otimização de pausa)
    @property
    def pausas_flag(self):      return self.dir / ".pausas_otimizadas"     # Etapa 4 (marca: pausas já aparadas)
    @property
    def narration_srt(self):    return self.dir / "narration.srt"          # Etapa 4
    @property
    def style_bible(self):      return self.dir / "style_bible.txt"        # Etapa 5 (= CHARACTER BIBLE)
    @property
    def prompts_referencia(self): return self.dir / "prompts_referencia.txt" # Etapa 5 (fichas de personagem)
    @property
    def prompts_thumb(self):    return self.dir / "prompts_thumbnail.txt"  # Etapa 5
    @property
    def referencias_dir(self):  return self.dir / "referencias"            # Etapa 6 (PNG das fichas)
    @property
    def referencias_json(self): return self.dir / "referencias.json"       # Etapa 6 (mapa [Character N]->Library id)
    @property
    def thumbs_dir(self):       return self.dir / "thumbs"                 # Etapa 6
    @property
    def thumb_base_gpt2(self):  return self.thumbs_dir / "_base_gpt2.png"  # Etapa 6 (base leve GPT-2 p/ refino)
    @property
    def thumb_status(self):     return self.thumbs_dir / "thumb_status.json" # Etapa 6 (status da geração: moderado?)
    @property
    def thumb_qa(self):         return self.thumbs_dir / "thumb_qa.json"   # Etapa 6 (veredito do QA do Claude/Opus)
    @property
    def thumb_selected(self):   return self.dir / "thumb_selected.png"     # Gate 2
    @property
    def prompts_imagens(self):  return self.dir / "prompts_imagens.txt"    # Etapa 7
    @property
    def images_dir(self):       return self.dir / "images"                 # Etapa 7
    @property
    def mapping(self):          return self.dir / "mapping.json"           # Etapa 8
    @property
    def base_mp4(self):         return self.dir / "out" / "base.mp4"       # Etapa 8 (FFmpeg: Ken Burns+áudio)
    @property
    def final_mp4(self):        return self.dir / "out" / "final.mp4"      # Etapa 8
    @property
    def render_meta(self):      return self.dir / "out" / ".render.json"   # Etapa 8 (assinatura do render: motor/fps/legenda)
    @property
    def publicacao_json(self):  return self.dir / "publicacao.json"        # Etapa 9 (título/descrição/tags/hashtags YouTube)
    @property
    def final_upload_mp4(self): return self.dir / "out" / "final_upload.mp4"  # Etapa 9 (vídeo comprimido p/ upload)
    @property
    def enfileirado_flag(self): return self.dir / ".enfileirado"           # Etapa 9 (vídeo já colocado na fila de publicação)
    @property
    def gate1_flag(self):       return self.dir / ".gate1_aprovado"        # Gate 1 (marca de aprovação)
    @property
    def thumb_anexada_flag(self): return self.dir / ".thumb_anexada_clickup" # Gate 2 (capa já anexada no card)
    @property
    def relight_flag(self):     return self.dir / ".thumb_relit"          # Etapa 7 (relight da capa já rodou)

    def existe(self, p):
        p = Path(p)
        return p.exists() and (p.is_dir() or p.stat().st_size > 0)

    # --- assinatura do render (motor/fps/legenda) p/ re-render automático sem gastar crédito ---
    @staticmethod
    def assinatura_render():
        """Assinatura do FORMATO de render ATUAL, lida do ambiente (= longform.env já aplicado).

        Captura só o que muda a SAÍDA do vídeo e justifica re-renderizar: o motor
        (dynamic/hybrid/ffmpeg/remotion), o fps e se a legenda está ligada. Os defaults
        espelham os de s8_montagem.py / build-mapping.py (engine=dynamic, fps=30, legenda ligada)
        para a assinatura bater com o que a Etapa 8 realmente produz.
        """
        eng = (os.environ.get("LONGFORM_RENDER_ENGINE", "dynamic") or "dynamic").strip().lower()
        fps = (os.environ.get("LONGFORM_FPS", "30") or "30").strip()
        cap = (os.environ.get("LONGFORM_CAPTIONS", "1") or "1").strip().lower() \
            in {"1", "true", "yes", "sim", "on"}
        return {"v": 1, "engine": eng, "fps": fps, "captions": cap}

    def gravar_render_meta(self):
        """Grava a assinatura do render ATUAL ao lado do final.mp4 (chamado ao concluir a Etapa 8).

        É esse marcador que permite ao 'Continuar' saber que um vídeo já está no FORMATO novo
        e NÃO precisa re-renderizar. Best-effort: falha de escrita nunca derruba a Etapa 8."""
        try:
            self.render_meta.parent.mkdir(parents=True, exist_ok=True)
            self.render_meta.write_text(json.dumps(self.assinatura_render()), encoding="utf-8")
        except OSError:
            pass

    def render_desatualizado(self):
        """True se existe um final.mp4 cujo FORMATO de render difere do atual (motor/fps/legenda).

        Vídeos antigos (sem o marcador out/.render.json) ou renderizados num motor/fps diferente
        contam como DESATUALIZADOS → o 'Continuar' re-renderiza SÓ a Etapa 8 (FFmpeg, local, sem
        custo de crédito), reaproveitando roteiro/narração/imagens. Sem final.mp4 não há o que
        desatualizar (devolve False — a etapa só está 'pendente' por não existir ainda)."""
        if not self.existe(self.final_mp4):
            return False
        if not self.render_meta.is_file():
            return True
        try:
            gravado = json.loads(self.render_meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        return gravado != self.assinatura_render()

    def etapa_pronta(self, n):
        """True se o artefato-âncora da etapa n já existe (base do 'Continuar')."""
        if n == 1: return self.existe(self.source)
        if n == 2: return self.existe(self.roteiro)
        if n == 3: return self.existe(self.validacao)
        if n == 4: return self.existe(self.narration_mp3) and self.existe(self.narration_srt)
        if n == 5: return self.existe(self.style_bible) and self.existe(self.prompts_thumb)
        if n == 6: return bool(list(self.thumbs_dir.glob("thumb_*.png")))
        if n == 7: return bool(list(self.images_dir.glob("img_*.png")))
        # Etapa 8: pronta SÓ se o final.mp4 existe E está no formato de render atual.
        # Se o motor/fps mudou (ex.: dynamic 60fps -> hybrid 30fps), conta como PENDENTE
        # para o 'Continuar' re-renderizar só o vídeo (sem refazer nada pago).
        if n == 8: return self.existe(self.final_mp4) and not self.render_desatualizado()
        # Etapa 9: pronta quando os metadados existem E o vídeo já foi enfileirado p/ publicação.
        if n == 9: return self.existe(self.publicacao_json) and self.enfileirado_flag.exists()
        return False

    def etapas_pendentes(self, etapas):
        """Das `etapas` pedidas, devolve só as que ainda não estão prontas (em ordem)."""
        return [n for n in sorted(etapas) if not self.etapa_pronta(n)]

    # --- limpeza p/ "Refazer" ---
    def _artefatos_etapa(self, n):
        """Lista os arquivos/pastas que devem ser apagados ao 'refazer' a etapa n.
        Preserva sempre source.json e thumb_ref.png (vêm do ClickUp e são caros de
        re-baixar — se quiser refazer a etapa 1, apague à mão)."""
        if n == 1: return [self.source]
        if n == 2: return [self.roteiro, self.roteiro_docx, self.roteiro_pdf]
        if n == 3: return [self.validacao, self.gate1_flag]
        if n == 4: return [self.narration_mp3, self.narration_srt, self.roteiro_tts,
                           self.narration_raw, self.pausas_flag]
        if n == 5: return [self.style_bible, self.prompts_referencia, self.prompts_thumb,
                           self.referencias_dir, self.referencias_json]
        if n == 6: return [self.thumbs_dir, self.thumb_selected]
        if n == 7: return [self.prompts_imagens, self.images_dir]
        if n == 8: return [self.mapping, self.base_mp4, self.final_mp4]
        if n == 9: return [self.publicacao_json, self.final_upload_mp4, self.enfileirado_flag]
        return []

    def limpar_etapas(self, etapas):
        """Apaga os artefatos das etapas pedidas para forçar regeneração.
        Pastas (thumbs/, images/, referencias/) são esvaziadas e recriadas vazias.
        Retorna a lista de paths que foram apagados (para log)."""
        apagados = []
        for n in sorted(etapas):
            for alvo in self._artefatos_etapa(n):
                p = Path(alvo)
                if not p.exists():
                    continue
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    p.mkdir(parents=True, exist_ok=True)
                else:
                    try:
                        p.unlink()
                    except OSError:
                        continue
                apagados.append(p)
        return apagados


def _pastas_canais():
    """Nomes das subpastas de canal em projects/ (ex.: 'Selena 1', 'Mafia 1'…). Import LOCAL
    p/ evitar dependência circular — categorias.py não importa common.py. Sem categorias
    (ou erro) devolve [] e a descoberta cai no layout plano."""
    try:
        import categorias
        return categorias.pastas_canais()
    except Exception:  # noqa: BLE001
        return []


def canal_atual():
    """Subpasta de canal da categoria ATUALMENTE fixada no ambiente (env LONGFORM_CATEGORIA),
    ex.: 'Mafia 2'. Devolve None quando NENHUMA categoria foi fixada — aí a descoberta não tem
    canal preferido e cai no comportamento legado (plano + varredura de todos os canais)."""
    if not os.environ.get("LONGFORM_CATEGORIA"):
        return None
    try:
        import categorias
        return categorias.pasta_canal()
    except Exception:  # noqa: BLE001
        return None


def achar_pasta_projeto(slug, canal=None):
    """Localiza a pasta do projeto no layout PLANO (projects/<slug>) OU no layout POR CANAL
    (projects/<Canal>/<slug>, desde 2026-07-10). Retorna o Path existente ou None.

    IMPORTANTE (2026-07-12): os slugs COLIDEM entre canais — Máfia 1/2/3/4 (e Selena 1/2)
    reusam os mesmos nomes de card, e o slugify() ainda trunca em 60 chars, então dois cards
    de canais diferentes viram o MESMO slug. Por isso a busca é ciente do canal:

      • `canal` EXPLÍCITO (o chamador AFIRMA o canal, ex.: a categoria escolhida na GUI) →
        busca ESTRITA: só `projects/<canal>/<slug>` (+ layout plano legado). NÃO cai em outro
        canal — assim "continuar" um card que ainda não existe NESTE canal devolve None (o
        chamador trata como "card novo: use Gerar") em vez de resolver pro projeto de OUTRO canal.

      • `canal` None → usa `canal_atual()` (env `LONGFORM_CATEGORIA`) como PREFERÊNCIA, depois o
        layout plano, e por último varre TODOS os canais (fallback legado p/ resume por `--slug`
        sem categoria fixada). Aqui a varredura cross-channel é aceitável porque é best-effort."""
    if canal:
        p = PROJECTS_DIR / canal / slug
        if p.is_dir():
            return p
        flat = PROJECTS_DIR / slug
        return flat if flat.is_dir() else None
    preferido = canal_atual()
    if preferido:
        p = PROJECTS_DIR / preferido / slug
        if p.is_dir():
            return p
    flat = PROJECTS_DIR / slug
    if flat.is_dir():
        return flat
    for c in _pastas_canais():
        p = PROJECTS_DIR / c / slug
        if p.is_dir():
            return p
    return None


def projeto_por_slug(slug):
    """Projeto pelo slug, procurando no layout plano E nas subpastas de canal. Se não existir
    em lugar nenhum, cai no layout plano (projects/<slug>) — comportamento antigo p/ slug novo."""
    achado = achar_pasta_projeto(slug)
    return Projeto(achado) if achado else Projeto(PROJECTS_DIR / slug)


def projeto_mais_recente():
    """Slug do projeto modificado mais recentemente (ignora _tmp_ e DESCE nas pastas de canal).
    None se não houver."""
    if not PROJECTS_DIR.is_dir():
        return None
    canais = set(_pastas_canais())
    pastas = []
    for p in PROJECTS_DIR.iterdir():
        if not p.is_dir() or p.name.startswith("_tmp_"):
            continue
        if p.name in canais:                      # pasta de canal -> olha os projetos dentro
            pastas += [q for q in p.iterdir()
                       if q.is_dir() and not q.name.startswith("_tmp_")]
        else:                                     # projeto solto no layout plano (legado)
            pastas.append(p)
    if not pastas:
        return None
    return max(pastas, key=lambda p: p.stat().st_mtime).name


def achar_audio(pasta):
    """narration.<audio> (preferido) ou o 1º arquivo de áudio da pasta."""
    pasta = Path(pasta)
    if not pasta.is_dir():
        return None
    for p in pasta.iterdir():
        if p.is_file() and p.stem.lower() == "narration" and p.suffix.lower() in AUDIO_EXTS:
            return p
    cands = [p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    return sorted(cands)[0] if cands else None


# ---------------------------------------------------------------------------
# Parse de SRT (para build-mapping e contagem de palavras/segmentos)
# ---------------------------------------------------------------------------

_SRT_TIME = re.compile(
    r"(\d\d):(\d\d):(\d\d)[,.](\d{3})\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d{3})"
)


def _tc(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(caminho):
    """Lê um .srt e devolve [(idx, start_s, end_s, texto), ...] em ordem."""
    texto = Path(caminho).read_text(encoding="utf-8", errors="replace")
    blocos = re.split(r"\n\s*\n", texto.strip())
    cues = []
    for b in blocos:
        linhas = [l for l in b.splitlines() if l.strip() != ""]
        if not linhas:
            continue
        # acha a linha de tempo (pode ou não haver índice antes)
        tline = None
        ti = 0
        for i, l in enumerate(linhas):
            if _SRT_TIME.search(l):
                tline, ti = l, i
                break
        if tline is None:
            continue
        m = _SRT_TIME.search(tline)
        start = _tc(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _tc(m.group(5), m.group(6), m.group(7), m.group(8))
        fala = " ".join(linhas[ti + 1:]).strip()
        cues.append((len(cues) + 1, start, end, fala))
    return cues


def contar_palavras(texto):
    return len(re.findall(r"\b[\w'-]+\b", texto or ""))
