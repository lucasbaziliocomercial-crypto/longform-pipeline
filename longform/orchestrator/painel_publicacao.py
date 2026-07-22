# -*- coding: utf-8 -*-
"""painel_publicacao.py — monta um PAINEL HTML "copia-cola" com todos os vídeos prontos.

Objetivo: facilitar o upload MANUAL no YouTube. Varre longform/projects/**, pega todo
projeto que já tem `publicacao.json` (descrição gerada na Etapa 9) + um MP4 final, e gera
um único HTML auto-contido (`longform/PAINEL-PUBLICACAO.html`) onde cada vídeo vira um cartão
com a thumbnail embutida e botões "copiar título / descrição / tags / hashtags / tudo",
o caminho do MP4 (abrir vídeo / abrir pasta) e o link do card no ClickUp.

Não gera descrição nenhuma — só REÚNE o que já existe. Rode quantas vezes quiser (idempotente,
sempre reescreve o HTML). Standalone:

    py -3 painel_publicacao.py            # só gera/atualiza o HTML
    py -3 painel_publicacao.py --abrir    # gera e ABRE num servidor local (http://127.0.0.1)

IMPORTANTE — abra pelo `--abrir` (servidor local), NÃO por duplo-clique no arquivo. Em `file://`
o Chrome bloqueia o clipboard e os botões "copiar" falham; servido por http://127.0.0.1 (contexto
seguro) o copiar funciona nativo. O `--abrir` sobe o servidor e deixa rodando (Ctrl+C encerra).

As thumbs são reduzidas (~480px, JPEG) e embutidas em base64, então o HTML é um arquivo só.
Os links "abrir vídeo/pasta" usam caminho absoluto local (só valem nesta máquina).
"""

from __future__ import annotations  # tipos 'X | None' em Python 3.9 (macOS)

import base64
import io
import json
import re
import sys
import webbrowser
from datetime import datetime, timezone
from html import escape
from pathlib import Path

# garante que `import config` / `clickup_api` funcione mesmo rodando de outro cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Raiz do longform: este arquivo está em longform/orchestrator/painel_publicacao.py
LONGFORM = Path(__file__).resolve().parent.parent
PROJECTS = LONGFORM / "projects"
SAIDA = LONGFORM / "PAINEL-PUBLICACAO.html"

RE_SO_HASHTAGS = re.compile(r"^\s*(#\S+\s*)+$")


def _nome_card(pasta: Path, src: dict) -> str:
    return (src.get("card_nome") or src.get("tema") or src.get("titulo")
            or src.get("title") or pasta.name)


