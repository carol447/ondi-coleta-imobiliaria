console.log("🧩 Background Zap imoveis Scraper carregado");

const SERVER = "http://127.0.0.1:5000";

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.tipo !== "fetch_servidor") {
    return false;
  }

  (async () => {
    try {
      const endpoint = msg.endpoint || "/";
      const method = msg.method || "GET";
      const payload = msg.payload;

      const options = {
        method,
        headers: { "Content-Type": "application/json" }
      };

      if (method !== "GET" && payload !== undefined && payload !== null) {
        options.body = JSON.stringify(payload);
      }

      const resposta = await fetch(`${SERVER}${endpoint}`, options);
      const texto = await resposta.text();

      let data = null;
      try {
        data = texto ? JSON.parse(texto) : null;
      } catch (e) {
        data = texto;
      }

      sendResponse({
        ok: resposta.ok,
        status: resposta.status,
        data
      });
    } catch (erro) {
      sendResponse({
        ok: false,
        status: 0,
        erro: erro && erro.message ? erro.message : String(erro)
      });
    }
  })();

  // Mantém o canal aberto para resposta assíncrona.
  return true;
});
