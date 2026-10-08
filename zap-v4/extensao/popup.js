const statusEl = () => document.getElementById("status");
function mostrar(s) {
  const e = s.estado || {}, servidor = s.servidor || {};
  const tarefa = e.tarefaAtual || {};
  const fila = servidor.maestro || {};
  statusEl().innerText = [
    `Worker: ${e.worker || "-"}`,
    `Município: ${tarefa.municipio ? `${tarefa.municipio}/${tarefa.uf}` : "-"}`,
    `Tipo: ${tarefa.tipo_rotulo || "-"}`,
    `Rodando: ${e.rodando ? "sim" : "não"}`, `Página: ${e.paginaAtual || 1}/50`,
    `Cards deste worker: ${servidor.total_worker ?? e.totalCards ?? 0}`,
    `Fila: ${fila.por_status?.PENDENTE ?? 0} pendentes · ${fila.por_status?.RESERVADA ?? 0} ativas`,
    `Status: ${e.ultimoStatus || "-"}`, `Atualização: ${e.ultimaAtualizacao || "-"}`
  ].join("\n");
}
function comando(action) {
  statusEl().innerText = `Enviando ${action}...`;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs?.[0]) return statusEl().innerText = "Nenhuma aba ativa.";
    chrome.tabs.sendMessage(tabs[0].id, { action }, (r) => {
      if (chrome.runtime.lastError) return statusEl().innerText = "Abra uma página do ZAP, dê F5 e tente novamente.\n" + chrome.runtime.lastError.message;
      mostrar(r || {});
    });
  });
}
function servidor(endpoint, method = "GET") {
  return new Promise((resolve) => chrome.runtime.sendMessage({ tipo: "fetch_servidor", endpoint, method, payload: {} }, resolve));
}
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("start").onclick = () => comando("start");
  document.getElementById("stop").onclick = () => comando("stop");
  document.getElementById("reset").onclick = () => comando("reset");
  document.getElementById("exportar").onclick = async () => {
    statusEl().innerText = "Gerando Excel..."; const r = await servidor("/exportar-excel", "POST");
    statusEl().innerText = r?.ok ? `Excel gerado.\n${r.data?.arquivo_excel_final}\nTotal: ${r.data?.total || 0}` : `Erro: ${r?.erro || r?.data?.erro || "servidor desligado"}`;
  };
  document.getElementById("telegram").onclick = async () => {
    statusEl().innerText = "Testando Telegram..."; const r = await servidor("/telegram/testar", "POST");
    statusEl().innerText = r?.ok ? "Mensagem de teste enviada ao Telegram." : `Falha no Telegram: ${r?.data?.erro || r?.erro || "verifique a configuração"}`;
  };
  comando("status");
});
