(function () {
  function semAcentos(valor) {
    return String(valor || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  function textoIndicaSemResultados(valor) {
    const corpo = semAcentos(valor);
    return corpo.includes("nenhum imovel encontrado com esses filtros") ||
      corpo.includes("por enquanto, nenhum resultado corresponde a sua busca") ||
      corpo.includes("nao encontramos imoveis com correspondencia exata") ||
      corpo.includes("nenhum imovel com correspondencia exata") ||
      corpo.includes("nao encontramos resultados exatos");
  }

  function urlEhRecomendacao(valor, origem = "https://www.zapimoveis.com.br/") {
    try {
      const source = new URL(valor, origem).searchParams.get("source") || "";
      return /(?:^|,)showcase(?:,|$)/i.test(source);
    } catch {
      return false;
    }
  }

  globalThis.ZAP_V4_CLASSIFICADORES = Object.freeze({ semAcentos, textoIndicaSemResultados, urlEhRecomendacao });
})();
