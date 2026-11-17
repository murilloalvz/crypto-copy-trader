"""RODADA 22 (2026-11-17): `solana_pda.find_program_address` -- PDA do Solana, so stdlib. O par
wallet/mint/ATA abaixo foi observado AO VIVO nesta sessao (`getTokenAccountsByOwner` contra
api.mainnet-beta.solana.com, mint authority real da USDC) -- nunca um vetor de teste memorizado,
exatamente pra nao arriscar transcrever hex/base58 de cabeca."""

from __future__ import annotations

import unittest

from ..pos_runner.carteiras_pro import base58_decode
from ..pos_runner.solana_pda import base58_encode, create_program_address, find_program_address

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"


class Base58RoundTripTests(unittest.TestCase):
    def test_encode_decode_round_trip_para_enderecos_conhecidos(self) -> None:
        for endereco in (TOKEN_PROGRAM, ATA_PROGRAM, "11111111111111111111111111111111",
                        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"):
            self.assertEqual(base58_encode(base58_decode(endereco)), endereco)

    def test_zeros_a_esquerda_preservados(self) -> None:
        dados = b"\x00\x00" + b"\x01" * 30
        self.assertEqual(base58_decode(base58_encode(dados)), dados)


class FindProgramAddressTests(unittest.TestCase):
    def test_bate_com_a_associated_token_account_real_observada_ao_vivo(self) -> None:
        """Par (wallet, mint) -> ATA observado via getTokenAccountsByOwner nesta sessao (mint
        authority real da USDC, EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v) -- confirma o
        algoritmo (create_program_address/find_program_address) contra dado on-chain real, nunca so
        contra um vetor de teste copiado de memoria."""
        wallet = base58_decode("BJE5MMbqXjVwjAF7oxwPYXnTXDyspzZyt4vwenNw5ruG")
        mint = base58_decode("JA1SyycEdeuVxNfJyXnhP63E37MFbmUTBd2uDgavZE9L")
        ata = find_program_address([wallet, base58_decode(TOKEN_PROGRAM), mint], ATA_PROGRAM)
        self.assertEqual(ata, "22iBCoc79WvQvaGvAiPkVmBWfhYVWzdsvbPJRnhGzFNK")

    def test_e_deterministico(self) -> None:
        seeds = [b"bonding-curve", base58_decode("JA1SyycEdeuVxNfJyXnhP63E37MFbmUTBd2uDgavZE9L")]
        a = find_program_address(seeds, "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        b = find_program_address(seeds, "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        self.assertEqual(a, b)


class BondingCurveSeedFixtureTests(unittest.TestCase):
    """RODADA 22 (2026-11-17), condicao 1 do operador: confirmar o seed ['bonding-curve', mint] do
    pump.fun contra DADOS REAIS -- 4 pares (mint, bonding-curve) observados AO VIVO nesta sessao
    (getTransaction/jsonParsed contra api.mainnet-beta.solana.com, conta referenciada na MESMA
    instrucao/CPI do programa pump.fun 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P -- posicao do
    mint/bonding-curve na lista de contas confirmada por eliminacao, nunca so copiada de um exemplo
    de SDK de terceiros). Inclui 1 par Token-2022 (`create_v2`) -- resolve a duvida sobre uma
    variante de seed 'bonding-curve-v2': o MESMO seed legado bate tambem pra esse caso, nunca
    precisou de variante nova."""

    # (mint, bonding_curve_real, descricao) -- 4 >= "ao menos 3" pedido pelo operador.
    PARES_REAIS = [
        ("83iFpecQkurgqTgUdAhcWDYgDrpoYLd8SPbF6jgCpump", "FAeMMp5VPdBSHS9C5nrGjY9Gdob9VTkHfevcUnuiWq8k",
         "legado (SPL Token)"),
        ("6ZBfHKe1ZSEh5H4VRFEZEKdXeT67hqvWeQSrYMAxpump", "EtDhyb8GrmudmAnNBN95p8rducSM7batNgWqiD6t6TgD",
         "legado (SPL Token)"),
        ("CGGPgjbGnUsjKxX2N7PzjUEVupWwvkLEEp1BZ2yBpump", "GgpcbEVsFxvgh7K2kqRn9cx6WKjTDRxBYhwC2iNu1ehR",
         "legado (SPL Token)"),
        ("7G8hoJQnT9UjogE58S7qjhSnPBs4RhQRiZiUSZ4zpump", "5Etb6aeMvoGNyLuxSFutuTpHn6NbBVHvDLHtJvYfcAzY",
         "Token-2022 (create_v2)"),
    ]

    def test_seed_bonding_curve_bate_com_4_pares_reais(self) -> None:
        for mint, curva_real, descricao in self.PARES_REAIS:
            with self.subTest(mint=mint, variante=descricao):
                curva = find_program_address([b"bonding-curve", base58_decode(mint)],
                                             "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
                self.assertEqual(curva, curva_real)

    def test_seed_v2_nunca_bate_com_os_mesmos_pares(self) -> None:
        """Confirma que 'bonding-curve-v2' NAO e o seed certo (nem pro caso legado nem pro
        Token-2022) -- descarta a hipotese da ressalva original, nunca so por omissao."""
        for mint, curva_real, _descricao in self.PARES_REAIS:
            with self.subTest(mint=mint):
                curva_v2 = find_program_address([b"bonding-curve-v2", base58_decode(mint)],
                                                "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
                self.assertNotEqual(curva_v2, curva_real)

    def test_seeds_diferentes_dao_enderecos_diferentes(self) -> None:
        mint = base58_decode("JA1SyycEdeuVxNfJyXnhP63E37MFbmUTBd2uDgavZE9L")
        a = find_program_address([b"bonding-curve", mint], "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        b = find_program_address([b"associated-bonding-curve", mint], "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        self.assertNotEqual(a, b)

    def test_resultado_e_um_endereco_base58_valido_de_32_bytes(self) -> None:
        mint = base58_decode("JA1SyycEdeuVxNfJyXnhP63E37MFbmUTBd2uDgavZE9L")
        addr = find_program_address([b"bonding-curve", mint], "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        self.assertEqual(len(base58_decode(addr)), 32)

    def test_create_program_address_nunca_fabrica_um_resultado_na_curva(self) -> None:
        # Testa as 256 tentativas de bump pra um par seeds/programa qualquer -- NENHUM resultado
        # aceito por create_program_address pode estar na curva (invariante do protocolo Solana).
        from ..pos_runner.solana_pda import _esta_na_curva

        mint = base58_decode("JA1SyycEdeuVxNfJyXnhP63E37MFbmUTBd2uDgavZE9L")
        program = base58_decode("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        for bump in range(256):
            try:
                addr = create_program_address([b"bonding-curve", mint, bytes([bump])], program)
            except ValueError:
                continue
            self.assertFalse(_esta_na_curva(addr))


if __name__ == "__main__":
    unittest.main()
