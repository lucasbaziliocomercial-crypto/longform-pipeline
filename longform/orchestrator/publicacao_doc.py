# -*- coding: utf-8 -*-
"""publicacao_doc.py — exporta os metadados de publicação (publicacao.json) para um PDF.

Regra do usuário: cada vídeo deve ter, na pasta do projeto, UM documento de publicação
(PDF) com o NOME DO CARD (igual à demanda do ClickUp) contendo título, descrição, tags,
hashtags e as fontes — pra não ficar tudo espalhado e ficar fácil de abrir/copiar.

A Etapa 9 chama `exportar(proj, ...)` automaticamente depois de gerar o `publicacao.json`.
Também roda standalone:

    py -3 publicacao_doc.py "<pasta_do_projeto>"

Gera SÓ o PDF (escolha do usuário), nativo via fpdf2 (mesmas fontes Unicode do Windows que o
roteiro_doc). Idempotente: só (re)gera quando o publicacao.json é mais novo que o PDF.
"""

import json
import sys
from pathlib import Path

# Reaproveita o localizador de fontes TTF do exportador de roteiro (Georgia/Times/Arial).
from roteiro_doc import _achar_fonte


def _nome_card(pasta: Path) -> str:
    """Nome do arquivo = nome do card (número + título), igual ao MP4 final.

    Reusa entrega._nome_amigavel quando disponível (mesma sanitização de Windows); se o
    orquestrador não estiver no path, cai para o source.json direto e por fim o slug.
    """
    try:
        import entrega
        from common import Projeto
        return entrega._nome_amigavel(Projeto(pasta))
    except Exception:  # noqa: BLE001 — standalone/sem o pacote: derive do source.json
        import re
        nome = pasta.name
        src_p = pasta / "source.json"
        try:
            if src_p.exists():
                s = json.loads(src_p.read_text(encoding="utf-8", errors="replace"))
                nome = (s.get("card_nome") or s.get("tema") or s.get("titulo")
                        or s.get("title") or nome)
        except Exception:
            pass
        nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(nome)).strip().rstrip(".")
        return nome or pasta.name


def _limpar(txt) -> str:
    """Remove astral chars (emoji) que a fonte serifada do Windows não possui — evita
    glifos-fantasma/erros no fpdf. O texto (obras/autores/descrição) fica intacto."""
    if txt is None:
        return ""
    return "".join(ch for ch in str(txt) if ord(ch) <= 0xFFFF).replace("\r\n", "\n")


def _campos(pub: dict) -> dict:
    """Normaliza o publicacao.json em (title, description, tags, hashtags, sources)."""
    tags = pub.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    hashtags = pub.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [h.strip() for h in hashtags.split() if h.strip()]
    return {
        "title": _limpar(pub.get("title")),
        "description": _limpar(pub.get("description")),
        "tags": ", ".join(_limpar(t) for t in tags),
        "hashtags": " ".join(_limpar(h) for h in hashtags),
        "sources": _limpar(pub.get("reference_sources")),
        "search": [ _limpar(u) for u in (pub.get("search_sources") or []) ],
    }


def _gerar_pdf(campos: dict, pdf_path: Path, log) -> bool:
    try:
        from fpdf import FPDF
    except Exception:
        log("    (publicacao.pdf pulado: fpdf2 indisponível.)")
        return False
    reg, bold = _achar_fonte()
    if not reg:
        log("    (publicacao.pdf pulado: nenhuma fonte TTF em C:\\Windows\\Fonts.)")
        return False
    try:
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(20, 20, 20)
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_font("pub", "", reg)
        pdf.add_font("pub", "B", bold)
        pdf.add_page()

        # título do vídeo
        pdf.set_font("pub", "B", 16)
        pdf.multi_cell(0, 8, campos["title"], align="L")
        pdf.ln(4)

        def secao(rotulo: str, corpo: str):
            if not corpo:
                return
            pdf.set_font("pub", "B", 11)
            pdf.multi_cell(0, 6, rotulo)
            pdf.ln(1)
            pdf.set_font("pub", "", 12)
            pdf.multi_cell(0, 6.5, corpo)
            pdf.ln(4)

        secao("DESCRIPTION", campos["description"])
        secao("TAGS", campos["tags"])
        secao("HASHTAGS", campos["hashtags"])
        secao("REFERENCE SOURCES", campos["sources"])
        if campos["search"]:
            secao("SEARCH REFERENCES (audit)", "\n".join(campos["search"]))

        pdf.output(str(pdf_path))
        return True
    except Exception as e:  # noqa: BLE001
        log("    (publicacao.pdf falhou: %s)" % e)
        return False


def exportar(proj_ou_pasta, log=print):
    """Gera <pasta>/<nome-do-card>.pdf a partir de publicacao.json. Retorna o Path (ou None).

    Aceita um objeto Projeto (tem .dir) OU um caminho de pasta. Idempotente."""
    pasta = Path(getattr(proj_ou_pasta, "dir", proj_ou_pasta))
    pub_json = pasta / "publicacao.json"
    if not (pub_json.exists() and pub_json.stat().st_size > 0):
        log("    (publicacao.pdf pulado: falta publicacao.json.)")
        return None
    pdf_path = pasta / (_nome_card(pasta) + ".pdf")

    # idempotência: PDF atual (>= json) e não vazio -> nada a fazer.
    if pdf_path.exists() and pdf_path.stat().st_size > 0 \
            and pdf_path.stat().st_mtime >= pub_json.stat().st_mtime:
        log("    publicacao.pdf já está atualizado — exportação pulada.")
        return pdf_path

    try:
        pub = json.loads(pub_json.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log("    (publicacao.pdf pulado: publicacao.json inválido: %s)" % e)
        return None

    if _gerar_pdf(_campos(pub), pdf_path, log):
        log("    ✓ %s gerado (documento de publicação)." % pdf_path.name)
        return pdf_path
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print('uso: py -3 publicacao_doc.py "<pasta_do_projeto>"')
        return
    pdf = exportar(Path(sys.argv[1]))
    print("PDF:", pdf or "(não gerado)")


if __name__ == "__main__":
    main()
