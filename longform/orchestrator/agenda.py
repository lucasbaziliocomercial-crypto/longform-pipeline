# -*- coding: utf-8 -*-
"""agenda.py — calcula o PRÓXIMO slot de publicação por canal (N vídeos/dia, espaçados X min).

Regra (canal novo, 2026-07-10): até `LONGFORM_PUB_POR_DIA` vídeos por dia (default 3), o 1º na
hora-base `LONGFORM_PUB_HORA` (default 18h) e os seguintes a cada `LONGFORM_PUB_ESPACO_MIN`
minutos (default 10) — ex.: 18:00, 18:10, 18:20. Estourou a cota do dia → rola pro dia seguinte
no 1º slot. Tudo no fuso `LONGFORM_PUB_TZ` (default America/Los_Angeles = US Pacific, o fuso de
referência de data do YouTube). Para voltar a "1/dia" basta `LONGFORM_PUB_POR_DIA=1`; para
"rajada de 5 em 5 min" use POR_DIA alto + `LONGFORM_PUB_ESPACO_MIN=5`.

Cada categoria (= canal) tem um ledger `publicacao/agenda_<categoria>.json` com o último slot
usado. O publicador chama `proximo_slot(cat)` p/ obter a data-hora, agenda no YouTube e então
`reservar(cat, slot)` p/ gravar o ledger — a próxima chamada já avança pro próximo slot do dia
(ou pro dia seguinte). Na 1ª vez (ledger vazio) o publicador pode passar `seed=` com a última
data já agendada no canal (lida do Studio), p/ continuar de onde a mão parou. Nunca agenda no
passado (piso = amanhã no 1º slot), então o YouTube sempre aceita a data.

Fuso: usa `zoneinfo` quando disponível (com o pacote tzdata no Windows); se não, cai num
fallback embutido com a regra de DST dos EUA (Pacific/Eastern) e do Brasil (sem DST desde 2019).
"""

import json
import os
from datetime import datetime, timedelta, tzinfo, timedelta as _td

from common import PUBLICACAO_DIR, forcar_utf8_console
import categorias


# ---------------------------------------------------------------------------
# Fuso horário (zoneinfo + fallback embutido, p/ não depender de tzdata no Windows)
# ---------------------------------------------------------------------------

def _segundo_domingo(ano, mes):
    """datetime.date do 2º domingo do mês (regra de início do DST dos EUA em março)."""
    from datetime import date
    d = date(ano, mes, 1)
    # weekday(): seg=0..dom=6. Dias até o 1º domingo:
    primeiro = (6 - d.weekday()) % 7
    return date(ano, mes, 1 + primeiro + 7)  # 2º domingo


def _primeiro_domingo(ano, mes):
    from datetime import date
    d = date(ano, mes, 1)
    primeiro = (6 - d.weekday()) % 7
    return date(ano, mes, 1 + primeiro)


class _FusoFallback(tzinfo):
    """Fallback simples p/ os fusos suportados quando o zoneinfo/tzdata não está disponível.

    kind: 'us_pacific' (-8/-7), 'us_eastern' (-5/-4), 'br' (-3 fixo). DST dos EUA: 2º domingo
    de março 02:00 → 1º domingo de novembro 02:00 (comparado por data — bordas de 18h ok)."""
    def __init__(self, kind):
        self.kind = kind

    def _dst_ativo_eua(self, dt):
        ini = _segundo_domingo(dt.year, 3)
        fim = _primeiro_domingo(dt.year, 11)
        return ini <= dt.date() < fim

    def utcoffset(self, dt):
        if self.kind == "br":
            return _td(hours=-3)
        std, dstoff = (-8, -7) if self.kind == "us_pacific" else (-5, -4)
        if dt is not None and self._dst_ativo_eua(dt):
            return _td(hours=dstoff)
        return _td(hours=std)

    def dst(self, dt):
        if self.kind == "br":
            return _td(0)
        return _td(hours=1) if (dt is not None and self._dst_ativo_eua(dt)) else _td(0)

    def tzname(self, dt):
        return {"us_pacific": "US/Pacific", "us_eastern": "US/Eastern", "br": "America/Sao_Paulo"}[self.kind]


