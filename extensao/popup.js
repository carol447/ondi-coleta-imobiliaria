function setStatus(texto) {
  const el = document.getElementById("status");
  if (el) el.innerText = texto;
}

function formatarTempo(segundos) {
  if (segundos === null || segundos === undefined || segundos === "-") return "-";
  const total = Number(segundos) || 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
}

function enviar(action) {
  setStatus(`Enviando comando: ${action}...`);

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) {
      setStatus("Erro: nenhuma aba ativa encontrada.");
      return;
    }

    chrome.tabs.sendMessage(tabs[0].id, { action }, (resposta) => {
      if (chrome.runtime.lastError) {
        setStatus(
          "Erro: abra uma pagina do Zap Imoveis, atualize com F5 e recarregue a extensao em chrome://extensions/.\n\n" +
          chrome.runtime.lastError.message
        );
        return;
      }

      if (resposta && resposta.estado) {
        atualizarStatus(resposta.estado, resposta.servidor || null);
      } else {
        setStatus("Comando enviado, mas a pagina nao retornou status. Atualize com F5 e tente de novo.");
      }
    });
  });
}

function chamarServidor(endpoint, method = "GET", payload = null) {
  return new Promise((resolve) => {
    const worker = localStorage.getItem("zap_popup_worker") || "worker1";
    const sep = endpoint.includes("?") ? "&" : "?";
    chrome.runtime.sendMessage(
      {
        tipo: "fetch_servidor",
        endpoint: `${endpoint}${sep}worker=${encodeURIComponent(worker)}`,
        method,
        payload: payload ? { worker, ...payload } : { worker }
      },
      (resposta) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, erro: chrome.runtime.lastError.message });
          return;
        }
        resolve(resposta);
      }
    );
  });
}

function atualizarStatus(estado, servidor) {
  const stats = servidor && servidor.stats ? servidor.stats : {};
  const worker = (servidor && servidor.worker) || estado.worker || estado.workerId || "worker1";
  localStorage.setItem("zap_popup_worker", worker);

  const linhas = [
    `Worker: ${worker}`,
    `Rodando: ${estado.rodando ? "sim" : "nao"}`,
    `Municipio atual: ${estado.municipioAtual || stats.municipio_atual || "-"}`,
    `Pagina atual: ${estado.paginaAtual || stats.pagina_atual || 1}`,
    `Tempo da cidade: ${formatarTempo(stats.tempo_cidade_segundos || 0)}`,
    `Tempo total: ${formatarTempo(stats.tempo_total_segundos || 0)}`,
    `Municipios concluidos: ${stats.municipios_concluidos || estado.municipiosConcluidos || 0}`,
    `Municipios restantes: ${stats.municipios_restantes ?? estado.municipiosRestantes ?? "-"}`,
    `Velocidade media: ${stats.velocidade_media_paginas_min || 0} pag/min`,
    `Estimativa de termino: ${formatarTempo(stats.estimativa_termino_segundos)}`,
    `Fila da pagina: ${(estado.filaLinks || []).length}`,
    `Indice da fila: ${estado.filaIndex || 0}`,
    `Detalhes salvos: ${estado.detalhesSalvos || servidor?.total_detalhes || 0}`,
    `Ultimo status: ${estado.ultimoStatus || "-"}`
  ];

  if (servidor) {
    linhas.push(`Pasta: ${servidor.pasta_cidade || "-"}`);
    linhas.push(`Excel: ${servidor.arquivo_excel_final || "gerar ao final"}`);
  }

  setStatus(linhas.join("\n"));
}

async function exportarExcel() {
  setStatus("Gerando Excel final...");

  const resposta = await chamarServidor("/exportar-excel", "POST", {});

  if (!resposta || !resposta.ok) {
    setStatus(
      `Erro ao gerar Excel: ${resposta && resposta.erro ? resposta.erro : "verifique se o servidor esta ligado"}`
    );
    return;
  }

  const data = resposta.data || {};
  setStatus([
    "Excel final gerado com sucesso!",
    `Detalhes: ${data.total_detalhes || 0}`,
    `URLs: ${data.total_lista || 0}`,
    `Arquivo: ${data.arquivo_excel_final || "-"}`
  ].join("\n"));
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("start").onclick = () => enviar("start");
  document.getElementById("stop").onclick = () => enviar("stop");
  document.getElementById("reset").onclick = () => enviar("reset");
  document.getElementById("exportar").onclick = exportarExcel;

  enviar("status");
});
