class ComparisonResult:
    def __init__(self, encontrados, faltantes, nuevos):
        self.encontrados = encontrados
        self.faltantes = faltantes
        self.nuevos = nuevos


def compare_expected_found(expected, found):
    encontrados = sorted(list(expected.intersection(found)))
    faltantes = sorted(list(expected.difference(found)))
    nuevos = sorted(list(found.difference(expected)))
    return ComparisonResult(encontrados=encontrados, faltantes=faltantes, nuevos=nuevos)