_FALLBACK_KIND = {
    "america/los_angeles": "us_pacific", "us/pacific": "us_pacific", "pst": "us_pacific",
    "america/new_york": "us_eastern", "us/eastern": "us_eastern", "est": "us_eastern",
    "america/sao_paulo": "br", "brt": "br",
}


def tz():
    """tzinfo do fuso de publicação (env LONGFORM_PUB_TZ, default America/Los_Angeles)."""
    nome = os.environ.get("LONGFORM_PUB_TZ", "America/Los_Angeles").strip()
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nome)
    except Exception:  # noqa: BLE001 — sem tzdata no Windows cai no fallback embutido
        kind = _FALLBACK_KIND.get(nome.lower(), "us_pacific")
        return _FusoFallback(kind)


def hora():
    """Hora-base do 1º slot do dia (0–23). Env LONGFORM_PUB_HORA (default 18; alternativa comum 19)."""
    try:
        h = int(os.environ.get("LONGFORM_PUB_HORA", "18"))
    except ValueError:
        h = 18
    return min(23, max(0, h))


def por_dia():
    """Máximo de vídeos agendados por dia por canal. Env LONGFORM_PUB_POR_DIA (default 3)."""
    try:
        n = int(os.environ.get("LONGFORM_PUB_POR_DIA", "3"))
    except ValueError:
        n = 3
    return max(1, n)


def espaco_min():
    """Espaçamento em minutos entre vídeos do mesmo dia. Env LONGFORM_PUB_ESPACO_MIN (default 10)."""
    try:
        m = int(os.environ.get("LONGFORM_PUB_ESPACO_MIN", "10"))
    except ValueError:
        m = 10
    return max(1, m)


