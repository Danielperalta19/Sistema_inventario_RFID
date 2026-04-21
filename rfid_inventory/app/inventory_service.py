from rfid_inventory.domain import compare_expected_found


class InventoryService:
    """
    Capa de aplicación: une catálogo (esperados) + lecturas (scanner) + comparación (dominio).

    La UI solo debería llamar a este servicio y renderizar resultados.
    """

    def __init__(self, locations, scanner):
        self._locations = locations
        self._scanner = scanner

    def get_expected_set(self, location_name):
        return set(self._locations.get(location_name, []))

    def expected_count(self, location_name):
        return len(self._locations.get(location_name, []))

    def compare_location(self, location_name):
        expected = self.get_expected_set(location_name)
        snap = self._scanner.snapshot()
        found = set(snap["seen_epcs"])
        result = compare_expected_found(expected, found)
        return result, snap, expected

