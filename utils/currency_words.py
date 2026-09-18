"""
Utilitário para conversão de valores monetários para texto por extenso em Português (Brasil).
Suporta formatos brasileiros (150.000,00 ou 150.000), americanos (150,000.00),
números puros (150000) e abreviações (150k, 1.5m).
"""

import re
from typing import Optional

UNIDADES = [
    "", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
    "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"
]

DEZENAS = [
    "", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"
]

CENTENAS = [
    "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos"
]


def _centenas_por_extenso(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    
    c = n // 100
    resto = n % 100
    partes = []
    
    if c > 0:
        partes.append(CENTENAS[c])
        
    if resto > 0:
        if resto < 20:
            partes.append(UNIDADES[resto])
        else:
            d = resto // 10
            u = resto % 10
            if u > 0:
                partes.append(f"{DEZENAS[d]} e {UNIDADES[u]}")
            else:
                partes.append(DEZENAS[d])
                
    return " e ".join(partes)


def numero_por_extenso(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 0:
        return f"menos {numero_por_extenso(abs(n))}"

    partes = []

    # Bilhões
    bilhoes = n // 1_000_000_000
    resto_bilhoes = n % 1_000_000_000
    if bilhoes > 0:
        texto = "um bilhão" if bilhoes == 1 else f"{_centenas_por_extenso(bilhoes)} bilhões"
        partes.append(texto)

    # Milhões
    milhoes = resto_bilhoes // 1_000_000
    resto_milhoes = resto_bilhoes % 1_000_000
    if milhoes > 0:
        texto = "um milhão" if milhoes == 1 else f"{_centenas_por_extenso(milhoes)} milhões"
        partes.append(texto)

    # Milhares
    milhares = resto_milhoes // 1_000
    centenas = resto_milhoes % 1_000
    if milhares > 0:
        texto = "mil" if milhares == 1 else f"{_centenas_por_extenso(milhares)} mil"
        partes.append(texto)

    # Centenas
    if centenas > 0:
        partes.append(_centenas_por_extenso(centenas))

    return " e ".join(partes)


def parse_currency_str(valor: any) -> Optional[float]:
    """
    Interpreta qualquer formato de string monetária brasileira ou internacional de forma resiliente.
    Suporta:
      '10000' -> 10000.0
      '10.000' -> 10000.0
      '10.000,00' -> 10000.0
      '10.000.00' -> 10000.0 (teclado numérico com ponto decimal)
      '10000,00' -> 10000.0
      '10000.00' -> 10000.0
      '10k' -> 10000.0
      '1000000' -> 1000000.0
      '1.000.000,00' -> 1000000.0
      '1.000.000.00' -> 1000000.0
      '1m' -> 1000000.0
      '150.000,50' -> 150000.5
      '150.000.50' -> 150000.5
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if valor >= 0 else None

    val_str = str(valor).strip().replace("R$", "").replace("r$", "").replace(" ", "")
    if not val_str:
        return None

    # Valores monetários negativos não são válidos neste domínio (ACV, dívida);
    # rejeita em vez de descartar o sinal silenciosamente.
    if val_str.startswith("-"):
        return None

    val_lower = val_str.lower()
    if val_lower.endswith("k") or val_lower.endswith("mil"):
        num = re.sub(r"[^\d,\.]", "", val_lower).replace(",", ".")
        try:
            return float(num) * 1000.0
        except ValueError:
            return None
    if val_lower.endswith("m") or val_lower.endswith("mi") or "milh" in val_lower:
        num = re.sub(r"[^\d,\.]", "", val_lower).replace(",", ".")
        try:
            return float(num) * 1_000_000.0
        except ValueError:
            return None

    # Detecta se há separador de centavos no final (.00, ,00, ,50, .50, ,5, .5, etc.)
    last_dot = val_str.rfind(".")
    last_comma = val_str.rfind(",")
    last_sep = max(last_dot, last_comma)

    if last_sep != -1:
        after = val_str[last_sep + 1:]
        before = val_str[:last_sep]
        # Se após o último separador houver 1 ou 2 dígitos, são centavos!
        if len(after) in (1, 2) and after.isdigit():
            int_digits = re.sub(r"\D", "", before)
            if not int_digits:
                int_digits = "0"
            cents = int(after) if len(after) == 2 else int(after) * 10
            return float(int_digits) + (cents / 100.0)

    # Caso contrário, todos os separadores são de milhar (ou número puro sem centavos)
    digits = re.sub(r"\D", "", val_str)
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def valor_para_extenso(valor: any) -> str:
    """
    Converte um valor monetário (int, float ou string com dígitos) para formato por extenso.
    Retorna string formatada com inicial maiúscula. Ex: 'Cento e cinquenta mil reais'.
    """
    val_float = parse_currency_str(valor)
    if val_float is None or val_float < 0:
        return ""

    inteiro = int(val_float)
    centavos = int(round((val_float - inteiro) * 100))

    partes = []
    if inteiro == 0 and centavos == 0:
        return "Zero reais"

    if inteiro > 0:
        ext_int = numero_por_extenso(inteiro)
        if inteiro == 1:
            moeda = "real"
        elif ext_int.endswith("milhão") or ext_int.endswith("milhões") or ext_int.endswith("bilhão") or ext_int.endswith("bilhões"):
            moeda = "de reais"
        else:
            moeda = "reais"
        partes.append(f"{ext_int} {moeda}")

    if centavos > 0:
        ext_cent = numero_por_extenso(centavos)
        moeda_cent = "centavo" if centavos == 1 else "centavos"
        partes.append(f"{ext_cent} {moeda_cent}")

    res = " e ".join(partes)
    return res[0].upper() + res[1:] if res else ""


def format_real_input(raw: any) -> str:
    """
    Formata valores monetários de forma padronizada no formato brasileiro:
      10000 -> 10.000,00
      10.000 -> 10.000,00
      10.000,00 -> 10.000,00
      10.000.00 -> 10.000,00
      10k -> 10.000,00
      1000000 -> 1.000.000,00
      1m -> 1.000.000,00
    """
    val_float = parse_currency_str(raw)
    if val_float is None:
        return ""
    inteiro = int(val_float)
    centavos = int(round((val_float - inteiro) * 100))
    return f"{inteiro:,}".replace(",", ".") + f",{centavos:02d}"

