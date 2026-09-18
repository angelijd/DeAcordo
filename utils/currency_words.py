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
    """Interpreta qualquer formato de string monetária de forma resiliente."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    val_str = str(valor).strip().replace("R$", "").replace("r$", "").replace(" ", "")
    if not val_str:
        return None

    val_lower = val_str.lower()
    if val_lower.endswith("k"):
        num_part = val_lower[:-1].replace(",", ".")
        try:
            return float(num_part) * 1000
        except ValueError:
            return None
    if val_lower.endswith("m") or val_lower.endswith("mi"):
        num_part = val_lower.rstrip("mi").rstrip("m").replace(",", ".")
        try:
            return float(num_part) * 1_000_000
        except ValueError:
            return None

    # Caso 1: Contém ponto e vírgula (ex: 150.000,00 ou 150,000.00)
    if "." in val_str and "," in val_str:
        last_dot = val_str.rfind(".")
        last_comma = val_str.rfind(",")
        if last_dot < last_comma:
            # Formato BR: 150.000,00 -> vírgula decimal
            clean = val_str.replace(".", "").replace(",", ".")
        else:
            # Formato US: 150,000.00 -> ponto decimal
            clean = val_str.replace(",", "")
        try:
            return float(clean)
        except ValueError:
            return None

    # Caso 2: Apenas vírgula (ex: 150000,00 ou 150,50 ou 150,000)
    if "," in val_str:
        parts = val_str.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1] == "000":
            # Ex: 150,000 -> 150 mil
            clean = "".join(parts)
        else:
            clean = val_str.replace(",", ".")
        try:
            return float(clean)
        except ValueError:
            return None

    # Caso 3: Apenas ponto (ex: 150.000 ou 1.500.000 ou 150000.50)
    if "." in val_str:
        parts = val_str.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            # Formato BR de milhar: 150.000 ou 1.500.000
            clean = "".join(parts)
        elif len(parts) == 2 and len(parts[1]) <= 2:
            # Decimal US: 150000.50
            clean = val_str
        else:
            clean = "".join(parts)
        try:
            return float(clean)
        except ValueError:
            return None

    # Caso 4: Apenas dígitos
    try:
        return float(val_str)
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
    Mascara automaticamente valores monetários enquanto o usuário digita.
    Adiciona pontos de milhar e vírgula de centavos fixos no formato brasileiro.
    Exemplos:
      '100000' -> '100.000,00'
      '100.000' -> '100.000,00'
      '100.000,00' -> '100.000,00'
      '150000' -> '150.000,00'
      '150000,50' -> '150.000,50'
    """
    if raw is None:
        return ""
    import re
    s = str(raw).strip().replace("R$", "").replace("r$", "").strip()
    if not s:
        return ""

    # Se o usuário digitou vírgula com centavos explícitos (ex: 150000,50)
    if "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2) and parts[1] != "00":
            int_part = re.sub(r"\D", "", parts[0])
            cent_part = re.sub(r"\D", "", parts[1])[:2].ljust(2, "0")
            val_int = int(int_part) if int_part else 0
            return f"{val_int:,}".replace(",", ".") + f",{cent_part}"

    if s.endswith(",00") or s.endswith(".00"):
        s = s[:-3]

    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    val_int = int(digits)
    return f"{val_int:,}".replace(",", ".") + ",00"

