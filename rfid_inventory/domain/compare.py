"""Comparación pura esperados vs hallados (sin lector ni interfaz)."""


class ResultadoComparacion:
    """Tres listas de EPC (hex): coincidencias, faltantes y etiquetas no esperadas."""

    def __init__(self, encontrados, faltantes, nuevos):
        self.encontrados = encontrados
        self.faltantes = faltantes
        self.nuevos = nuevos


def comparar_esperados_y_leidos(esperados, leidos):
    """Compara dos conjuntos de EPC (hex en minúsculas) y devuelve un ``ResultadoComparacion``."""
    lista_encontrados = sorted(list(esperados.intersection(leidos)))
    lista_faltantes = sorted(list(esperados.difference(leidos)))
    lista_nuevos = sorted(list(leidos.difference(esperados)))
    return ResultadoComparacion(
        encontrados=lista_encontrados, faltantes=lista_faltantes, nuevos=lista_nuevos
    )