def jitter_min():
    """Amplitude do 'jitter' humano (± minutos) somado a cada slot p/ o horário não sair
    robótico/cravado (18:00, 18:10…) e sim 'humano' (17:57, 18:06…). Env LONGFORM_PUB_JITTER_MIN
    (default 4; 0 desliga). É CAPADO em `espaco_min()//2 - 1` p/ o jitter nunca embaralhar a
    grade — assim o índice do slot ainda é recuperável do ledger (ver `_indice_no_dia`)."""
    try:
        j = int(os.environ.get("LONGFORM_PUB_JITTER_MIN", "4"))
    except ValueError:
        j = 4
    return max(0, min(j, max(0, espaco_min() // 2 - 1)))


def _com_jitter(slot, cat):
    """Desloca `slot` em ± jitter_min minutos de forma DETERMINÍSTICA por (canal, dia, índice).
    Determinístico de propósito: um `--dry-run` e a rodada real mostram o MESMO horário (nada de
    o vídeo agendar num minuto e o ledger gravar outro), mas cada slot parece humano. O RNG aqui
    é próprio (semeado), separado do RNG de sessão do humano.py."""
    j = jitter_min()
    if j <= 0:
        return slot
    idx = _indice_no_dia(slot)
    semente = "%s|%s|%d" % (categorias.resolver(cat), slot.date().isoformat(), idx)
    import random
    off = random.Random(semente).randint(-j, j)
    return slot + timedelta(minutes=off)


def descrever_cadencia():
    """Frase curta da cadência atual (p/ logar no início do drain). Ex.: '3/dia, 1 a cada 10 min, 18:00 US/Pacific (jitter ±4min)'."""
    j = jitter_min()
    extra = (" (jitter ±%dmin)" % j) if j else ""
    return "%d/dia, 1 a cada %d min, a partir das %02d:00 %s%s" % (
        por_dia(), espaco_min(), hora(), agora().tzname(), extra)


def agora():
    return datetime.now(tz())


# ---------------------------------------------------------------------------
# Ledger por canal
# ---------------------------------------------------------------------------

def _ledger(cat):
    chave = categorias.resolver(cat)
    return PUBLICACAO_DIR / ("agenda_%s.json" % chave)


def ultimo_slot(cat):
    """datetime (tz-aware) do último slot já reservado no canal, ou None."""
    p = _ledger(cat)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return datetime.fromisoformat(d["ultimo"]).astimezone(tz())
    except Exception:  # noqa: BLE001
        return None


def reservar(cat, slot):
    """Grava `slot` como o último slot do canal (chamado após agendar com sucesso)."""
    PUBLICACAO_DIR.mkdir(parents=True, exist_ok=True)
    _ledger(cat).write_text(
        json.dumps({"ultimo": slot.isoformat(), "canal": categorias.canal_de(cat)},
                   ensure_ascii=False),
        encoding="utf-8")


def _na_hora(dia, indice=0):
    """datetime tz-aware do slot `indice` do dia: hora-base + indice*espaco_min minutos.
    indice 0 = 1º vídeo do dia (na hora-base); 1 = +espaco_min; etc."""
    base = datetime(dia.year, dia.month, dia.day, hora(), 0, 0, tzinfo=tz())
    return base + timedelta(minutes=indice * espaco_min())


def _indice_no_dia(slot):
    """Índice (0..) do `slot` dentro do seu dia, medido a partir da hora-base em passos de espaco_min.
    Um slot gerado por _na_hora cai exato; valores fora da grade são arredondados p/ o passo mais próximo."""
    dia0 = _na_hora(slot.date(), 0)
    passos = round((slot - dia0).total_seconds() / 60.0 / espaco_min())
    return max(0, passos)


def _proximo_apos(base):
    """Próximo slot depois de `base`: o próximo índice do MESMO dia se ainda couber na cota
    (por_dia), senão o 1º slot do dia seguinte."""
    idx = _indice_no_dia(base)
    if idx + 1 < por_dia():
        return _na_hora(base.date(), idx + 1)
    return _na_hora(base.date() + timedelta(days=1), 0)


def proximo_slot(cat, seed=None):
    """Próximo slot livre do canal, respeitando N vídeos/dia espaçados espaco_min minutos.

    A partir do último slot do ledger, avança 1 slot (mesmo dia se ainda cabe na cota, senão dia
    seguinte no 1º slot). Nunca antes de amanhã no 1º slot (piso — YouTube exige data futura).
    `seed` (datetime opcional) = última data já agendada no canal lida do Studio na 1ª vez —
    entra como base quando não há ledger (ou quando é mais recente que ele)."""
    base = ultimo_slot(cat)
    if seed is not None:
        seed = seed.astimezone(tz()) if seed.tzinfo else seed.replace(tzinfo=tz())
        if base is None or seed > base:
            base = seed

    piso = _na_hora((agora() + timedelta(days=1)).date(), 0)   # amanhã, 1º slot
    grade = piso if base is None else max(_proximo_apos(base), piso)
    alvo = _com_jitter(grade, cat)
    # jitter negativo nunca pode furar o piso (YouTube exige data futura) — se furar, usa a grade.
    return alvo if alvo >= piso else grade


def _cli():
    """py -3 agenda.py [categoria]  -> mostra o próximo slot do canal."""
    import sys
    forcar_utf8_console()
    cat = sys.argv[1] if len(sys.argv) > 1 else categorias.atual()
    slot = proximo_slot(cat)
    print("canal: %s" % categorias.canal_de(cat))
    print("cadência: %s" % descrever_cadencia())
    print("próximo slot: %s" % slot.strftime("%Y-%m-%d %H:%M %Z"))
    ult = ultimo_slot(cat)
    print("último no ledger: %s" % (ult.strftime("%Y-%m-%d %H:%M %Z") if ult else "(vazio)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
