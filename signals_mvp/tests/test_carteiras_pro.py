"""PEDIDO 2026-10-27 (H8): testes de signals_mvp/pos_runner/carteiras_pro.py -- base58/32 bytes,
dedup, agrupamento por pessoa (heuristica deterministica) e o trava-lista (sha256+versao em meta,
IMUTAVEL)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner import carteiras_pro as cp
from ..storage import Storage

# endereco REAL da lista (4YdHuvKYgS4xbEzpp6C59B8XGpfq3nKddAEp5dDNwGHA) -- usado so pra ter um
# base58 valido de pubkey Solana (32 bytes) sem depender da lista real inteira nos testes puros.
ENDERECO_VALIDO = "4YdHuvKYgS4xbEzpp6C59B8XGpfq3nKddAEp5dDNwGHA"


class Base58DecodeTests(unittest.TestCase):
    def test_a_real_solana_pubkey_decodes_to_exactly_32_bytes(self) -> None:
        self.assertEqual(len(cp.base58_decode(ENDERECO_VALIDO)), 32)

    def test_a_character_outside_the_alphabet_raises_value_error(self) -> None:
        for invalido in ("0", "O", "I", "l"):
            with self.assertRaises(ValueError):
                cp.base58_decode(f"4YdHuvKYgS4xbEzpp6C59B8XGpfq3nKddAEp5dDNwGH{invalido}")

    def test_a_short_address_decodes_to_fewer_than_32_bytes(self) -> None:
        self.assertLess(len(cp.base58_decode("11")), 32)


class GrupoDeTests(unittest.TestCase):
    def test_numeric_suffix_variants_share_the_same_group(self) -> None:
        self.assertEqual(cp.grupo_de("dani1"), cp.grupo_de("dani5"))
        self.assertEqual(cp.grupo_de("dani1"), cp.grupo_de("dani6"))

    def test_underscore_numeric_suffix_also_groups(self) -> None:
        self.assertEqual(cp.grupo_de("nyhrox"), cp.grupo_de("nyhrox_3"))
        self.assertEqual(cp.grupo_de("nyhrox"), cp.grupo_de("nyhrox_4"))

    def test_removable_words_are_stripped_even_when_concatenated_without_a_separator(self) -> None:
        self.assertEqual(cp.grupo_de("cup 1"), cp.grupo_de("CupMain"))
        self.assertEqual(cp.grupo_de("Dior"), cp.grupo_de("DiorMain"))
        self.assertEqual(cp.grupo_de("gake side"), cp.grupo_de("gake3"))
        self.assertEqual(cp.grupo_de("eq_side"), cp.grupo_de("eq"))

    def test_spacing_and_punctuation_differences_never_split_the_same_group(self) -> None:
        self.assertEqual(cp.grupo_de("jack duval"), cp.grupo_de("jackduval_2"))
        self.assertEqual(cp.grupo_de("dv (multi)"), cp.grupo_de("dv"))

    def test_marcell_fomo_variant_groups_with_the_plain_name(self) -> None:
        self.assertEqual(cp.grupo_de("marcell"), cp.grupo_de("marcell_FOMO"))
        self.assertEqual(cp.grupo_de("marcell"), cp.grupo_de("Marcell"))

    def test_a_typo_variant_is_never_merged_pure_deterministic_substring_only(self) -> None:
        # "nhyrox" (typo real da lista) NUNCA agrupa com "nyhrox" -- a heuristica e literal, sem
        # fuzzy matching/distancia de edicao.
        self.assertNotEqual(cp.grupo_de("nyhrox"), cp.grupo_de("nhyrox"))

    def test_a_name_without_a_trailing_digit_stays_distinct_from_the_numeric_stem(self) -> None:
        # "orangie" NUNCA agrupa com "orange" -- so sufixo NUMERICO e removido, nao qualquer prefixo
        # comum (a heuristica pedida nao inclui stemming).
        self.assertNotEqual(cp.grupo_de("orange"), cp.grupo_de("orangie"))

    def test_group_key_is_never_empty(self) -> None:
        self.assertTrue(cp.grupo_de("new"))
        self.assertTrue(cp.grupo_de("123"))


class ListaRealTests(unittest.TestCase):
    """Guarda-de-regressao sobre o arquivo REAL ja salvo em signals_mvp/dados/ -- qualquer edicao
    futura do arquivo precisa justificar uma mudanca nestes numeros (lista_versao nova)."""

    def test_the_real_file_has_121_unique_valid_addresses_and_no_duplicates(self) -> None:
        val = cp.validar_lista()
        self.assertEqual(val.n_entradas, 121)
        self.assertEqual(val.n_validas, 121)
        self.assertEqual(val.n_unicas, 121)
        self.assertEqual(val.invalidas, [])
        self.assertEqual(val.duplicadas, [])

    def test_the_real_file_groups_into_79_people_with_21_multi_wallet_groups(self) -> None:
        linhas = cp.gerar_grupos()
        self.assertEqual(len(linhas), 121)
        self.assertEqual(cp.contar_pessoas(linhas), 79)
        multi = cp.grupos_com_mais_de_uma_carteira(linhas)
        self.assertEqual(len(multi), 21)
        contagem = dict(multi)
        self.assertEqual(contagem["aloh"], 7)
        self.assertEqual(contagem["dani"], 6)
        self.assertEqual(contagem["marcell"], 5)
        for esperado in ("cup", "doc", "orange", "gake", "lunarfang", "nyhrox"):
            self.assertIn(esperado, contagem)


class ValidarListaSinteticaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="carteiras_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _escrever(self, entradas: list[dict]) -> Path:
        path = self.tmp / "lista.json"
        path.write_text(json.dumps(entradas), encoding="utf-8")
        return path

    def test_an_invalid_character_is_reported_without_raising(self) -> None:
        path = self._escrever([
            {"trackedWalletAddress": ENDERECO_VALIDO, "name": "ok", "emoji": "x", "alertsOn": True},
            {"trackedWalletAddress": "0INVALIDO", "name": "ruim", "emoji": "x", "alertsOn": True},
        ])
        val = cp.validar_lista(path)
        self.assertEqual(val.n_entradas, 2)
        self.assertEqual(val.n_validas, 1)
        self.assertEqual(len(val.invalidas), 1)
        self.assertEqual(val.invalidas[0].motivo, "caractere fora do alfabeto base58")

    def test_a_short_decoded_address_is_reported_as_invalid(self) -> None:
        path = self._escrever([{"trackedWalletAddress": "11", "name": "curto", "emoji": "x", "alertsOn": True}])
        val = cp.validar_lista(path)
        self.assertEqual(len(val.invalidas), 1)
        self.assertIn("esperado 32", val.invalidas[0].motivo)

    def test_a_duplicate_address_is_counted_once_and_reported(self) -> None:
        path = self._escrever([
            {"trackedWalletAddress": ENDERECO_VALIDO, "name": "a", "emoji": "x", "alertsOn": True},
            {"trackedWalletAddress": ENDERECO_VALIDO, "name": "b", "emoji": "x", "alertsOn": True},
        ])
        val = cp.validar_lista(path)
        self.assertEqual(val.n_entradas, 2)
        self.assertEqual(val.n_unicas, 1)
        self.assertEqual(val.duplicadas, [ENDERECO_VALIDO])

    def test_alertson_and_emoji_are_never_read(self) -> None:
        path = self._escrever([{"trackedWalletAddress": ENDERECO_VALIDO, "name": "x"}])   # sem emoji/alertsOn
        val = cp.validar_lista(path)
        self.assertEqual(val.n_unicas, 1)


class GarantirListaRegistradaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="carteiras_meta_"))
        self.storage = Storage(make_paths(self.tmp))
        self.path = self.tmp / "lista.json"
        self.csv = self.tmp / "grupos.csv"
        self.path.write_text(json.dumps([
            {"trackedWalletAddress": ENDERECO_VALIDO, "name": "dani1", "emoji": "x", "alertsOn": True},
        ]), encoding="utf-8")

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_call_registers_sha256_versao_and_counts(self) -> None:
        val = cp.garantir_lista_registrada(self.storage, self.path, self.csv)
        self.assertEqual(self.storage.get_meta(cp.META_KEY_SHA256), val.sha256)
        self.assertEqual(self.storage.get_meta(cp.META_KEY_VERSAO), "1")
        self.assertEqual(self.storage.get_meta(cp.META_KEY_N_CARTEIRAS), "1")
        self.assertEqual(self.storage.get_meta(cp.META_KEY_N_PESSOAS), "1")
        self.assertTrue(self.csv.exists())

    def test_unchanged_files_never_raise_on_later_calls(self) -> None:
        cp.garantir_lista_registrada(self.storage, self.path, self.csv)
        cp.garantir_lista_registrada(self.storage, self.path, self.csv)   # nao levanta

    def test_editing_the_list_after_registration_raises(self) -> None:
        cp.garantir_lista_registrada(self.storage, self.path, self.csv)
        self.path.write_text(json.dumps([
            {"trackedWalletAddress": ENDERECO_VALIDO, "name": "outro", "emoji": "x", "alertsOn": True},
        ]), encoding="utf-8")
        with self.assertRaises(cp.ListaAlteradaError):
            cp.garantir_lista_registrada(self.storage, self.path, self.csv)

    def test_editing_the_groups_csv_after_registration_also_raises(self) -> None:
        cp.garantir_lista_registrada(self.storage, self.path, self.csv)
        self.csv.write_text("endereco,nome,grupo\nXXX,YYY,ZZZ\n", encoding="utf-8")
        with self.assertRaises(cp.ListaAlteradaError):
            cp.garantir_lista_registrada(self.storage, self.path, self.csv)


if __name__ == "__main__":
    unittest.main()
