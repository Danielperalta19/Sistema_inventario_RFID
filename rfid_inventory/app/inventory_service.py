"""Inventario por ubicación: catálogo + escáner + comparación de dominio."""

from rfid_inventory.domain import comparar_esperados_y_leidos


class ServicioInventario:
    """
    Capa de aplicación: une catálogo (esperados) + lecturas del escáner + comparación (dominio).

    La UI solo debería llamar a este servicio y renderizar resultados.
    """

    def __init__(self, mapa_ubicacion_a_epcs, escaner):
        self._mapa_ubicacion_a_epcs = mapa_ubicacion_a_epcs
        self._escaner = escaner

    def conjunto_esperados(self, nombre_ubicacion):
        return set(self._mapa_ubicacion_a_epcs.get(nombre_ubicacion, []))

    def cantidad_esperados(self, nombre_ubicacion):
        return len(self._mapa_ubicacion_a_epcs.get(nombre_ubicacion, []))

    def comparar_ubicacion(self, nombre_ubicacion):
        esperados = self.conjunto_esperados(nombre_ubicacion)
        muestra = self._escaner.instantanea()
        encontrados = set(muestra["seen_epcs"])
        resultado = comparar_esperados_y_leidos(esperados, encontrados)
        return resultado, muestra, esperados