def _achar_mp4(pasta: Path) -> Path | None:
    """MP4 final pronto pra postar: prefere final_upload.mp4, cai pra final.mp4."""
    out = pasta / "out"
    for nome in ("final_upload.mp4", "final.mp4"):
        p = out / nome
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _thumb_b64(pasta: Path) -> str:
    """thumb_selected.png (fallback img_000.png) reduzida p/ ~480px, JPEG base64 (data URI)."""
    for rel in ("thumb_selected.png", "images/img_000.png", "thumbs/thumb_01.png"):
        p = pasta / rel
        if not p.exists():
            continue
        try:
            from PIL import Image
            im = Image.open(p).convert("RGB")
            w, h = im.size
            alvo = 480
            if w > alvo:
                im = im.resize((alvo, max(1, round(h * alvo / w))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            # sem PIL ou imagem quebrada: embute o PNG cru (maior, mas funciona)
            try:
                return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
            except Exception:
                return ""
    return ""


def _descricao_final(pub: dict) -> str:
    """Descrição pronta pra colar: corpo + bloco de hashtags (5) + fontes, se houver.

    A `description` do json já traz o CTA; se ela terminar numa linha só de hashtags,
    troca essa linha pelas hashtags completas do campo `hashtags` (fica consistente)."""
    desc = (pub.get("description") or "").replace("\r\n", "\n").rstrip()
    linhas = desc.split("\n")
    while linhas and RE_SO_HASHTAGS.match(linhas[-1]):
        linhas.pop()
    while linhas and not linhas[-1].strip():
        linhas.pop()
    corpo = "\n".join(linhas)

    hashtags = pub.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    if hashtags:
        corpo += "\n\n" + " ".join(hashtags)

    fontes = (pub.get("reference_sources") or "").strip()
    if fontes:
        corpo += "\n\n" + fontes
    return corpo


def _tags_str(pub: dict) -> str:
    tags = pub.get("tags") or []
    if isinstance(tags, str):
        return tags.strip()
    return ", ".join(t.strip() for t in tags if str(t).strip())


def _hashtags_str(pub: dict) -> str:
    h = pub.get("hashtags") or []
    if isinstance(h, str):
        return h.strip()
    return " ".join(x.strip() for x in h if str(x).strip())


def coletar() -> list[dict]:
    itens = []
    for pub_json in sorted(PROJECTS.rglob("publicacao.json")):
        pasta = pub_json.parent
        try:
            pub = json.loads(pub_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not (pub.get("title") or pub.get("description")):
            continue
        src = {}
        src_p = pasta / "source.json"
        if src_p.exists():
            try:
                src = json.loads(src_p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                src = {}
        mp4 = _achar_mp4(pasta)
        canal = pasta.parent.name if pasta.parent != PROJECTS else "(sem canal)"
        itens.append({
            "canal": canal,
            "card": _nome_card(pasta, src),
            "card_id": src.get("card_id") or "",
            "card_url": src.get("card_url") or "",
            "due_iso": "",   # preenchido por _carregar_datas (data de postagem do ClickUp)
            "status": "",
            "titulo": (pub.get("title") or "").strip(),
            "descricao": _descricao_final(pub),
            "tags": _tags_str(pub),
            "hashtags": _hashtags_str(pub),
            "thumb": _thumb_b64(pasta),
            "mp4_uri": mp4.as_uri() if mp4 else "",
            "mp4_path": str(mp4) if mp4 else "",
            "pasta_uri": pasta.as_uri(),
            "tem_mp4": bool(mp4),
        })
    # ordena por canal e depois pelo nome do card (que costuma começar com número)
    itens.sort(key=lambda x: (x["canal"].lower(), x["card"].lower()))
    return itens


def _carregar_datas(itens: list[dict], log=print) -> int:
    """Preenche `due_iso` (YYYY-MM-DD da postagem) e `status` de cada item via ClickUp REST.

    Best-effort: sem token / offline / card sem data, o item simplesmente fica sem data e o
    painel funciona igual. As datas são "date-only" (sem hora) no ClickUp → formatadas em UTC
    pra não rolar pro dia anterior. Retorna quantos itens ganharam data."""
    try:
        import config  # noqa: F401 — carrega longform.env em os.environ
        import clickup_api as c
    except Exception as e:  # noqa: BLE001
        log(f"    (datas do ClickUp puladas: {e})")
        return 0
    achou = 0
    for it in itens:
        cid = it.get("card_id")
        if not cid:
            continue
        try:
            t = c._get(f"/task/{cid}")
        except Exception:
            continue
        dd = t.get("due_date")
        if dd:
            it["due_iso"] = datetime.fromtimestamp(int(dd) / 1000, tz=timezone.utc) \
                .strftime("%Y-%m-%d")
            achou += 1
        it["status"] = ((t.get("status") or {}).get("status") or "").strip()
    return achou


def gerar_html(itens: list[dict]) -> str:
    dados = json.dumps(itens, ensure_ascii=False)
    canais = sorted({i["canal"] for i in itens}, key=str.lower)
    sem_mp4 = sum(1 for i in itens if not i["tem_mp4"])
    chips = "".join(
        f'<button class="chip" data-canal="{escape(c)}">{escape(c)}</button>' for c in canais
    )
    aviso_mp4 = (
        f'<span class="aviso">⚠ {sem_mp4} sem MP4 final localizado</span>' if sem_mp4 else ""
    )
    return _TEMPLATE.replace("__DADOS__", dados) \
        .replace("__CHIPS__", chips) \
        .replace("__TOTAL__", str(len(itens))) \
        .replace("__NCANAIS__", str(len(canais))) \
        .replace("__AVISO_MP4__", aviso_mp4)


_TEMPLATE = r"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Publicação — YouTube</title>
<style>
  :root{ --bg:#0f1115; --card:#191c23; --card2:#20242d; --tx:#e8eaed; --dim:#9aa0aa;
         --ac:#7c5cff; --ac2:#5b8cff; --ok:#22c55e; --bd:#2b2f3a; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,Segoe UI,Roboto,Arial}
  header{position:sticky;top:0;z-index:5;background:rgba(15,17,21,.92);backdrop-filter:blur(8px);
         border-bottom:1px solid var(--bd);padding:14px 20px}
  h1{margin:0 0 4px;font-size:19px;font-weight:700}
  .sub{color:var(--dim);font-size:13px}
  .aviso{color:#f7b955;margin-left:10px}
  .barra{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:10px}
  #busca{flex:1;min-width:220px;padding:9px 12px;border-radius:9px;border:1px solid var(--bd);
         background:var(--card2);color:var(--tx);font-size:14px}
  .chip{padding:6px 12px;border-radius:999px;border:1px solid var(--bd);background:var(--card2);
        color:var(--dim);cursor:pointer;font-size:13px}
  .chip.on{background:var(--ac);border-color:var(--ac);color:#fff}
  main{padding:20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));
       max-width:1500px;margin:0 auto}
  .v{background:var(--card);border:1px solid var(--bd);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
  .thumb{aspect-ratio:16/9;width:100%;object-fit:cover;background:#000;display:block}
  .no-thumb{aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;color:var(--dim);background:#000}
  .body{padding:13px 14px;display:flex;flex-direction:column;gap:9px;flex:1}
  .data{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;
        padding:3px 10px;border-radius:999px;width:fit-content}
  .data.hoje{background:#14532d;color:#4ade80}
  .data.amanha{background:#1e3a5f;color:#8fc0ff}
  .data.futuro{background:#2a2f3a;color:#c9cfda}
  .data.atrasado{background:#4c1d1d;color:#fca5a5}
  .data.semdata{background:#26262b;color:#8b8f99}
  .canal{font-size:11px;color:var(--ac2);font-weight:700;text-transform:uppercase;letter-spacing:.04em}
  .card-nome{font-size:12px;color:var(--dim)}
  .titulo{font-size:14.5px;font-weight:600;line-height:1.35}
  .btns{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}
  button.cp{padding:6px 10px;border-radius:8px;border:1px solid var(--bd);background:var(--card2);
            color:var(--tx);cursor:pointer;font-size:12.5px}
  button.cp:hover{border-color:var(--ac)}
  button.cp.done{background:var(--ok);border-color:var(--ok);color:#04220f}
  button.tudo{background:var(--ac);border-color:var(--ac);color:#fff;font-weight:600}
  .links{display:flex;flex-wrap:wrap;gap:12px;margin-top:auto;padding-top:6px;font-size:12.5px}
  .links a{color:var(--ac2);text-decoration:none}.links a:hover{text-decoration:underline}
  .links a.off{color:#5a5f6a;pointer-events:none}
  .vazio{grid-column:1/-1;text-align:center;color:var(--dim);padding:40px}
  footer{color:var(--dim);font-size:12px;text-align:center;padding:22px}
</style></head><body>
<header>
  <h1>Painel de Publicação — YouTube <span class="sub">(upload manual)</span></h1>
  <div class="sub"><b id="cont">__TOTAL__</b> vídeos prontos · __NCANAIS__ canais __AVISO_MP4__</div>
  <div class="barra">
    <input id="busca" placeholder="Buscar por título, nome do card ou canal…">
    <button class="chip on" data-canal="">Todos</button>__CHIPS__
  </div>
</header>
<main id="grid"></main>
<footer>Gerado por painel_publicacao.py · clique num botão para copiar o campo e cole no YouTube.</footer>
<script>
const DADOS = __DADOS__;
let filtroCanal = "", termo = "";
const grid = document.getElementById('grid');
const esc = s => (s||"").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function dataInfo(iso){
  const dias=['dom','seg','ter','qua','qui','sex','sáb'];
  const meses=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
  if(!iso) return {txt:'sem data', cls:'semdata'};
  const [y,m,d]=iso.split('-').map(Number);
  const dt=new Date(y,m-1,d), hoje=new Date(); hoje.setHours(0,0,0,0);
  const diff=Math.round((dt-hoje)/86400000);
  let rel = diff===0?' · Hoje' : diff===1?' · Amanhã' : diff===-1?' · Ontem'
          : diff<0?` · ${-diff}d atrás` : '';
  const cls = diff<0?'atrasado' : diff===0?'hoje' : diff===1?'amanha' : 'futuro';
  return {txt:`📅 ${dias[dt.getDay()]}, ${d} ${meses[m-1]}${rel}`, cls};
}
function blocoTudo(v){
  return `TÍTULO:\n${v.titulo}\n\nDESCRIÇÃO:\n${v.descricao}\n\nTAGS:\n${v.tags}\n\nHASHTAGS:\n${v.hashtags}`;
}
function copiar(btn, texto){
  const ok = ()=>{
    const t = btn.textContent; btn.textContent = '✓ copiado'; btn.classList.add('done');
    setTimeout(()=>{ btn.textContent = t; btn.classList.remove('done'); }, 1100);
  };
  // fallback pra file:// (onde navigator.clipboard costuma ser bloqueado): textarea + execCommand
  const legado = ()=>{
    const ta = document.createElement('textarea');
    ta.value = texto; ta.setAttribute('readonly','');
    ta.style.position='fixed'; ta.style.top='-1000px'; ta.style.opacity='0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try{ ta.setSelectionRange(0, texto.length); }catch(e){}
    let sucesso = false;
    try{ sucesso = document.execCommand('copy'); }catch(e){ sucesso = false; }
    document.body.removeChild(ta);
    if(sucesso){ ok(); }
    else { window.prompt('Copie com Ctrl+C (Ctrl+C e Enter):', texto); }  // último recurso: sempre copiável
  };
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(texto).then(ok).catch(legado);
  } else { legado(); }
}
function render(){
  const t = termo.trim().toLowerCase();
  const vis = DADOS.filter(v =>
    (!filtroCanal || v.canal === filtroCanal) &&
    (!t || (v.titulo+' '+v.card+' '+v.canal).toLowerCase().includes(t)));
  document.getElementById('cont').textContent = vis.length;
  if(!vis.length){ grid.innerHTML = '<div class="vazio">Nenhum vídeo com esse filtro.</div>'; return; }
  grid.innerHTML = vis.map((v,i)=>{
    const idx = DADOS.indexOf(v);
    const thumb = v.thumb ? `<img class="thumb" loading="lazy" src="${v.thumb}">`
                          : `<div class="no-thumb">sem capa</div>`;
    const abrirV = v.mp4_uri ? `<a href="${v.mp4_uri}">▶ abrir vídeo</a>`
                             : `<a class="off">▶ sem MP4</a>`;
    const card = v.card_url ? `<a href="${esc(v.card_url)}" target="_blank">🗂 card</a>` : '';
    const di = dataInfo(v.due_iso);
    return `<div class="v">
      ${thumb}
      <div class="body">
        <div class="data ${di.cls}">${di.txt}</div>
        <div class="canal">${esc(v.canal)}</div>
        <div class="card-nome">${esc(v.card)}</div>
        <div class="titulo">${esc(v.titulo)}</div>
        <div class="btns">
          <button class="cp" data-c="titulo" data-i="${idx}">Título</button>
          <button class="cp" data-c="descricao" data-i="${idx}">Descrição</button>
          <button class="cp" data-c="tags" data-i="${idx}">Tags</button>
          <button class="cp" data-c="hashtags" data-i="${idx}">Hashtags</button>
          <button class="cp tudo" data-c="tudo" data-i="${idx}">Copiar tudo</button>
        </div>
        <div class="links">
          ${abrirV}
          <a href="${v.pasta_uri}">📁 pasta</a>
          ${card}
        </div>
      </div>
    </div>`;
  }).join('');
}
grid.addEventListener('click', e=>{
  const b = e.target.closest('button.cp'); if(!b) return;
  const v = DADOS[+b.dataset.i], campo = b.dataset.c;
  copiar(b, campo === 'tudo' ? blocoTudo(v) : (v[campo]||''));
});
document.querySelector('.barra').addEventListener('click', e=>{
  const c = e.target.closest('.chip'); if(!c) return;
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); filtroCanal = c.dataset.canal; render();
});
document.getElementById('busca').addEventListener('input', e=>{ termo = e.target.value; render(); });
render();
</script></body></html>"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not PROJECTS.exists():
        print("Pasta de projetos não encontrada:", PROJECTS)
        return
    itens = coletar()
    if not itens:
        print("Nenhum projeto com publicacao.json encontrado.")
        return
    print("  buscando datas de postagem no ClickUp…")
    com_data = _carregar_datas(itens)
    # ordena por DATA de postagem (agendados primeiro, em ordem cronológica), depois canal/card
    itens.sort(key=lambda x: (x["due_iso"] or "9999-99-99", x["canal"].lower(), x["card"].lower()))
    html = gerar_html(itens)
    SAIDA.write_text(html, encoding="utf-8")
    com_mp4 = sum(1 for i in itens if i["tem_mp4"])
    print(f"✓ {len(itens)} vídeos no painel ({com_mp4} com MP4, {com_data} com data de postagem).")
    print("  ->", SAIDA)
    if "--abrir" in sys.argv or "--servir" in sys.argv:
        _servir_e_abrir()
    else:
        print("  Dica: rode com --abrir pra abrir num servidor local (o 'copiar' só funciona assim).")


def _servir_e_abrir(porta_inicial: int = 8750):
    """Sobe um http.server local em LONGFORM e abre o painel por http://127.0.0.1 (contexto
    seguro → clipboard funciona). Fica rodando até Ctrl+C. Se a porta estiver ocupada, tenta a
    próxima."""
    import functools
    import http.server
    import socketserver

    Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(LONGFORM))
    for porta in range(porta_inicial, porta_inicial + 20):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", porta), Handler)
        except OSError:
            continue
        url = f"http://127.0.0.1:{porta}/{SAIDA.name}"
        print(f"\n  Painel no ar: {url}")
        print("  (deixe esta janela aberta enquanto usa; Ctrl+C encerra.)")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Encerrado.")
        finally:
            httpd.server_close()
        return
    print("  (não achei porta livre entre %d-%d; abra o HTML manualmente.)"
          % (porta_inicial, porta_inicial + 19))


if __name__ == "__main__":
    main()
